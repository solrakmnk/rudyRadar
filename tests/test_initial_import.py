"""OAuth callback, one-time history import and the maintenance command."""
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app import cli, main
from app.config import get_settings
from app.database import get_db
from app.models import Activity, Athlete
from app.services import StravaClient, StravaRateLimitError

CLUB = {"id": 1187973}
VISIBLE = "read,activity:read,profile:read_all"
PRIVATE = "read,activity:read_all,profile:read_all"


def summary(activity_id, days_ago=1):
    start = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": activity_id, "name": f"Run {activity_id}", "sport_type": "Run", "start_date": start, "distance": 5000, "moving_time": 1500}


@pytest.fixture()
def app_client(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "token_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "strava_sync_enabled", True)
    monkeypatch.setattr(settings, "strava_initial_history_days", 365)
    calls = {"activities": [], "clubs": 0}
    state = {"activities": [summary(1), summary(2)], "error": None}

    def activities(self, token, after, **_):
        calls["activities"].append(after)
        if state["error"]:
            raise state["error"]
        return state["activities"]

    def clubs(self, token):
        calls["clubs"] += 1
        return [CLUB]

    exchange = {"access_token": "access", "refresh_token": "refresh", "expires_at": int((datetime.now(UTC) + timedelta(hours=6)).timestamp()),
                "athlete": {"id": 4242, "firstname": "Rudo", "lastname": "Nuevo"}}
    monkeypatch.setattr(StravaClient, "exchange_code", lambda self, code: exchange)
    monkeypatch.setattr(StravaClient, "clubs", clubs)
    monkeypatch.setattr(StravaClient, "activities", activities)
    monkeypatch.setattr(settings, "webhook_retry_interval_seconds", 0)
    main.app.dependency_overrides[get_db] = lambda: db
    client = TestClient(main.app)

    def connect(scope=VISIBLE, mode="register", **params):
        start = client.get("/auth/strava", params={"mode": mode, **params}, follow_redirects=False)
        token = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        response = client.get("/auth/strava/callback", params={"code": "c", "state": token, "scope": scope}, follow_redirects=False)
        client.get("/logout")
        return response

    yield connect, calls, state
    main.app.dependency_overrides.clear()


def test_first_connection_imports_history_once_and_records_the_result(db, app_client):
    connect, calls, _ = app_client

    response = connect()

    athlete = db.query(Athlete).one()
    assert response.status_code == 303 and response.headers["location"] == "/radar"
    assert len(calls["activities"]) == 1
    assert (datetime.now(UTC) - calls["activities"][0]).days == 365
    assert (athlete.initial_import_status, athlete.initial_import_count) == ("completed", 2)
    assert athlete.history_synced_at is not None and athlete.auth_status == "connected"
    assert athlete.access_token_encrypted != "access"  # stored encrypted
    assert db.query(Activity).count() == 2


def test_regular_login_does_not_download_activities_again(db, app_client):
    connect, calls, _ = app_client
    connect()
    connect(scope=VISIBLE, mode="register")

    assert len(calls["activities"]) == 1
    assert db.query(Activity).count() == 2


def test_granting_private_scope_reimports_and_revoking_it_reconciles(db, app_client):
    connect, calls, state = app_client
    connect()
    state["activities"] = [summary(1), summary(2), summary(3)]
    connect(scope=PRIVATE, include_private="true")
    assert len(calls["activities"]) == 2 and db.query(Activity).count() == 3

    state["activities"] = [summary(1)]
    connect(scope=VISIBLE, remove_private="true")
    assert len(calls["activities"]) == 3
    assert [a.strava_activity_id for a in db.query(Activity).all()] == [1]


def test_reconnecting_after_invalid_credentials_catches_up_only_the_gap(db, app_client):
    connect, calls, _ = app_client
    connect()
    athlete = db.query(Athlete).one()
    athlete.auth_status, athlete.is_active = "reauth_required", False
    athlete.last_sync_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()

    connect()

    assert len(calls["activities"]) == 2
    assert (datetime.now(UTC) - calls["activities"][1]).days == 4
    db.refresh(athlete)
    assert (athlete.auth_status, athlete.is_active) == ("connected", True)


def test_rate_limited_import_is_recorded_and_retried_on_next_login(db, app_client):
    connect, calls, state = app_client
    state["error"] = StravaRateLimitError("429", retry_after=60)

    response = connect()
    athlete = db.query(Athlete).one()
    assert response.status_code == 503
    assert (athlete.initial_import_status, athlete.initial_import_error) == ("failed", "rate_limited")

    state["error"] = None
    connect()
    db.refresh(athlete)
    assert athlete.initial_import_status == "completed"
    assert len(calls["activities"]) == 2


def test_history_import_is_paginated_and_bounded():
    pages = []

    def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        assert request.url.params["per_page"] == "200"
        return httpx.Response(200, json=[{"id": page * 1000 + i} for i in range(200 if page < 3 else 7)])

    client = StravaClient(httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(client.activities("token", datetime.now(UTC) - timedelta(days=365))) == 407
    assert pages == [1, 2, 3]

    pages.clear()
    assert len(client.activities("token", datetime.now(UTC), max_pages=2)) == 400
    assert pages == [1, 2]


def test_maintenance_command_never_lists_activities(db, monkeypatch, fake_token):
    fresh = Athlete(strava_athlete_id=1, firstname="A", is_active=True, is_club_member=True, membership_checked_at=datetime.now(UTC))
    stale = Athlete(strava_athlete_id=2, firstname="B", is_active=True, is_club_member=True, membership_checked_at=datetime.now(UTC) - timedelta(days=8))
    gone = Athlete(strava_athlete_id=3, firstname="C", is_active=True, is_club_member=True, membership_checked_at=None)
    db.add_all([fresh, stale, gone])
    db.commit()
    clubs_calls = []

    def clubs(self, token):
        clubs_calls.append(token)
        return [CLUB] if len(clubs_calls) == 1 else [{"id": 1}]

    monkeypatch.setattr(StravaClient, "clubs", clubs)
    monkeypatch.setattr(StravaClient, "activities", lambda *a, **k: pytest.fail("maintenance must not poll activities"))

    result = cli.maintenance(db)

    assert result["activity_polling"] is False
    assert result["membership"] == {"checked": 2, "left_club": 1, "errors": 0}
    assert len(clubs_calls) == 2
    db.refresh(gone)
    assert (gone.is_active, gone.membership_check_status) == (False, "not_member")


def test_manual_recovery_is_capped(db, monkeypatch, fake_token):
    athlete = Athlete(strava_athlete_id=1, firstname="A", is_active=True, is_club_member=True, history_synced_at=datetime.now(UTC))
    db.add(athlete)
    db.commit()
    seen = []
    monkeypatch.setattr(StravaClient, "activities", lambda self, token, after, **_: seen.append(after) or [])

    from app.sync import recover_activities
    recover_activities(db, athlete, StravaClient(), days=400)

    assert (datetime.now(UTC) - seen[0]).days == 30
