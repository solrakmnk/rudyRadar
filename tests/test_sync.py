from app.models import Athlete
from app.sync import upsert_activity


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
