"""Defense in depth for unsigned Strava webhook events.

Strava does not sign push events, so destructive changes are only applied after
Strava itself confirms them through the API.
"""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.models import Activity, Athlete, StravaWebhookEvent
from app.services import (
    StravaAuthError, StravaClient, StravaForbiddenError, StravaNotFoundError, StravaRateLimitError,
    StravaTransientError, api_metrics,
)
from app.strava_events import MAX_ATTEMPTS, parse_event, process_event, record_event, requeue_unverified_deletes
from tests.test_initial_import import app_client  # noqa: F401  (fixture)
from tests.test_strava_events import BASE_TIME, FakeClient, make_athlete, summary


def stored_activity(db, athlete, activity_id=321, **extra):
    db.add(Activity(athlete=athlete, strava_activity_id=activity_id, name="Kept", sport_type="Run",
                    normalized_sport="run", start_date=datetime.now(UTC), distance_m=1000, **extra))
    db.commit()


def deliver(db, aspect="delete", object_id=321, owner=9001, offset=0, updates=None, object_type="activity"):
    stored, is_new = record_event(db, {"object_type": object_type, "aspect_type": aspect, "object_id": object_id, "owner_id": owner,
                                       "event_time": BASE_TIME + offset, "subscription_id": 7, "updates": updates or {}})
    assert stored is not None
    return stored.id, is_new


def outcome(db, event_id):
    item = db.get(StravaWebhookEvent, event_id)
    db.refresh(item)
    return item.status, item.outcome


def activity_count(db):
    return db.query(Activity).count()


# --- forged vs. legitimate deletions ---------------------------------------

def test_forged_delete_is_not_applied_when_strava_still_serves_the_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    client = FakeClient(summary(activity_id=321, name="Still on Strava", distance=1000))
    event_id, _ = deliver(db)

    process_event(db, event_id, client)

    assert outcome(db, event_id) == ("ignored", "delete_not_confirmed")
    assert db.query(Activity).one().name == "Still on Strava"  # kept and refreshed
    assert len(client.calls) == 1


def test_legitimate_delete_confirmed_by_404_removes_the_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(StravaNotFoundError("Record Not Found")))

    assert outcome(db, event_id) == ("processed", "deleted")
    assert activity_count(db) == 0


def test_delete_for_an_activity_not_stored_makes_no_api_call(db, fake_token):
    make_athlete(db)
    client = FakeClient()
    event_id, _ = deliver(db)

    process_event(db, event_id, client)

    assert outcome(db, event_id) == ("processed", "already_absent") and client.calls == []


def test_duplicate_delete_deliveries_verify_once(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    first, new_first = deliver(db)
    second, new_second = deliver(db)
    client = FakeClient(StravaNotFoundError("gone"))

    process_event(db, first, client)
    assert process_event(db, second, client) is None

    assert new_first and not new_second and first == second
    assert activity_count(db) == 0 and len(client.calls) == 1


def test_delete_for_an_activity_owned_by_someone_else_is_ignored(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(summary(activity_id=321, owner=5555)))

    assert outcome(db, event_id) == ("ignored", "owner_mismatch") and activity_count(db) == 1


def test_delete_that_turns_out_to_be_a_privacy_change_removes_the_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(summary(activity_id=321, private=True, visibility="only_me")))

    assert outcome(db, event_id) == ("processed", "removed_private") and activity_count(db) == 0


# --- privacy changes ----------------------------------------------------------

def test_forged_private_update_does_not_remove_a_public_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner, activity_id=123)
    event_id, _ = deliver(db, "update", object_id=123, updates={"private": "true"})

    process_event(db, event_id, FakeClient(summary(visibility="everyone")))

    assert outcome(db, event_id) == ("processed", "upserted") and activity_count(db) == 1


def test_private_activity_is_kept_with_read_all_and_removed_without_it(db, fake_token):
    keeps = make_athlete(db, strava_id=1, scopes="activity:read_all,read")
    loses = make_athlete(db, strava_id=2)
    stored_activity(db, keeps, activity_id=10)
    stored_activity(db, loses, activity_id=20)
    first, _ = deliver(db, "update", object_id=10, owner=1, updates={"private": "true"})
    second, _ = deliver(db, "update", object_id=20, owner=2, updates={"private": "true"})

    process_event(db, first, FakeClient(summary(activity_id=10, owner=1, private=True, visibility="only_me")))
    process_event(db, second, FakeClient(summary(activity_id=20, owner=2, private=True, visibility="only_me")))

    remaining = db.query(Activity).one()
    assert (remaining.strava_activity_id, remaining.visibility) == (10, "only_me")


