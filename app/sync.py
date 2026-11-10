from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, Athlete
from app.services import StravaClient, StravaError, StravaRateLimitError, StravaTransientError, call_with_token, normalize_sport

logger = logging.getLogger(__name__)
MAX_RECOVERY_DAYS = 30


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
    """Download summary activities once for a bounded window and upsert them.

    This is the one-time historical import (first connection, or a change in
    the privacy scopes the athlete granted). It is never scheduled: webhooks
    keep the data current afterwards. Activities are upserted by their Strava
    id, so running it twice never creates duplicates.
    """
    settings = get_settings()
    initial_history = athlete.history_synced_at is None
    days = lookback_days or (settings.strava_initial_history_days if initial_history else settings.strava_rolling_sync_days)
    cutoff = datetime.now(UTC) - timedelta(days=days)
    activities = call_with_token(db, athlete, client, lambda token: client.activities(token, cutoff))
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


def import_history(db: Session, athlete: Athlete, client: StravaClient, *, lookback_days: int, reconcile: bool = False) -> int:
    """Run ``sync_activities`` and record its status and result on the athlete."""
    athlete.initial_import_status = "running"
    athlete.initial_import_error = None
    db.commit()
    try:
        count = sync_activities(db, athlete, client, lookback_days=lookback_days, reconcile=reconcile)
    except StravaError as e:
        db.rollback()
        athlete.initial_import_status = "failed"
        athlete.initial_import_error = "rate_limited" if isinstance(e, StravaRateLimitError) else "strava_unavailable" if isinstance(e, StravaTransientError) else type(e).__name__
        db.commit()
        logger.warning("Activity import failed athlete_id=%s error=%s", athlete.id, athlete.initial_import_error)
        raise
    athlete.initial_import_status = "completed"
    athlete.initial_import_count = count
    db.commit()
    logger.info("Activity import completed athlete_id=%s days=%s activities=%s reconcile=%s", athlete.id, lookback_days, count, reconcile)
    return count


def recover_activities(db: Session, athlete: Athlete, client: StravaClient, *, days: int) -> int:
    """Manual, bounded catch-up for one athlete (e.g. after a webhook outage).

    Capped at MAX_RECOVERY_DAYS so it can never become a disguised full poll.
    """
    if athlete.auth_status != "connected" or not athlete.is_active or not athlete.is_club_member:
        raise ValueError("athlete is not connected")
    days = max(1, min(days, MAX_RECOVERY_DAYS))
    count = sync_activities(db, athlete, client, lookback_days=days)
    logger.warning("Manual activity recovery athlete_id=%s days=%s activities=%s", athlete.id, days, count)
    return count
