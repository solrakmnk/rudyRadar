from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Activity, Athlete


def period_bounds(kind: str, now: datetime, timezone: str | None = None) -> tuple[datetime, datetime]:
    """Return UTC bounds for a current or completed local reporting period."""
    local = now.astimezone(ZoneInfo(timezone or get_settings().app_timezone))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "week":
        start -= timedelta(days=start.weekday())
        end = start + timedelta(days=7)
    elif kind == "last_week":
        end = start - timedelta(days=start.weekday())
        start = end - timedelta(days=7)
    elif kind == "month":
        start = start.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    elif kind == "last_month":
        end = start.replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
    elif kind == "two_months_ago":
        end = (start.replace(day=1) - timedelta(days=1)).replace(day=1)
        start = (end - timedelta(days=1)).replace(day=1)
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


def athlete_discipline_stats(db: Session, athlete_id: int, kind: str, now: datetime | None = None) -> dict[str, dict[str, float | int]]:
    """Summarize one athlete's activities by discipline for a selected period."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(
        select(Activity).where(
            Activity.athlete_id == athlete_id,
            Activity.start_date >= start,
            Activity.start_date < end,
            Activity.normalized_sport.is_not(None),
        )
    ).all()
    result: dict[str, dict[str, float | int]] = {
        sport: {"distance_m": 0.0, "moving_time_s": 0, "elevation_m": 0.0, "activity_count": 0} for sport in ("swim", "open_water", "bike", "run", "walk", "strength", "wellbeing")
    }
    for activity in activities:
        if activity.normalized_sport in result:
            result[activity.normalized_sport]["distance_m"] += activity.distance_m
            result[activity.normalized_sport]["moving_time_s"] += activity.moving_time_s
            result[activity.normalized_sport]["elevation_m"] += activity.total_elevation_gain_m
            result[activity.normalized_sport]["activity_count"] += 1
    return result


def team_leaderboard(db: Session, kind: str, now: datetime | None = None) -> list[dict[str, str | int | float]]:
    """Rank verified members by active time, with comparable sport contributions."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.start_date >= start, Activity.start_date < end)).all()
    athletes = {athlete.id: athlete for athlete in db.scalars(select(Athlete).where(Athlete.is_active.is_(True), Athlete.is_club_member.is_(True))).all()}
    rows: dict[int, dict[str, str | int | float]] = {}
    for activity in activities:
        if activity.athlete_id not in athletes:
            continue
        athlete = athletes[activity.athlete_id]
        row = rows.setdefault(activity.athlete_id, {"name": f"{athlete.firstname} {athlete.lastname}".strip(), "profile_url": athlete.profile_url or "", "moving_time_s": 0, "activity_count": 0, "swim_time_s": 0, "bike_distance_m": 0.0, "run_distance_m": 0.0, "strength_sessions": 0})
        row["moving_time_s"] += activity.moving_time_s
        row["activity_count"] += 1
        if activity.normalized_sport in {"swim", "open_water"}:
            row["swim_time_s"] += activity.moving_time_s
        elif activity.normalized_sport == "bike":
            row["bike_distance_m"] += activity.distance_m
        elif activity.normalized_sport == "run":
            row["run_distance_m"] += activity.distance_m
        elif activity.normalized_sport == "strength":
            row["strength_sessions"] += 1
    return sorted(rows.values(), key=lambda row: row["moving_time_s"], reverse=True)


def rankings(db: Session, kind: str, now: datetime | None = None) -> dict[str, list[dict[str, str | float | int]]]:
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(
        select(Activity).where(
            Activity.start_date >= start,
            Activity.start_date < end,
            Activity.normalized_sport.is_not(None),
        )
    ).all()
    result: dict[str, list[dict[str, str | float | int]]] = {sport: [] for sport in ("swim", "open_water", "bike", "run", "walk", "strength", "wellbeing")}
    totals: dict[tuple[str, int], float] = {}
    counts: dict[tuple[str, int], int] = {}
    for activity in activities:
        key = (activity.normalized_sport, activity.athlete_id)
        totals[key] = totals.get(key, 0) + activity.distance_m
        counts[key] = counts.get(key, 0) + 1
    names = {athlete.id: f"{athlete.firstname} {athlete.lastname}".strip() for athlete in db.scalars(select(Athlete)).all()}
    for (sport, athlete_id), distance in totals.items():
        result[sport].append({"name": names[athlete_id], "distance_m": distance, "activity_count": counts[(sport, athlete_id)]})
    for sport in result:
        metric = "activity_count" if sport in {"strength", "wellbeing"} else "distance_m"
        result[sport].sort(key=lambda row: row[metric], reverse=True)
        result[sport] = result[sport][:3]
    return result


