"""HTTP layer of POST/GET /webhooks/strava."""
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import main, webhooks
from app.database import get_db
from app.models import Athlete, StravaWebhookEvent


def athlete(db, strava_id=9001):
    item = Athlete(strava_athlete_id=strava_id, firstname="Webhook", lastname="Tester", access_token_encrypted="token",
                   refresh_token_encrypted="refresh", token_expires_at=datetime.now(UTC), is_active=True, is_club_member=True)
    db.add(item)
    db.commit()
    return item


def client_for(db, monkeypatch, processed):
    monkeypatch.setattr(main, "get_db", lambda: iter([db]))
    monkeypatch.setattr(main, "process_event_in_new_session", lambda event_id: processed.append(event_id))
    monkeypatch.setattr(main.settings, "webhook_retry_interval_seconds", 0)
    main.app.dependency_overrides[get_db] = lambda: db
    return TestClient(main.app)


def test_webhook_verification_uses_strava_dotted_query_names(monkeypatch):
    monkeypatch.setattr(main.settings, "webhook_verify_token", "expected-token")
    with TestClient(main.app) as client:
        response = client.get("/webhooks/strava", params={"hub.mode": "subscribe", "hub.verify_token": "expected-token", "hub.challenge": "challenge-123"})
    assert response.status_code == 200
    assert response.json() == {"hub.challenge": "challenge-123"}


def test_webhook_verification_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(main.settings, "webhook_verify_token", "expected-token")
    with TestClient(main.app) as client:
        response = client.get("/webhooks/strava", params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "x"})
    assert response.status_code == 403


def test_event_is_persisted_before_ack_and_duplicates_are_not_reprocessed(db, monkeypatch):
    athlete(db)
    processed = []
    event = {"object_type": "activity", "aspect_type": "create", "object_id": 123, "owner_id": 9001, "event_time": 1760000000, "subscription_id": 7, "updates": {}}
    client = client_for(db, monkeypatch, processed)

    first = client.post("/webhooks/strava", json=event)
    second = client.post("/webhooks/strava", json=event)

    assert first.status_code == 200 and first.json() == {"status": "accepted"}
    assert second.status_code == 200 and second.json() == {"status": "duplicate"}
    assert db.query(StravaWebhookEvent).count() == 1
    assert len(processed) == 1
    main.app.dependency_overrides.clear()


def test_events_for_another_subscription_are_ignored(db, monkeypatch):
    processed = []
    client = client_for(db, monkeypatch, processed)
    monkeypatch.setattr(webhooks, "active_subscription_id", 7)

    response = client.post("/webhooks/strava", json={"object_type": "activity", "aspect_type": "create", "object_id": 1, "owner_id": 1, "event_time": 1, "subscription_id": 99})

    assert response.json() == {"status": "ignored"}
    assert db.query(StravaWebhookEvent).count() == 0 and processed == []
    main.app.dependency_overrides.clear()


def test_malformed_payloads_are_acknowledged_but_not_stored(db, monkeypatch):
    processed = []
    client = client_for(db, monkeypatch, processed)

    assert client.post("/webhooks/strava", json={"object_type": "segment"}).json() == {"status": "ignored"}
    assert client.post("/webhooks/strava", content=b"not json", headers={"content-type": "application/json"}).status_code == 400
    assert db.query(StravaWebhookEvent).count() == 0
    main.app.dependency_overrides.clear()
