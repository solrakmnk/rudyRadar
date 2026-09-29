from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, Athlete


def period_bounds(kind: str, now: datetime, timezone: str | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for the current local week or month."""
    local = now.astimezone(ZoneInfo(timezone or get_settings().app_timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "week":
        start -= timedelta(days=start.weekday())
        end = start + timedelta(days=7)
    elif kind == "month":
        start = start.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        raise ValueError("Unknown period")
    return start.astimezone(UTC), end.astimezone(UTC)


def athlete_period_stats(db: Session, athlete_id: int, kind: str, now: datetime | None = None) -> dict[str, float | int]:
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(
        select(Activity).where(
            Activity.athlete_id == athlete_id,
            Activity.start_date >= start,
            Activity.start_date < end,
        )
    ).all()
    zone = ZoneInfo(get_settings().app_timezone)
    return {
        "distance_m": sum(activity.distance_m for activity in activities),
        "moving_time_s": sum(activity.moving_time_s for activity in activities),
        "activity_count": len(activities),
        "active_days": len({activity.start_date.astimezone(zone).date() for activity in activities}),
        "elevation_m": sum(activity.total_elevation_gain_m for activity in activities),
    }


def rankings(db: Session, kind: str, now: datetime | None = None) -> dict[str, list[dict[str, str | float]]]:
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(
        select(Activity).where(
            Activity.start_date >= start,
            Activity.start_date < end,
            Activity.normalized_sport.is_not(None),
        )
    ).all()
    result: dict[str, list[dict[str, str | float]]] = {sport: [] for sport in ("swim", "bike", "run", "gym")}
    totals: dict[tuple[str, int], float] = {}
    for activity in activities:
        key = (activity.normalized_sport, activity.athlete_id)
        totals[key] = totals.get(key, 0) + activity.distance_m
    names = {athlete.id: f"{athlete.firstname} {athlete.lastname}".strip() for athlete in db.scalars(select(Athlete)).all()}
    for (sport, athlete_id), distance in totals.items():
        result[sport].append({"name": names[athlete_id], "distance_m": distance})
    for sport in result:
        result[sport].sort(key=lambda row: row["distance_m"], reverse=True)
        result[sport] = result[sport][:3]
    return result


def weekly_comparison(db: Session, athlete_id: int, now: datetime | None = None) -> dict[str, float | int]:
    current_start, current_end = period_bounds("week", now or datetime.now(UTC))
    previous_start = current_start - timedelta(days=7)
    activities = db.scalars(select(Activity).where(Activity.athlete_id == athlete_id)).all()
    def totals(start: datetime, end: datetime) -> tuple[float, int]:
        selected = [activity for activity in activities if start <= activity.start_date < end]
        return sum(activity.distance_m for activity in selected), len(selected)
    current_distance, current_count = totals(current_start, current_end)
    previous_distance, previous_count = totals(previous_start, current_start)
    return {"distance_m": current_distance, "distance_change_m": current_distance - previous_distance, "activity_count": current_count, "activity_change": current_count - previous_count}


def activity_highlights(db: Session, athlete_id: int, now: datetime | None = None) -> dict[str, str | float | int | None]:
    start, _ = period_bounds("week", now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.athlete_id == athlete_id, Activity.start_date >= start)).all()
    if not activities:
        return {"longest_day": None, "longest_distance_m": 0, "busiest_day": None, "busiest_count": 0}
    zone = ZoneInfo(get_settings().app_timezone)
    distance_by_day: dict[str, float] = {}
    count_by_day: dict[str, int] = {}
    for activity in activities:
        day = activity.start_date.astimezone(zone).strftime("%A")
        distance_by_day[day] = distance_by_day.get(day, 0) + activity.distance_m
        count_by_day[day] = count_by_day.get(day, 0) + 1
    longest_day, longest_distance = max(distance_by_day.items(), key=lambda row: row[1])
    busiest_day, busiest_count = max(count_by_day.items(), key=lambda row: row[1])
    return {"longest_day": longest_day, "longest_distance_m": longest_distance, "busiest_day": busiest_day, "busiest_count": busiest_count}


def monthly_comparison(db: Session, athlete_id: int, sport: str, now: datetime | None = None) -> dict[str, float | None]:
    current_start, current_end = period_bounds("month", now or datetime.now(UTC))
    previous_end = current_start
    previous_start = (current_start - timedelta(days=1)).replace(day=1)
    activities = db.scalars(
        select(Activity).where(Activity.athlete_id == athlete_id, Activity.normalized_sport == sport)
    ).all()
    total = lambda start, end: sum(activity.distance_m for activity in activities if start <= activity.start_date < end)
    previous, current = total(previous_start, previous_end), total(current_start, current_end)
    absolute = current - previous
    return {
        "previous_distance": previous,
        "current_distance": current,
        "absolute_change": absolute,
        "percentage_change": None if previous == 0 else absolute / previous * 100,
    }
