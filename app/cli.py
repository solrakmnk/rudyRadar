"""Operational commands. None of them polls Strava for new activities.

``python -m app.cli`` (no arguments) is what the existing Railway cron
``rudo-sync`` runs. It used to download the last 21 days of activities for
every athlete every two hours; it now only does maintenance:

* retries webhook events whose backoff has elapsed (Strava is called only for
  those events);
* revalidates club membership for athletes not checked in
  MEMBERSHIP_REVALIDATION_DAYS and refreshes their photo URL (one
  /athlete/clubs and one /athlete call per athlete per week);
* purges old webhook event records.

Manual commands:
  python -m app.cli status
  python -m app.cli recover --athlete-id 12 --days 7
  python -m app.cli requeue-failed [--event-id 5 ...]
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import logging

from sqlalchemy import or_, select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Athlete
from app.services import StravaAuthError, StravaClient, StravaError, api_metrics, call_with_token, is_club_member, profile_photo_url
from app.strava_events import event_summary, process_due_events, purge_old_events, requeue_failed
from app.sync import recover_activities

logger = logging.getLogger("app.cli")


def revalidate_memberships(db, client: StravaClient) -> dict[str, int]:
    days = get_settings().membership_revalidation_days
    result = {"checked": 0, "left_club": 0, "errors": 0}
    if days <= 0:
        return result
    cutoff = datetime.now(UTC) - timedelta(days=days)
    athletes = db.scalars(select(Athlete).where(
        Athlete.is_active.is_(True), Athlete.is_club_member.is_(True), Athlete.auth_status == "connected",
        or_(Athlete.membership_checked_at.is_(None), Athlete.membership_checked_at < cutoff),
    )).all()
    for athlete in athletes:
        try:
            clubs = call_with_token(db, athlete, client, client.clubs)
        except StravaAuthError:
            result["errors"] += 1  # athlete already flagged reauth_required
            continue
        except StravaError:
            db.rollback()
            result["errors"] += 1
            if api_metrics.blocked_for():
                break
            continue
        except Exception:
            # e.g. a token that cannot be decrypted: skip this athlete, keep the run going.
            db.rollback()
            result["errors"] += 1
            logger.exception("Membership revalidation failed for athlete_id=%s", athlete.id)
            continue
        athlete.membership_checked_at = datetime.now(UTC)
        athlete.membership_check_error = None
        result["checked"] += 1
        if not is_club_member(clubs):
            athlete.is_club_member = False
            athlete.is_active = False
            athlete.membership_check_status = "not_member"
            result["left_club"] += 1
            logger.info("athlete_id=%s is no longer a RUD@S member", athlete.id)
        else:
            athlete.membership_check_status = "verified"
        db.commit()
        if athlete.is_club_member and _refresh_photo(db, athlete, client):
            result["photos_updated"] = result.get("photos_updated", 0) + 1
    return result


def _refresh_photo(db, athlete: Athlete, client: StravaClient) -> bool:
    """Keep the stored photo URL current: Strava's old photo URLs stop working when an
    athlete changes their picture, and no webhook announces profile changes. One
    GET /athlete per athlete, at most once per revalidation period."""
    try:
        photo = profile_photo_url(call_with_token(db, athlete, client, client.athlete))
    except StravaError:
        db.rollback()
        return False
    if photo == athlete.profile_url:
        return False
    athlete.profile_url = photo
    db.commit()
    return True


def _safe(db, name: str, fn):
    try:
        return fn()
    except Exception:
        db.rollback()
        logger.exception("Maintenance step failed: %s", name)
        return {"error": True}


def maintenance(db) -> dict:
    client = StravaClient()
    return {
        "mode": "maintenance",
        "activity_polling": False,
        "webhook_retries": _safe(db, "webhook_retries", lambda: process_due_events(db, client)),
        "membership": _safe(db, "membership", lambda: revalidate_memberships(db, client)),
        "purged_events": _safe(db, "purge", lambda: purge_old_events(db)),
        "strava_api": api_metrics.snapshot()["calls_by_endpoint"],
    }


def status(db) -> dict:
    athletes = db.scalars(select(Athlete)).all()
    return {
        "athletes": {
            "total": len(athletes),
            "active": sum(a.is_active and a.is_club_member for a in athletes),
            "reauth_required": [a.id for a in athletes if a.auth_status == "reauth_required"],
            "import_not_completed": [a.id for a in athletes if a.initial_import_status != "completed"],
        },
        "webhook_events": event_summary(db),
    }


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("maintenance")
    sub.add_parser("status")
    recover = sub.add_parser("recover", help="bounded manual catch-up for one athlete")
    recover.add_argument("--athlete-id", type=int, required=True)
    recover.add_argument("--days", type=int, default=7)
    requeue = sub.add_parser("requeue-failed")
    requeue.add_argument("--event-id", type=int, action="append")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "status":
            result = status(db)
        elif args.command == "recover":
            athlete = db.get(Athlete, args.athlete_id)
            if not athlete:
                raise SystemExit("athlete not found")
            result = {"athlete_id": athlete.id, "activities": recover_activities(db, athlete, StravaClient(), days=args.days)}
        elif args.command == "requeue-failed":
            result = {"requeued": requeue_failed(db, args.event_id)}
        else:
            result = maintenance(db)
        print(json.dumps(result, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
