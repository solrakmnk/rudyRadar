from datetime import UTC, datetime

from app import main
from app.models import Activity, Athlete


def athlete(db, strava_id=9001):
    item = Athlete(
        strava_athlete_id=strava_id,
        firstname="Webhook",
        lastname="Tester",
        access_token_encrypted="token",
        refresh_token_encrypted="refresh",
        token_expires_at=datetime.now(UTC),
        is_active=True,
        is_club_member=True,
    )
    db.add(item)
    db.commit()
    return item


def use_test_db(monkeypatch, db):
    monkeypatch.setattr(main, "get_db", lambda: iter([db]))


def test_webhook_create_is_idempotent_and_updates_sync_time(db, monkeypatch):
    owner = athlete(db)
    use_test_db(monkeypatch, db)
    monkeypatch.setattr(main, "get_valid_access_token", lambda *_: "access")
    payload = {
        "id": 123,
        "name": "Morning swim",
        "sport_type": "Swim",
        "start_date": "2026-10-02T12:00:00Z",
        "distance": 1500,
        "moving_time": 1800,
    }
    monkeypatch.setattr(main.StravaClient, "activity", lambda *_: payload)

    event = {"object_type": "activity", "aspect_type": "create", "object_id": 123, "owner_id": 9001}
    main.process_webhook(event)
    main.process_webhook(event)

    assert db.query(Activity).count() == 1
    assert db.get(Athlete, owner.id).last_sync_at is not None


def test_webhook_delete_removes_activity(db, monkeypatch):
    owner = athlete(db)
    activity = Activity(
        athlete=owner,
        strava_activity_id=321,
        name="Private now",
        sport_type="Run",
        normalized_sport="run",
        start_date=datetime.now(UTC),
    )
    db.add(activity)
    db.commit()
    use_test_db(monkeypatch, db)

    main.process_webhook({"object_type": "activity", "aspect_type": "delete", "object_id": 321, "owner_id": 9001})

    assert db.query(Activity).count() == 0
    assert db.get(Athlete, owner.id).last_sync_at is not None


def test_webhook_deauthorization_accepts_boolean_false(db, monkeypatch):
    owner = athlete(db)
    use_test_db(monkeypatch, db)

    main.process_webhook({"object_type": "athlete", "aspect_type": "update", "owner_id": 9001, "updates": {"authorized": False}})

    assert db.get(Athlete, owner.id) is None
