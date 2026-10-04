from __future__ import annotations

from datetime import datetime

from app.models import Activity, Athlete


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def athlete_data_export(athlete: Athlete, activities: list[Activity]) -> dict[str, object]:
    """Return the Strava-derived data stored for one athlete, excluding credentials."""
    return {
        "exported_at": datetime.now().astimezone().isoformat(),
        "athlete": {
            "strava_athlete_id": athlete.strava_athlete_id,
            "firstname": athlete.firstname,
            "lastname": athlete.lastname,
            "profile_url": athlete.profile_url,
            "authorized_scopes": athlete.authorized_scopes,
            "membership_check_status": athlete.membership_check_status,
            "membership_checked_at": _iso(athlete.membership_checked_at),
            "connected_at": _iso(athlete.connected_at),
            "last_sync_at": _iso(athlete.last_sync_at),
        },
        "activities": [
            {
                "strava_activity_id": item.strava_activity_id,
                "name": item.name,
                "sport_type": item.sport_type,
                "normalized_sport": item.normalized_sport,
                "start_date": _iso(item.start_date),
                "start_date_local": _iso(item.start_date_local),
                "timezone": item.timezone,
                "visibility": item.visibility,
                "distance_m": item.distance_m,
                "moving_time_s": item.moving_time_s,
                "elapsed_time_s": item.elapsed_time_s,
                "total_elevation_gain_m": item.total_elevation_gain_m,
                "average_speed_mps": item.average_speed_mps,
                "max_speed_mps": item.max_speed_mps,
                "calories": item.calories,
                "suffer_score": item.suffer_score,
                "workout_type": item.workout_type,
                "manual": item.manual,
                "trainer": item.trainer,
                "commute": item.commute,
            }
            for item in activities
        ],
    }
