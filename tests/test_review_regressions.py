"""Regression tests for the PR #1 code-review findings."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main, webhooks
from app.database import get_db
from app.models import Activity, Athlete, StravaWebhookEvent
from app.services import StravaAuthError, StravaClient, StravaForbiddenError, StravaRateLimitError, StravaTransientError
from app.strava_events import process_due_events, process_event, record_event
from tests.test_initial_import import app_client  # noqa: F401  (fixture)
from tests.test_strava_events import FakeClient, make_athlete, summary


def deliver(db, aspect="update", object_id=123, owner=9001, event_time=1000, object_type="activity", updates=None, subscription_id=7):
    stored, is_new = record_event(db, {"object_type": object_type, "aspect_type": aspect, "object_id": object_id, "owner_id": owner,
                                       "event_time": event_time, "subscription_id": subscription_id, "updates": updates or {}})
    return stored, is_new


def deauth(db, **kwargs):
    stored, _ = deliver(db, "update", object_type="athlete", object_id=9001, updates={"authorized": "false"}, **kwargs)
    return stored.id


# --- Finding 1: untrusted events must not delete athletes ---------------------

def test_event_received_before_subscription_is_known_is_stored_but_not_acted_on(db, fake_token, monkeypatch):
    make_athlete(db)
    monkeypatch.setattr(webhooks, "active_subscription_id", None)
    monkeypatch.setattr(webhooks, "resolve_subscription_id", lambda client=None: None)
    monkeypatch.setattr("app.strava_events.resolve_subscription_id", lambda client=None: None)
    event_id = deauth(db)
    client = FakeClient()

    assert process_event(db, event_id, client) == "retry"

    item = db.get(StravaWebhookEvent, event_id)
    assert (item.status, item.last_error, item.attempts) == ("retry", "subscription_unverified", 0)
    assert db.query(Athlete).count() == 1 and client.calls == []


def test_unknown_subscription_is_resolved_from_strava_before_processing(db, fake_token, monkeypatch):
    make_athlete(db)
    monkeypatch.setattr(webhooks, "active_subscription_id", None)
    settings = webhooks.get_settings()
    monkeypatch.setattr(settings, "strava_client_id", "25116")
    monkeypatch.setattr(settings, "strava_client_secret", "secret")
    monkeypatch.setattr(settings, "app_base_url", "https://rudo-radar.up.railway.app")
    lookups = []

    def handler(request):
        lookups.append(request)
        return httpx.Response(200, json=[{"id": 7, "callback_url": "https://rudo-radar.up.railway.app/webhooks/strava"}])

    assert webhooks.resolve_subscription_id(httpx.Client(transport=httpx.MockTransport(handler))) == 7
    assert webhooks.resolve_subscription_id() == 7  # cached: no second lookup
    assert len(lookups) == 1

    good, _ = deliver(db, "create")
    forged, _ = deliver(db, "create", object_id=999, subscription_id=8)
    assert process_event(db, good.id, FakeClient(summary())) == "upserted"
    assert process_event(db, forged.id, FakeClient()) == "untrusted_subscription"


def test_subscription_lookups_are_throttled(monkeypatch):
    monkeypatch.setattr(webhooks, "active_subscription_id", None)
    settings = webhooks.get_settings()
    monkeypatch.setattr(settings, "strava_client_id", "25116")
    monkeypatch.setattr(settings, "strava_client_secret", "secret")
    lookups = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: lookups.append(r) or httpx.Response(503)))

    assert webhooks.resolve_subscription_id(client) is None
    assert webhooks.resolve_subscription_id(client) is None
    assert len(lookups) == 1


def test_forged_deauthorization_with_working_credentials_keeps_the_athlete(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=1, name="Kept", sport_type="Run", start_date=datetime.now(UTC)))
    db.commit()
    client = FakeClient(athlete={"id": 9001})  # token still accepted by Strava

    assert process_event(db, deauth(db), client) == "deauthorization_not_confirmed"
    assert db.query(Athlete).count() == 1 and db.query(Activity).count() == 1
    assert client.calls == [("athlete", "access")]


def test_confirmed_deauthorization_deletes_the_athlete(db, fake_token):
    make_athlete(db)
    client = FakeClient(athlete=StravaAuthError("revoked"))

    assert process_event(db, deauth(db), client) == "athlete_deleted"
    assert db.query(Athlete).count() == 0


def test_deauthorization_check_retries_on_transient_errors(db, fake_token):
    make_athlete(db)
    event_id = deauth(db)

    assert process_event(db, event_id, FakeClient(athlete=StravaTransientError("503"))) == "retry"
    assert db.query(Athlete).count() == 1


def test_deauthorization_from_another_subscription_is_ignored(db, fake_token):
    make_athlete(db)
    client = FakeClient()

    assert process_event(db, deauth(db, subscription_id=8), client) == "untrusted_subscription"
    assert db.query(Athlete).count() == 1 and client.calls == []


def test_endpoint_stores_events_while_subscription_is_unknown_and_rejects_missing_ids(db, monkeypatch):
    monkeypatch.setattr(webhooks, "active_subscription_id", None)
    monkeypatch.setattr(main, "get_db", lambda: iter([db]))
    monkeypatch.setattr(main, "process_event_in_new_session", lambda event_id: None)
    client = TestClient(main.app)
    base = {"object_type": "activity", "aspect_type": "create", "object_id": 5, "owner_id": 1, "event_time": 1}

    assert client.post("/webhooks/strava", json={**base, "subscription_id": 7}).json() == {"status": "accepted"}
    assert client.post("/webhooks/strava", json={**base, "event_time": 2}).json() == {"status": "ignored"}
    assert db.query(StravaWebhookEvent).count() == 1


# --- Finding 2: athletes with zero activities are not re-imported -------------

def test_athlete_with_empty_history_is_not_reimported_on_login(db, app_client):  # noqa: F811
    connect, calls, state = app_client
    state["activities"] = []

    connect()
    connect()

    athlete = db.query(Athlete).one()
    assert (athlete.initial_import_status, athlete.initial_import_count) == ("completed", 0)
    assert db.query(Activity).count() == 0
    assert len(calls["activities"]) == 1


# --- Finding 3: distinct updates sharing an event_time are kept ---------------

def test_different_updates_in_the_same_second_are_both_recorded(db):
    first, new_first = deliver(db, updates={"title": "A"})
    second, new_second = deliver(db, updates={"type": "Ride"})
    again, new_again = deliver(db, updates={"title": "A"})

    assert new_first and new_second and not new_again
    assert first.id != second.id and again.id == first.id
    assert db.query(StravaWebhookEvent).count() == 2


def test_same_second_title_and_type_changes_both_reach_the_activity(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Old", sport_type="Run", normalized_sport="run", start_date=datetime.now(UTC)))
    db.commit()
    title, _ = deliver(db, updates={"title": "Renamed"})
    kind, _ = deliver(db, updates={"type": "Ride"})
    client = FakeClient(summary(name="Renamed", sport_type="Run"))

    result = process_due_events(db, client)

    activity = db.query(Activity).one()
    assert result["processed"] == 2
    assert (activity.name, activity.sport_type, activity.normalized_sport) == ("Renamed", "Ride", "bike")


def test_title_only_update_never_supersedes_an_event_that_needs_a_fetch(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Old", sport_type="Run", start_date=datetime.now(UTC), distance_m=1))
    db.commit()
    needs_fetch, _ = deliver(db, updates={"private": "false"}, event_time=1000)
    deliver(db, updates={"title": "New"}, event_time=1000)
    client = FakeClient(summary(name="New", distance=4200))

    assert process_event(db, needs_fetch.id, client) == "upserted"
    assert db.query(Activity).one().distance_m == 4200


def test_older_event_after_a_title_only_update_is_fetched_not_dropped(db, fake_token):
    owner = make_athlete(db)
    db.add(Activity(athlete=owner, strava_activity_id=123, name="Old", sport_type="Run", start_date=datetime.now(UTC), distance_m=1))
    db.commit()
    newer, _ = deliver(db, updates={"title": "New"}, event_time=2000)
    assert process_event(db, newer.id, FakeClient()) == "updated_from_event"

    older, _ = deliver(db, updates={"private": "false"}, event_time=1000)
    client = FakeClient(summary(name="New", distance=4200))
    assert process_event(db, older.id, client) == "upserted"
    assert len(client.calls) == 1 and db.query(Activity).one().distance_m == 4200


# --- Finding 4: clubs() fallback only for restricted access (403) -------------

def club_client(status, requests):
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/athlete/clubs"):
            return httpx.Response(status, headers={"X-RateLimit-Limit": "200,2000", "X-RateLimit-Usage": "200,300"}, json={"message": "x"})
        return httpx.Response(200, json={"id": 1, "clubs": [{"id": 1187973}]})
    return StravaClient(httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status,error", [(429, StravaRateLimitError), (503, StravaTransientError), (401, StravaAuthError)])
def test_clubs_does_not_fall_back_on_rate_limits_transient_or_auth_errors(status, error):
    requests = []
    with pytest.raises(error):
        club_client(status, requests).clubs("token")
    assert requests == ["/api/v3/athlete/clubs"]


def test_clubs_falls_back_to_the_athlete_profile_when_access_is_restricted():
    requests = []
    assert club_client(403, requests).clubs("token") == [{"id": 1187973}]
    assert requests == ["/api/v3/athlete/clubs", "/api/v3/athlete"]


def test_rate_limited_membership_check_keeps_a_verified_member_active(db, app_client, monkeypatch):  # noqa: F811
    connect, _, _ = app_client
    connect()

    def limited(self, token):
        raise StravaRateLimitError("429", retry_after=60)

    monkeypatch.setattr(StravaClient, "clubs", limited)
    response = connect()

    athlete = db.query(Athlete).one()
    assert response.status_code == 503
    assert (athlete.is_active, athlete.is_club_member, athlete.membership_check_status) == (True, True, "verified")


def test_rate_limited_membership_check_does_not_activate_a_new_athlete(db, app_client, monkeypatch):  # noqa: F811
    connect, _, _ = app_client
    monkeypatch.setattr(StravaClient, "clubs", lambda self, token: (_ for _ in ()).throw(StravaRateLimitError("429", retry_after=60)))

    assert connect().status_code == 503
    athlete = db.query(Athlete).one()
    assert (athlete.is_active, athlete.membership_check_status) == (False, "unavailable")