# --- 401 / 403 / 404 ------------------------------------------------------------

def test_403_on_the_activity_means_it_is_no_longer_accessible_and_is_removed(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(StravaForbiddenError("forbidden", scope_missing=False)))

    assert outcome(db, event_id) == ("processed", "not_accessible") and activity_count(db) == 0


def test_403_for_a_missing_token_scope_keeps_data_and_stops_using_the_athlete(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(StravaForbiddenError("scope", scope_missing=True)))

    db.refresh(owner)
    assert outcome(db, event_id) == ("failed", "permission_denied")
    assert activity_count(db) == 1
    assert (owner.auth_status, owner.auth_error) == ("reauth_required", "activity_scope_missing")


def test_401_is_refreshed_once_then_the_delete_is_verified(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(StravaAuthError("expired"), StravaNotFoundError("gone")))

    assert fake_token == [False, True]
    assert outcome(db, event_id) == ("processed", "deleted")


def test_persistent_401_keeps_the_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(StravaAuthError("401"), StravaAuthError("401")))

    assert outcome(db, event_id) == ("failed", "athlete_auth_invalid") and activity_count(db) == 1


def test_403_body_with_missing_scope_is_classified(monkeypatch):
    bodies = {
        1: {"message": "Authorization Error", "errors": [{"resource": "AccessToken", "field": "activity:read_permission", "code": "missing"}]},
        2: {"message": "Forbidden", "errors": [{"resource": "Activity", "field": "id", "code": "forbidden"}]},
    }
    client = StravaClient(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json=bodies[int(r.url.path.rsplit("/", 1)[1])]))))
    with pytest.raises(StravaForbiddenError) as scope:
        client.activity("token", 1)
    with pytest.raises(StravaForbiddenError) as activity:
        client.activity("token", 2)
    assert scope.value.scope_missing is True and activity.value.scope_missing is False


# --- 429 / 5xx / timeouts never delete ---------------------------------------

@pytest.mark.parametrize("error", [StravaRateLimitError("429", retry_after=120), StravaTransientError("503"), StravaTransientError("timeout")])
def test_rate_limits_server_errors_and_timeouts_never_delete(db, fake_token, error):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient(error))

    assert outcome(db, event_id)[0] == "retry" and activity_count(db) == 1


