from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, Athlete
from app.services import StravaClient, StravaError, get_valid_access_token, is_club_member, normalize_sport

logger = logging.getLogger(__name__)


def upsert_activity(db: Session, athlete: Athlete, item: dict) -> Activity:
    activity = db.scalar(select(Activity).where(Activity.strava_activity_id == item["id"]))
    if not activity:
        activity = Activity(athlete=athlete, strava_activity_id=item["id"])
        db.add(activity)
    activity.name = item.get("name", "Actividad")
    activity.sport_type = item.get("sport_type", item.get("type", ""))
    activity.normalized_sport = normalize_sport(activity.sport_type, item.get("workout_type"))
    activity.start_date = datetime.fromisoformat(item["start_date"].replace("Z", "+00:00"))
    activity.start_date_local = datetime.fromisoformat(item["start_date_local"].replace("Z", "+00:00")) if item.get("start_date_local") else None
    activity.timezone = item.get("timezone")
    activity.distance_m = item.get("distance", 0)
    activity.moving_time_s = item.get("moving_time", 0)
    activity.elapsed_time_s = item.get("elapsed_time", 0)
    activity.total_elevation_gain_m = item.get("total_elevation_gain", 0)
    activity.average_speed_mps = item.get("average_speed")
    activity.max_speed_mps = item.get("max_speed")
    activity.calories = item.get("calories")
    activity.suffer_score = item.get("suffer_score")
    activity.workout_type = item.get("workout_type")
    activity.manual = item.get("manual", False)
    activity.trainer = item.get("trainer", False)
    activity.commute = item.get("commute", False)
    activity.visibility = item.get("visibility") or ("Only You" if item.get("private") else None)
    return activity


def sync_activities(db: Session, athlete: Athlete, client: StravaClient, *, lookback_days: int | None = None, reconcile: bool = False) -> int:
    """Backfill a bounded history once, then only refresh recent summaries."""
    token = get_valid_access_token(db, athlete, client)
    settings = get_settings()
    initial_history = athlete.history_synced_at is None
    days = lookback_days or (settings.strava_initial_history_days if initial_history else settings.strava_rolling_sync_days)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    activities = client.activities(token, cutoff)
    for item in activities:
        upsert_activity(db, athlete, item)
    if reconcile:
        visible_ids = {item["id"] for item in activities}
        for stored in db.scalars(select(Activity).where(Activity.athlete_id == athlete.id, Activity.start_date >= cutoff)):
            if stored.strava_activity_id not in visible_ids:
                db.delete(stored)
    athlete.last_sync_at = datetime.now(UTC)
    if initial_history:
        athlete.history_synced_at = athlete.last_sync_at
    db.commit()
    return len(activities)


def sync_all_active_athletes(db: Session) -> dict[str, int]:
    client = StravaClient()
    result = {"athletes": 0, "activities": 0, "failed": 0}
    for athlete in db.scalars(select(Athlete).where(Athlete.is_active.is_(True), Athlete.is_club_member.is_(True))):
        try:
            token = get_valid_access_token(db, athlete, client)
            if not is_club_member(client.clubs(token)):
                athlete.is_club_member = False
                athlete.is_active = False
                athlete.membership_check_status = "not_member"
                athlete.membership_checked_at = datetime.now(UTC)
                athlete.membership_check_error = None
                db.commit()
                logger.info("athlete_id=%s is no longer a RUD@S member", athlete.id)
                continue
            result["activities"] += sync_activities(db, athlete, client)
            result["athletes"] += 1
        except StravaError:
            db.rollback()
            result["failed"] += 1
            logger.exception("sync failed for internal athlete_id=%s", athlete.id)
    return result
