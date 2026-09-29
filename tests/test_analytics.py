from datetime import UTC, datetime

import pytest

from app.analytics import activity_highlights, athlete_discipline_stats, athlete_period_stats, monthly_comparison, rankings, team_highlights, team_sport_highlights, weekly_comparison
from app.models import Activity, Athlete


def athlete(strava_id: int, name: str) -> Athlete:
    return Athlete(strava_athlete_id=strava_id, firstname=name, lastname="Runner")


def activity(athlete: Athlete, strava_id: int, sport: str, distance: float, date: datetime) -> Activity:
    return Activity(
        athlete=athlete,
        strava_activity_id=strava_id,
        name="Entreno",
        sport_type=sport.title(),
        normalized_sport=sport,
        start_date=date,
        distance_m=distance,
        moving_time_s=3600,
        elapsed_time_s=3600,
        total_elevation_gain_m=100,
    )


def test_stats_only_include_the_requested_week(db):
    carlos = athlete(1, "Carlos")
    db.add_all([
        carlos,
        activity(carlos, 11, "run", 5_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "run", 9_000, datetime(2026, 9, 20, 15, tzinfo=UTC)),
    ])
    db.commit()

    stats = athlete_period_stats(db, carlos.id, "week", datetime(2026, 9, 30, 12, tzinfo=UTC))

    assert stats["distance_m"] == 5_000
    assert stats["activity_count"] == 1
    assert stats["active_days"] == 1


def test_rankings_are_grouped_by_sport_and_sorted(db):
    carlos, ana = athlete(1, "Carlos"), athlete(2, "Ana")
    db.add_all([
        carlos,
        ana,
        activity(carlos, 11, "run", 5_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "run", 3_000, datetime(2026, 9, 30, 15, tzinfo=UTC)),
        activity(ana, 13, "run", 10_000, datetime(2026, 9, 30, 15, tzinfo=UTC)),
        activity(ana, 14, "bike", 25_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
    ])
    db.commit()

    board = rankings(db, "week", datetime(2026, 9, 30, 18, tzinfo=UTC))

    assert [(row["name"], row["distance_m"]) for row in board["run"]] == [
        ("Ana Runner", 10_000),
        ("Carlos Runner", 8_000),
    ]
    assert board["bike"][0]["distance_m"] == 25_000
    assert board["swim"] == []


def test_monthly_comparison_has_no_percentage_without_baseline(db):
    carlos = athlete(1, "Carlos")
    db.add_all([carlos, activity(carlos, 11, "bike", 42_000, datetime(2026, 9, 2, 15, tzinfo=UTC))])
    db.commit()

    comparison = monthly_comparison(db, carlos.id, "bike", datetime(2026, 9, 30, tzinfo=UTC))

    assert comparison["current_distance"] == 42_000
    assert comparison["previous_distance"] == 0
    assert comparison["percentage_change"] is None


def test_weekly_comparison_and_highlights_include_previous_week(db):
    carlos, ana = athlete(1, "Carlos"), athlete(2, "Ana")
    db.add_all([
        carlos, ana,
        activity(carlos, 11, "run", 8_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "run", 5_000, datetime(2026, 9, 30, 15, tzinfo=UTC)),
        activity(carlos, 13, "run", 4_000, datetime(2026, 9, 22, 15, tzinfo=UTC)),
        activity(ana, 14, "bike", 10_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
    ])
    db.commit()

    now = datetime(2026, 9, 30, 18, tzinfo=UTC)
    comparison = weekly_comparison(db, carlos.id, now)
    highlights = activity_highlights(db, carlos.id, now)
    team = team_highlights(db, now)

    assert comparison["distance_change_m"] == 9_000
    assert highlights["longest_distance_m"] == 8_000
    assert team["participants"] == 2


def test_gym_ranking_is_sorted_by_sessions(db):
    carlos, ana = athlete(1, "Carlos"), athlete(2, "Ana")
    db.add_all([
        carlos, ana,
        activity(carlos, 11, "gym", 0, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "gym", 0, datetime(2026, 9, 30, 15, tzinfo=UTC)),
        activity(ana, 13, "gym", 0, datetime(2026, 9, 29, 15, tzinfo=UTC)),
    ])
    db.commit()

    board = rankings(db, "week", datetime(2026, 9, 30, 18, tzinfo=UTC))

    assert [(row["name"], row["activity_count"]) for row in board["gym"]] == [("Carlos Runner", 2), ("Ana Runner", 1)]


def test_last_month_and_team_discipline_highlights(db):
    carlos = athlete(1, "Carlos")
    db.add_all([
        carlos,
        activity(carlos, 11, "bike", 20_000, datetime(2026, 8, 25, 15, tzinfo=UTC)),
        activity(carlos, 12, "run", 8_000, datetime(2026, 8, 26, 15, tzinfo=UTC)),
    ])
    db.commit()

    stats = athlete_period_stats(db, carlos.id, "last_month", datetime(2026, 9, 30, tzinfo=UTC))
    highlights = team_sport_highlights(db, datetime(2026, 9, 30, tzinfo=UTC), "last_month")

    assert stats["distance_m"] == 28_000
    assert highlights["bike"]["distance_m"] == 20_000
    assert highlights["run"]["day"] == "weekday_2"


def test_athlete_discipline_totals_keep_each_sport_separate(db):
    carlos = athlete(1, "Carlos")
    db.add_all([
        carlos,
        activity(carlos, 11, "swim", 2_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "bike", 20_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 13, "gym", 0, datetime(2026, 9, 30, 15, tzinfo=UTC)),
    ])
    db.commit()

    totals = athlete_discipline_stats(db, carlos.id, "week", datetime(2026, 9, 30, tzinfo=UTC))

    assert totals["swim"] == {"distance_m": 2_000, "activity_count": 1}
    assert totals["bike"] == {"distance_m": 20_000, "activity_count": 1}
    assert totals["run"]["activity_count"] == 0
    assert totals["gym"]["activity_count"] == 1


def test_open_water_is_kept_separate_from_pool_swimming(db):
    carlos = athlete(1, "Carlos")
    db.add_all([
        carlos,
        activity(carlos, 11, "swim", 2_000, datetime(2026, 9, 29, 15, tzinfo=UTC)),
        activity(carlos, 12, "open_water", 3_000, datetime(2026, 9, 30, 15, tzinfo=UTC)),
    ])
    db.commit()

    totals = athlete_discipline_stats(db, carlos.id, "week", datetime(2026, 9, 30, tzinfo=UTC))
    board = rankings(db, "week", datetime(2026, 9, 30, tzinfo=UTC))

    assert totals["swim"]["distance_m"] == 2_000
    assert totals["open_water"]["distance_m"] == 3_000
    assert board["open_water"][0]["distance_m"] == 3_000