def test_real_http_timeout_during_delete_verification_is_retried(db, monkeypatch, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    def timeout(request):
        raise httpx.ConnectTimeout("slow", request=request)

    process_event(db, event_id, StravaClient(httpx.Client(transport=httpx.MockTransport(timeout))))

    assert outcome(db, event_id)[0] == "retry" and activity_count(db) == 1


def test_exhausted_retries_keep_the_activity(db, fake_token):
    owner = make_athlete(db)
    stored_activity(db, owner)
    event_id, _ = deliver(db)
    client = FakeClient(*[StravaTransientError("503")] * MAX_ATTEMPTS)
    for _ in range(MAX_ATTEMPTS):
        item = db.get(StravaWebhookEvent, event_id)
        item.next_attempt_at = None
        db.commit()
        process_event(db, event_id, client)

    assert outcome(db, event_id) == ("failed", "retries_exhausted") and activity_count(db) == 1


# --- disconnected athletes -----------------------------------------------------

def test_delete_for_a_disconnected_athlete_is_kept_then_rechecked_on_reconnect(db, fake_token):
    owner = make_athlete(db, auth_status="reauth_required", is_active=False)
    stored_activity(db, owner)
    event_id, _ = deliver(db)

    process_event(db, event_id, FakeClient())
    assert outcome(db, event_id) == ("failed", "delete_unverified_disconnected") and activity_count(db) == 1

    owner.auth_status, owner.is_active = "connected", True
    db.commit()
    assert requeue_unverified_deletes(db, 9001) == 1
    process_event(db, event_id, FakeClient(StravaNotFoundError("gone")))
    assert outcome(db, event_id) == ("processed", "deleted") and activity_count(db) == 0


# --- payload validation ---------------------------------------------------------

def valid(**overrides):
    payload = {"object_type": "activity", "aspect_type": "delete", "object_id": 321, "owner_id": 9001,
               "event_time": BASE_TIME, "subscription_id": 7, "updates": {}}
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("payload", [
    valid(object_id="321"),
    valid(object_id=3.5),
    valid(object_id=True),
    valid(owner_id=-1),
    valid(subscription_id=None),
    valid(event_time=None),
    valid(object_type="segment"),
    valid(aspect_type="destroy"),
    valid(object_type="athlete", aspect_type="create", object_id=9001, updates={"authorized": "false"}),
    valid(object_type="athlete", aspect_type="update", object_id=1234, updates={"authorized": "false"}),
    valid(object_type="athlete", aspect_type="update", object_id=9001, updates={}),
    valid(aspect_type="update", updates={"private": "maybe"}),
    valid(aspect_type="update", updates={"distance": "0"}),
    valid(aspect_type="update", updates={"title": "x" * 256}),
    valid(aspect_type="update", updates={"title": 5}),
    valid(updates=["not", "a", "dict"]),
    valid(event_time=int((datetime.now(UTC) - timedelta(days=8)).timestamp())),
    valid(event_time=int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
])
def test_malformed_or_implausible_events_are_rejected(payload):
    assert parse_event(payload) is None


def test_documented_event_shapes_are_accepted():
    assert parse_event(valid())
    assert parse_event(valid(aspect_type="update", updates={"title": "Lunch Run", "type": "Run", "private": "true"}))
    assert parse_event(valid(object_type="athlete", aspect_type="update", object_id=9001, updates={"authorized": "false"}))
    assert parse_event(valid(object_type="athlete", aspect_type="update", object_id=9001, updates={"authorized": False}))


def test_oversized_webhook_bodies_are_refused(db, monkeypatch):
    monkeypatch.setattr(main, "get_db", lambda: iter([db]))
    client = TestClient(main.app)
    response = client.post("/webhooks/strava", content=b'{"pad": "' + b"x" * 5000 + b'"}', headers={"content-type": "application/json"})
    assert response.status_code == 413
    assert db.query(StravaWebhookEvent).count() == 0


# --- API budget protection -------------------------------------------------------

def test_calls_are_deferred_when_usage_nears_the_limit_without_hitting_strava():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "91,200"}, json={"id": 1})

    client = StravaClient(httpx.Client(transport=httpx.MockTransport(handler)))
    client.activity("token", 1)
    with pytest.raises(StravaRateLimitError) as deferred:
        client.activity("token", 2)

    assert len(requests) == 1
    assert 0 < deferred.value.retry_after <= 15 * 60 + 1


def test_usage_from_a_previous_window_does_not_block():
    now = datetime(2026, 11, 10, 10, 20, tzinfo=UTC)
    api_metrics.last_usage = {"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "99,200"}
    api_metrics.last_usage_at = datetime(2026, 11, 10, 10, 10, tzinfo=UTC)  # previous 15-minute window
    assert api_metrics.near_limit_for(now=now) == 0

    api_metrics.last_usage = {"X-RateLimit-Limit": "100,1000", "X-RateLimit-Usage": "5,950"}
    assert api_metrics.near_limit_for(now=now) > 3600  # daily budget: wait for midnight UTC


def test_oauth_reconnection_requeues_unverified_deletes(db, app_client):  # noqa: F811
    connect, _, _ = app_client
    connect()
    athlete = db.query(Athlete).one()
    stored_activity(db, athlete, activity_id=999)
    athlete.auth_status, athlete.is_active, athlete.last_sync_at = "reauth_required", False, datetime.now(UTC)
    db.commit()
    event_id, _ = deliver(db, owner=athlete.strava_athlete_id, object_id=999)
    process_event(db, event_id, FakeClient())
    assert outcome(db, event_id) == ("failed", "delete_unverified_disconnected")

    connect()

    item = db.get(StravaWebhookEvent, event_id)
    db.refresh(item)
    assert (item.status, item.attempts) == ("retry", 0)
    # Still waiting for Strava's confirmation: nothing was deleted on reconnect.
    assert db.query(Activity).filter_by(strava_activity_id=999).count() == 1
