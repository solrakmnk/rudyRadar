from datetime import UTC, datetime
from types import SimpleNamespace
from sqlalchemy import select
from app.models import Activity, Athlete
from app.sync import sync_activities, upsert_activity


def test_upsert_activity_updates_an_existing_strava_activity(db):
    athlete = Athlete(strava_athlete_id=99, firstname="Carlos", lastname="A")
    db.add(athlete)
    db.commit()
    assert athlete.membership_check_status == "pending"
    initial = {
        "id": 12345678901,
        "name": "Primera salida",
        "sport_type": "Run",
        "start_date": "2026-09-29T15:00:00Z",
        "distance": 5000,
        "moving_time": 1500,
        "elapsed_time": 1600,
        "total_elevation_gain": 25,
        "visibility": "Only You",
    }
    changed = {**initial, "name": "Salida corregida", "distance": 5100}

    first = upsert_activity(db, athlete, initial)
    db.commit()
    second = upsert_activity(db, athlete, changed)
    db.commit()

    assert first.id == second.id
    assert second.name == "Salida corregida"
    assert second.distance_m == 5100
    assert second.normalized_sport == "run"
    assert second.visibility == "Only You"


def test_reconcile_removes_activities_no_longer_visible(db, monkeypatch):
    athlete = Athlete(strava_athlete_id=100, firstname="Rudo", lastname="Privado")
    db.add(athlete)
    db.flush()
    hidden = Activity(
        athlete=athlete, strava_activity_id=1, name="Privada", sport_type="Run",
        normalized_sport="run", start_date=datetime.now(UTC), visibility="Only You",
    )
    db.add(hidden)
    db.commit()

    monkeypatch.setattr("app.sync.get_valid_access_token", lambda *_: "token")
    monkeypatch.setattr("app.sync.get_settings", lambda: SimpleNamespace(strava_initial_history_days=365, strava_rolling_sync_days=21))

    class VisibleOnlyClient:
        def activities(self, token, after):
            return []

    sync_activities(db, athlete, VisibleOnlyClient(), lookback_days=365, reconcile=True)
    assert db.scalar(select(Activity).where(Activity.strava_activity_id == 1)) is None
