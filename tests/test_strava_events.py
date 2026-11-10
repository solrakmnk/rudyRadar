"""Event processing: idempotency, ordering, retries, tokens and deauthorization."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet

from app import strava_events
from app.config import get_settings
from app.models import Activity, Athlete, StravaWebhookEvent
from app.services import (
    Crypto, StravaAuthError, StravaClient, StravaNotFoundError, StravaRateLimitError, StravaTransientError,
    api_metrics, get_valid_access_token, seconds_until_rate_limit_reset,
)
from app.strava_events import process_due_events, process_event, record_event


def make_athlete(db, strava_id=9001, scopes="activity:read,profile:read_all,read", **extra):
    fields = {"is_active": True, "is_club_member": True, **extra}
    item = Athlete(strava_athlete_id=strava_id, firstname="Rudo", lastname="Test", access_token_encrypted="x",
                   refresh_token_encrypted="y", token_expires_at=datetime.now(UTC) + timedelta(hours=1),
                   authorized_scopes=scopes, **fields)
    db.add(item)
    db.commit()
    return item


def summary(activity_id=123, owner=9001, **extra):
    return {"id": activity_id, "athlete": {"id": owner}, "name": "Morning swim", "sport_type": "Swim",
            "start_date": "2026-10-02T12:00:00Z", "distance": 1500, "moving_time": 1800, "visibility": "everyone", **extra}


class FakeClient:
    """Counts Strava calls; ``responses`` is a list of items or exceptions returned in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def activity(self, token, activity_id):
        self.calls.append(("activity", activity_id, token))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def event(db, aspect="create", object_id=123, owner=9001, event_time=1000, object_type="activity", updates=None):
    payload = {"object_type": object_type, "aspect_type": aspect, "object_id": object_id, "owner_id": owner,
               "event_time": event_time, "subscription_id": 7, "updates": updates or {}}
    stored, is_new = record_event(db, payload)
    assert is_new
    return stored.id


def status(db, event_id):
    item = db.get(StravaWebhookEvent, event_id)
    db.refresh(item)
    return item.status, item.outcome


# --- create / update / delete ------------------------------------------------

def test_new_activity_is_fetched_once_and_stored(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary())
    event_id = event(db)

    assert process_event(db, event_id, client) == "upserted"
    assert db.query(Activity).one().name == "Morning swim"
    assert len(client.calls) == 1
    assert db.query(Athlete).one().last_sync_at is not None