def period_comparison(db: Session, athlete_id: int, kind: str, now: datetime | None = None) -> dict[str, float | int]:
    current_start, current_end = period_bounds(kind, now or datetime.now(UTC))
    if kind in {"week", "last_week"}:
        previous_start = current_start - timedelta(days=7)
    else:
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
    activities = db.scalars(select(Activity).where(Activity.athlete_id == athlete_id)).all()
    def totals(start: datetime, end: datetime) -> tuple[float, int]:
        selected = [activity for activity in activities if start <= activity.start_date < end]
        return sum(activity.distance_m for activity in selected), len(selected)
    current_distance, current_count = totals(current_start, current_end)
    previous_distance, previous_count = totals(previous_start, current_start)
    return {"distance_m": current_distance, "distance_change_m": current_distance - previous_distance, "activity_count": current_count, "activity_change": current_count - previous_count}


def weekly_comparison(db: Session, athlete_id: int, now: datetime | None = None) -> dict[str, float | int]:
    """Compatibility wrapper for the current-week pulse."""
    return period_comparison(db, athlete_id, "week", now)


def activity_highlights(db: Session, athlete_id: int, now: datetime | None = None, kind: str = "week") -> dict[str, str | float | int | None]:
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.athlete_id == athlete_id, Activity.start_date >= start, Activity.start_date < end)).all()
    if not activities:
        return {"longest_day": None, "longest_distance_m": 0, "busiest_day": None, "busiest_count": 0}
    zone = ZoneInfo(get_settings().app_timezone)
    distance_by_day: dict[str, float] = {}
    count_by_day: dict[str, int] = {}
    for activity in activities:
        day = f"weekday_{activity.start_date.astimezone(zone).weekday()}"
        distance_by_day[day] = distance_by_day.get(day, 0) + activity.distance_m
        count_by_day[day] = count_by_day.get(day, 0) + 1
    longest_day, longest_distance = max(distance_by_day.items(), key=lambda row: row[1])
    busiest_day, busiest_count = max(count_by_day.items(), key=lambda row: row[1])
    return {"longest_day": longest_day, "longest_distance_m": longest_distance, "busiest_day": busiest_day, "busiest_count": busiest_count}


def team_highlights(db: Session, now: datetime | None = None, kind: str = "week") -> dict[str, str | int | None]:
    """Find the weekday when the largest part of the club trained in a period."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.start_date >= start, Activity.start_date < end)).all()
    if not activities:
        return {"day": None, "participants": 0}
    zone = ZoneInfo(get_settings().app_timezone)
    athletes_by_day: dict[str, set[int]] = {}
    for activity in activities:
        day = f"weekday_{activity.start_date.astimezone(zone).weekday()}"
        athletes_by_day.setdefault(day, set()).add(activity.athlete_id)
    day, athlete_ids = max(athletes_by_day.items(), key=lambda row: len(row[1]))
    return {"day": day, "participants": len(athlete_ids)}


def team_overview(db: Session, kind: str, now: datetime | None = None) -> dict[str, int]:
    """Return registered and active RUD@S participation for a reporting period."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    registered = db.scalars(select(Athlete).where(Athlete.is_active.is_(True), Athlete.is_club_member.is_(True))).all()
    activities = db.scalars(select(Activity).where(Activity.start_date >= start, Activity.start_date < end)).all()
    registered_ids = {athlete.id for athlete in registered}
    current = [activity for activity in activities if activity.athlete_id in registered_ids]
    return {"registered": len(registered), "participants": len({activity.athlete_id for activity in current}), "activities": len(current), "distance_m": sum(activity.distance_m for activity in current), "moving_time_s": sum(activity.moving_time_s for activity in current)}


def team_group_stats(db: Session, kind: str, now: datetime | None = None) -> dict[str, dict[str, int]]:
    """Count members and activities for non-distance groups such as strength."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.start_date >= start, Activity.start_date < end)).all()
    result = {sport: {"participants": 0, "activities": 0} for sport in ("strength", "wellbeing")}
    for sport in result:
        matching = [activity for activity in activities if activity.normalized_sport == sport]
        result[sport] = {"participants": len({activity.athlete_id for activity in matching}), "activities": len(matching)}
    return result


def team_sport_highlights(db: Session, now: datetime | None = None, kind: str = "week") -> dict[str, dict[str, str | float]]:
    """Return each discipline's biggest club distance day in the selected period."""
    start, end = period_bounds(kind, now or datetime.now(UTC))
    activities = db.scalars(select(Activity).where(Activity.start_date >= start, Activity.start_date < end)).all()
    zone = ZoneInfo(get_settings().app_timezone)
    totals: dict[tuple[str, str], float] = {}
    for activity in activities:
        if activity.normalized_sport not in {"swim", "open_water", "bike", "run", "walk"}:
            continue
        day = f"weekday_{activity.start_date.astimezone(zone).weekday()}"
        key = (activity.normalized_sport, day)
        totals[key] = totals.get(key, 0) + activity.distance_m
    result: dict[str, dict[str, str | float]] = {}
    for sport in ("swim", "open_water", "bike", "run", "walk"):
        candidates = [(day, distance) for (candidate_sport, day), distance in totals.items() if candidate_sport == sport]
        if candidates:
            day, distance = max(candidates, key=lambda item: item[1])
            result[sport] = {"day": day, "distance_m": distance}
    return result


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
