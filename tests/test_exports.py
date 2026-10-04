from datetime import UTC, datetime

from app.exports import athlete_data_export
from app.models import Activity, Athlete


def test_athlete_export_contains_owned_data_without_credentials():
    athlete = Athlete(
        strava_athlete_id=42,
        firstname="Carlos",
        lastname="Guevara",
        access_token_encrypted="secret-access",
        refresh_token_encrypted="secret-refresh",
        authorized_scopes="activity:read,read",
    )
    activity = Activity(
        strava_activity_id=99,
        name="Morning Run",
        sport_type="Run",
        normalized_sport="run",
        start_date=datetime(2026, 10, 4, tzinfo=UTC),
        distance_m=5000,
        moving_time_s=1500,
        elapsed_time_s=1600,
        total_elevation_gain_m=20,
    )

    exported = athlete_data_export(athlete, [activity])

    assert exported["athlete"]["strava_athlete_id"] == 42
    assert exported["activities"][0]["strava_activity_id"] == 99
    assert "access_token_encrypted" not in exported["athlete"]
    assert "refresh_token_encrypted" not in exported["athlete"]