def test_title_and_type_updates_are_applied_without_calling_strava(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Old", sport_type="Run", normalized_sport="run", start_date=datetime.now(UTC)))
    db.commit()
    client = FakeClient()

    outcome = process_event(db, event(db, "update", updates={"title": "Renamed", "type": "Ride"}), client)

    activity = db.query(Activity).one()
    assert outcome == "updated_from_event"
    assert (activity.name, activity.sport_type, activity.normalized_sport) == ("Renamed", "Ride", "bike")
    assert client.calls == []


def test_other_updates_refetch_the_activity(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Old", sport_type="Swim", start_date=datetime.now(UTC)))
    db.commit()
    client = FakeClient(summary(distance=2000))

    assert process_event(db, event(db, "update", updates={"private": "false"}), client) == "upserted"
    assert db.query(Activity).one().distance_m == 2000
    assert len(client.calls) == 1


def test_update_for_unknown_activity_falls_back_to_a_fetch(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary())

    assert process_event(db, event(db, "update", updates={"title": "New"}), client) == "upserted"
    assert len(client.calls) == 1


def test_delete_removes_the_activity_without_calling_strava(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=321, name="Gone", sport_type="Run", start_date=datetime.now(UTC)))
    db.commit()
    client = FakeClient()

    assert process_event(db, event(db, "delete", object_id=321), client) == "deleted"
    assert db.query(Activity).count() == 0 and client.calls == []


def test_activity_made_private_is_removed_when_private_scope_was_not_granted(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Now private", sport_type="Run", start_date=datetime.now(UTC)))
    db.commit()
    client = FakeClient()

    assert process_event(db, event(db, "update", updates={"private": "true"}), client) == "removed_private"
    assert db.query(Activity).count() == 0 and client.calls == []


def test_private_activity_returned_by_strava_is_not_stored_without_read_all(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary(visibility="only_me", private=True))

    assert process_event(db, event(db), client) == "removed_private"
    assert db.query(Activity).count() == 0


def test_private_activity_is_kept_when_read_all_was_granted(db, fake_token):
    make_athlete(db, scopes="activity:read_all,profile:read_all,read")
    client = FakeClient(summary(visibility="only_me", private=True))

    assert process_event(db, event(db), client) == "upserted"
    assert db.query(Activity).count() == 1


def test_activity_not_found_on_strava_is_removed_locally(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Gone", sport_type="Run", start_date=datetime.now(UTC)))
    db.commit()

    assert process_event(db, event(db, "update", updates={"private": "false"}), FakeClient(StravaNotFoundError("gone"))) == "not_visible"
    assert db.query(Activity).count() == 0


# --- duplicates and ordering -----------------------------------------------

def test_duplicate_delivery_is_recorded_once_and_processed_once(db, fake_token):
    make_athlete(db)
    payload = {"object_type": "activity", "aspect_type": "create", "object_id": 123, "owner_id": 9001, "event_time": 1000}
    first, new_first = record_event(db, payload)
    second, new_second = record_event(db, payload)
    client = FakeClient(summary())

    assert new_first and not new_second and first.id == second.id
    assert process_event(db, first.id, client) == "upserted"
    assert process_event(db, second.id, client) is None  # already processed: not claimable
    assert db.query(Activity).count() == 1 and len(client.calls) == 1


def test_older_event_arriving_after_a_newer_one_is_skipped(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary(name="Latest"))
    newer = event(db, "update", event_time=2000, updates={"private": "false"})
    assert process_event(db, newer, client) == "upserted"

    older = event(db, "create", event_time=1000)
    assert process_event(db, older, client) == "stale"
    assert len(client.calls) == 1
    assert db.query(Activity).one().name == "Latest"


def test_event_superseded_by_a_queued_newer_event_does_not_call_strava(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary())
    create = event(db, "create", event_time=1000)
    event(db, "update", event_time=2000, updates={"private": "false"})

    assert process_event(db, create, client) == "superseded"
    assert client.calls == []


def test_late_create_after_delete_does_not_resurrect_the_activity(db, fake_token):
    make_athlete(db)
    client = FakeClient(summary())
    delete = event(db, "delete", event_time=2000)
    assert process_event(db, delete, client) == "already_absent"

    late_create = event(db, "create", event_time=1000)
    assert process_event(db, late_create, client) in {"already_deleted", "stale"}
    assert db.query(Activity).count() == 0 and client.calls == []


# --- athletes, tokens and deauthorization ----------------------------------

def test_deauthorization_deletes_athlete_activities_and_event_log(db, fake_token):
    owner = make_athlete(db, is_active=False)  # applies even to athletes hidden from the radar
    db.add(Activity(athlete=owner, strava_activity_id=1, name="A", sport_type="Run", start_date=datetime.now(UTC)))
    db.commit()
    old = event(db, "create", object_id=1, event_time=10)
    deauth = event(db, "update", object_type="athlete", object_id=9001, event_time=20, updates={"authorized": "false"})

    assert process_event(db, deauth, FakeClient()) == "athlete_deleted"
    assert db.query(Athlete).count() == 0 and db.query(Activity).count() == 0
    assert db.get(StravaWebhookEvent, old) is None


def test_deauthorization_accepts_boolean_false(db, fake_token):
    make_athlete(db)
    assert process_event(db, event(db, "update", object_type="athlete", object_id=9001, updates={"authorized": False}), FakeClient()) == "athlete_deleted"


def test_events_for_unknown_or_disconnected_athletes_make_no_calls(db, fake_token):
    make_athlete(db, auth_status="reauth_required")
    client = FakeClient()

    assert process_event(db, event(db, owner=9001), client) == "athlete_not_syncing"
    assert process_event(db, event(db, owner=5555, event_time=2), client) == "unknown_athlete"
    assert client.calls == []


@pytest.fixture()
def encryption(monkeypatch):
    monkeypatch.setattr(get_settings(), "token_encryption_key", Fernet.generate_key().decode())
    return Crypto()


class TokenClient(StravaClient):
    def __init__(self, refresh_result):
        self.refresh_result = refresh_result
        self.refreshed = 0

    def refresh(self, refresh_token):
        self.refreshed += 1
        if isinstance(self.refresh_result, Exception):
            raise self.refresh_result
        return self.refresh_result


def test_expired_token_is_refreshed_and_stored_encrypted(db, encryption):
    owner = make_athlete(db)
    owner.access_token_encrypted, owner.refresh_token_encrypted = encryption.encrypt("old"), encryption.encrypt("refresh")
    owner.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    client = TokenClient({"access_token": "new", "refresh_token": "refresh2", "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp())})

    assert get_valid_access_token(db, owner, client) == "new"
    assert client.refreshed == 1
    assert encryption.decrypt(owner.refresh_token_encrypted) == "refresh2"
    assert "new" not in owner.access_token_encrypted


def test_valid_token_is_not_refreshed(db, encryption):
    owner = make_athlete(db)
    owner.access_token_encrypted = encryption.encrypt("still-good")
    db.commit()
    client = TokenClient(AssertionError("must not refresh"))

    assert get_valid_access_token(db, owner, client) == "still-good"


def test_401_triggers_one_forced_refresh_then_succeeds(db, fake_token):
    make_athlete(db)
    client = FakeClient(StravaAuthError("expired early"), summary())

    assert process_event(db, event(db), client) == "upserted"
    assert fake_token == [False, True]
    assert db.query(Athlete).one().auth_status == "connected"


def test_revoked_refresh_token_flags_athlete_and_stops_retries(db, encryption):
    owner = make_athlete(db)
    owner.refresh_token_encrypted = encryption.encrypt("revoked")
    owner.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    client = TokenClient(StravaAuthError("invalid refresh token"))

    event_id = event(db)
    assert process_event(db, event_id, client) == "failed"

    db.refresh(owner)
    assert (owner.auth_status, owner.is_active) == ("reauth_required", False)
    assert status(db, event_id) == ("failed", "athlete_auth_invalid")
    # Later events for this athlete are ignored without touching Strava again.
    assert process_event(db, event(db, object_id=999, event_time=5000), client) == "athlete_not_syncing"
    assert client.refreshed == 1
    assert process_due_events(db, client)["attempted"] == 0


def test_persistent_401_after_refresh_marks_athlete_for_reauthorization(db, fake_token):
    make_athlete(db)
    client = FakeClient(StravaAuthError("401"), StravaAuthError("401 again"))

    assert process_event(db, event(db), client) == "failed"
    assert db.query(Athlete).one().auth_status == "reauth_required"


# --- transient errors, retries and rate limits -----------------------------

def test_transient_error_is_retried_with_backoff_then_succeeds(db, fake_token):
    make_athlete(db)
    client = FakeClient(StravaTransientError("503"), summary())
    event_id = event(db)

    assert process_event(db, event_id, client) == "retry"
    item = db.get(StravaWebhookEvent, event_id)
    assert item.attempts == 1 and item.last_error == "strava_unavailable"
    assert process_due_events(db, client)["attempted"] == 0  # backoff not elapsed: no call

    item.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert process_due_events(db, client)["processed"] == 1
    assert status(db, event_id) == ("processed", "upserted")
    assert len(client.calls) == 2


def test_retries_are_bounded(db, fake_token):
    make_athlete(db)
    client = FakeClient(*[StravaTransientError("503")] * strava_events.MAX_ATTEMPTS)
    event_id = event(db)
    for _ in range(strava_events.MAX_ATTEMPTS):
        item = db.get(StravaWebhookEvent, event_id)
        item.next_attempt_at = None
        db.commit()
        process_event(db, event_id, client)

    assert status(db, event_id) == ("failed", "retries_exhausted")
    assert process_event(db, event_id, client) is None


def test_rate_limit_defers_the_event_until_the_window_resets(db, fake_token):
    make_athlete(db)
    event_id = event(db)

    assert process_event(db, event_id, FakeClient(StravaRateLimitError("429", retry_after=600))) == "retry"
    item = db.get(StravaWebhookEvent, event_id)
    assert item.last_error == "rate_limited"
    assert item.next_attempt_at.replace(tzinfo=UTC) >= datetime.now(UTC) + timedelta(seconds=590)


def test_unexpected_processing_error_is_retried_not_lost(db, fake_token):
    make_athlete(db)
    event_id = event(db)

    assert process_event(db, event_id, FakeClient(summary(start_date=None))) == "retry"
    assert db.get(StravaWebhookEvent, event_id).last_error == "internal_error"


def test_crashed_processing_lease_is_released_for_retry(db, fake_token):
    make_athlete(db)
    event_id = event(db)
    item = db.get(StravaWebhookEvent, event_id)
    item.status, item.next_attempt_at = "processing", datetime.now(UTC) - timedelta(minutes=1)
    db.commit()

    result = process_due_events(db, FakeClient(summary()))
    assert result["released"] == 1 and result["processed"] == 1


def test_429_blocks_further_requests_without_hitting_strava():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"X-RateLimit-Limit": "200,2000", "X-RateLimit-Usage": "201,500"}, json={"message": "Rate Limit Exceeded"})

    client = StravaClient(httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(StravaRateLimitError) as first:
        client.activity("token", 1)
    with pytest.raises(StravaRateLimitError):
        client.activity("token", 2)

    assert len(requests) == 1
    assert 0 < first.value.retry_after <= 15 * 60 + 1
    snapshot = api_metrics.snapshot()
    assert snapshot["calls_by_endpoint"] == {"/activities/:id": 1}
    assert snapshot["last_rate_limit_headers"]["X-RateLimit-Usage"] == "201,500"


def test_rate_limit_reset_uses_15_minute_and_daily_windows():
    now = datetime(2026, 11, 10, 10, 7, 30, tzinfo=UTC)
    short = httpx.Headers({"X-RateLimit-Limit": "200,2000", "X-RateLimit-Usage": "200,900"})
    daily = httpx.Headers({"X-RateLimit-Limit": "200,2000", "X-RateLimit-Usage": "50,2000"})

    assert seconds_until_rate_limit_reset(short, now) == 7 * 60 + 30 + 1
    assert seconds_until_rate_limit_reset(daily, now) == int((datetime(2026, 11, 11, tzinfo=UTC) - now).total_seconds()) + 1


@pytest.mark.parametrize("code,error", [(401, StravaAuthError), (404, StravaNotFoundError), (503, StravaTransientError)])
def test_http_errors_are_classified(code, error):
    client = StravaClient(httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(code, json={"message": "x"}))))
    with pytest.raises(error):
        client.activity("token", 1)


def test_timeouts_are_transient():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(StravaTransientError):
        StravaClient(httpx.Client(transport=httpx.MockTransport(handler))).activity("token", 1)


def test_refresh_rejection_is_an_auth_error_but_5xx_is_transient():
    reject = StravaClient(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "Bad Request"}))))
    down = StravaClient(httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(502))))
    with pytest.raises(StravaAuthError):
        reject.refresh("refresh")
    with pytest.raises(StravaTransientError):
        down.refresh("refresh")


def test_deauthorize_uses_the_oauth_endpoint():
    urls = []

    def handler(request):
        urls.append(str(request.url))
        return httpx.Response(200, json={"access_token": "x"})

    StravaClient(httpx.Client(transport=httpx.MockTransport(handler))).deauthorize("token")
    assert urls == ["https://www.strava.com/oauth/deauthorize"]
