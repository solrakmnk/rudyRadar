"""Event-driven Strava synchronization.

Every webhook delivery is stored in ``strava_webhook_events`` before Strava gets
its HTTP 200, then processed outside the request. The table gives us:

* idempotency: a redelivered event hits the unique constraint and is dropped;
* ordering: events older than one already applied for the same activity are
  skipped, and an event superseded by a newer pending one is not fetched;
* controlled retries with exponential backoff for transient Strava failures,
  never for invalid credentials;
* a diagnosable record of anything that could not be processed.

Strava is only called when the event cannot be applied from its own payload.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Activity, Athlete, StravaWebhookEvent
from app.services import (
    StravaAuthError,
    StravaClient,
    StravaError,
    StravaForbiddenError,
    StravaNotFoundError,
    StravaRateLimitError,
    StravaTransientError,
    call_with_token,
    normalize_sport,
    parse_scopes,
)
from app.sync import upsert_activity
from app.webhooks import resolve_subscription_id

logger = logging.getLogger(__name__)

# Delay before attempt n+1 (seconds). After MAX_ATTEMPTS the event is marked failed.
BACKOFF_SECONDS = (60, 300, 900, 3600, 6 * 3600)
MAX_ATTEMPTS = len(BACKOFF_SECONDS) + 1
PROCESSING_LEASE = timedelta(minutes=15)
RETRYABLE = ("pending", "retry")
OPEN = ("pending", "retry", "processing")
LOCAL_UPDATE_FIELDS = {"title", "type"}
PRIVATE_VISIBILITY = {"only_me", "Only You"}
# Outcomes after which the local copy reflects Strava's full state at processing time.
FULL_STATE_OUTCOMES = {"upserted", "not_visible", "removed_private", "deleted", "already_absent"}
UNVERIFIED_RETRY_SECONDS = 300


class SubscriptionUnverified(Exception):
    """The app's own subscription id is not known yet, so the event cannot be trusted."""


def _now() -> datetime:
    return datetime.now(UTC)


def _as_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def parse_event(payload: dict) -> dict | None:
    """Validate the fields Strava documents for push events. Returns None when malformed."""
    object_type = payload.get("object_type")
    aspect_type = payload.get("aspect_type")
    owner_id = _as_int(payload.get("owner_id"))
    object_id = _as_int(payload.get("object_id"))
    event_time = _as_int(payload.get("event_time"))
    updates = payload.get("updates") or {}
    if object_type not in {"activity", "athlete"} or aspect_type not in {"create", "update", "delete"}:
        return None
    if owner_id is None or object_id is None or not isinstance(updates, dict):
        return None
    return {
        "subscription_id": _as_int(payload.get("subscription_id")),
        "owner_id": owner_id,
        "object_type": object_type,
        "object_id": object_id,
        "aspect_type": aspect_type,
        # event_time is part of the idempotency key; fall back to receipt time if absent.
        "event_time": event_time if event_time is not None else int(_now().timestamp()),
        "updates": json.dumps(updates, sort_keys=True) if updates else None,
        "payload_hash": hashlib.sha256(json.dumps(updates, sort_keys=True).encode()).hexdigest(),
    }


def record_event(db: Session, payload: dict) -> tuple[StravaWebhookEvent | None, bool]:
    """Persist a delivery. Returns (event, is_new). Duplicates return (existing, False)."""
    fields = parse_event(payload)
    if fields is None:
        return None, False
    event = StravaWebhookEvent(**fields, status="pending", attempts=0)
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(StravaWebhookEvent).where(
            StravaWebhookEvent.owner_id == fields["owner_id"],
            StravaWebhookEvent.object_type == fields["object_type"],
            StravaWebhookEvent.object_id == fields["object_id"],
            StravaWebhookEvent.aspect_type == fields["aspect_type"],
            StravaWebhookEvent.event_time == fields["event_time"],
            StravaWebhookEvent.payload_hash == fields["payload_hash"],
        ))
        logger.info("Duplicate Strava webhook delivery ignored event_id=%s", existing.id if existing else None)
        return existing, False
    return event, True


def claim_event(db: Session, event_id: int) -> StravaWebhookEvent | None:
    """Atomically move an event to ``processing`` so two workers never handle it twice."""
    now = _now()
    result = db.execute(
        update(StravaWebhookEvent)
        .where(
            StravaWebhookEvent.id == event_id,
            StravaWebhookEvent.status.in_(RETRYABLE),
            or_(StravaWebhookEvent.next_attempt_at.is_(None), StravaWebhookEvent.next_attempt_at <= now),
        )
        .values(status="processing", attempts=StravaWebhookEvent.attempts + 1, next_attempt_at=now + PROCESSING_LEASE)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if result.rowcount != 1:
        return None
    event = db.get(StravaWebhookEvent, event_id)
    db.refresh(event)
    return event


def _finish(db: Session, event: StravaWebhookEvent, status: str, outcome: str) -> str:
    event.status = status
    event.outcome = outcome
    event.last_error = None
    event.next_attempt_at = None
    event.processed_at = _now()
    db.commit()
    logger.info("strava_webhook_event id=%s object=%s aspect=%s status=%s outcome=%s", event.id, event.object_type, event.aspect_type, status, outcome)
    return outcome


def _schedule_retry(db: Session, event: StravaWebhookEvent, error: str, min_delay: int = 0) -> str:
    if event.attempts >= MAX_ATTEMPTS:
        event.status = "failed"
        event.next_attempt_at = None
        event.processed_at = _now()
        event.outcome = "retries_exhausted"
    else:
        delay = max(BACKOFF_SECONDS[min(event.attempts - 1, len(BACKOFF_SECONDS) - 1)], min_delay)
        event.status = "retry"
        event.next_attempt_at = _now() + timedelta(seconds=delay)
    event.last_error = error[:120]
    db.commit()
    logger.warning("strava_webhook_event id=%s attempt=%s status=%s error=%s", event.id, event.attempts, event.status, error)
    return event.status


def _event_updates(event: StravaWebhookEvent) -> dict:
    return json.loads(event.updates) if event.updates else {}


def _is_local_update(event: StravaWebhookEvent) -> bool:
    """An update that can be applied from its own payload (title and/or type only)."""
    updates = _event_updates(event)
    return event.aspect_type == "update" and bool(updates) and set(updates) <= LOCAL_UPDATE_FIELDS


def _later_events(db: Session, event: StravaWebhookEvent) -> list[StravaWebhookEvent]:
    """Events for the same object that happened after this one.

    Order is (event_time, id): event_time has one-second resolution, so events
    sharing a second are ordered by arrival.
    """
    candidates = db.scalars(select(StravaWebhookEvent).where(
        StravaWebhookEvent.object_type == event.object_type,
        StravaWebhookEvent.object_id == event.object_id,
        StravaWebhookEvent.id != event.id,
        StravaWebhookEvent.event_time >= event.event_time,
        StravaWebhookEvent.status.not_in(("ignored", "failed")),
    )).all()
    return [e for e in candidates if (e.event_time, e.id) > (event.event_time, event.id)]


def _deleted_at_or_after(db: Session, event: StravaWebhookEvent) -> bool:
    return db.scalar(select(func.count(StravaWebhookEvent.id)).where(
        StravaWebhookEvent.object_type == "activity",
        StravaWebhookEvent.object_id == event.object_id,
        StravaWebhookEvent.aspect_type == "delete",
        StravaWebhookEvent.status == "processed",
        StravaWebhookEvent.event_time >= event.event_time,
    )) > 0


def _remove_local(db: Session, athlete: Athlete, activity_id: int) -> bool:
    activity = db.scalar(select(Activity).where(Activity.strava_activity_id == activity_id, Activity.athlete_id == athlete.id))
    if activity:
        db.delete(activity)
        return True
    return False


def _apply(db: Session, event: StravaWebhookEvent, client: StravaClient) -> tuple[str, str]:
    """Apply one event. Returns (status, outcome). Raises Strava errors for the caller to classify."""
    athlete = db.scalar(select(Athlete).where(Athlete.strava_athlete_id == event.owner_id))
    updates = json.loads(event.updates) if event.updates else {}

    # Strava push events are not signed. The subscription id filters stray or
    # misrouted deliveries; it is checked against the id Strava reports for this
    # app, never trusted blindly while that id is still unknown.
    known_subscription = resolve_subscription_id()
    if known_subscription is None:
        raise SubscriptionUnverified()
    if event.subscription_id != known_subscription:
        return "ignored", "untrusted_subscription"

    if event.object_type == "athlete":
        if str(updates.get("authorized", "")).lower() == "false":
            if not athlete:
                return "ignored", "unknown_athlete"
            if not _deauthorization_confirmed(db, athlete, client):
                logger.warning("Deauthorization event not confirmed by Strava for athlete_id=%s; data kept", athlete.id)
                return "ignored", "deauthorization_not_confirmed"
            # Strava deauthorization: delete the athlete, their activities and their event log.
            db.execute(delete(StravaWebhookEvent).where(StravaWebhookEvent.owner_id == event.owner_id, StravaWebhookEvent.id != event.id))
            db.delete(athlete)
            db.commit()
            logger.warning("Strava deauthorization confirmed; local athlete data deleted")
            return "processed", "athlete_deleted"
        return "ignored", "athlete_update_not_used"

    if not athlete:
        return "ignored", "unknown_athlete"

    if event.aspect_type == "delete":
        # Deletions are applied locally regardless of the athlete's state: no API call.
        removed = _remove_local(db, athlete, event.object_id)
        athlete.last_sync_at = _now()
        db.commit()
        return "processed", "deleted" if removed else "already_absent"

    if not athlete.is_club_member or athlete.auth_status != "connected" or not athlete.is_active:
        return "ignored", "athlete_not_syncing"
    if _deleted_at_or_after(db, event):
        return "ignored", "already_deleted"
    later = _later_events(db, event)
    if any(e.status == "processed" and e.outcome in FULL_STATE_OUTCOMES for e in later):
        # A later event already read the activity's full state from Strava.
        return "ignored", "stale"
    if any(e.status in OPEN and not _is_local_update(e) for e in later):
        # A later queued event will read the full state; a later title/type-only
        # update cannot stand in for this one, so it never supersedes it.
        return "ignored", "superseded"
    # With any later event around, applying this payload could overwrite newer
    # values (or miss fields), so read the current state from Strava instead.
    apply_locally = not later

    includes_private = "activity:read_all" in parse_scopes(athlete.authorized_scopes)
    if event.aspect_type == "update":
        if str(updates.get("private", "")).lower() == "true" and not includes_private:
            _remove_local(db, athlete, event.object_id)
            athlete.last_sync_at = _now()
            db.commit()
            return "processed", "removed_private"
        local = db.scalar(select(Activity).where(Activity.strava_activity_id == event.object_id, Activity.athlete_id == athlete.id))
        if local and apply_locally and _is_local_update(event):
            # Title and sport type changes come in the event itself.
            if "title" in updates:
                local.name = str(updates["title"])[:255] or local.name
            if "type" in updates:
                local.sport_type = str(updates["type"])[:50]
                local.normalized_sport = normalize_sport(local.sport_type, local.workout_type)
            athlete.last_sync_at = _now()
            db.commit()
            return "processed", "updated_from_event"

    try:
        item = call_with_token(db, athlete, client, lambda token: client.activity(token, event.object_id))
    except (StravaNotFoundError, StravaForbiddenError):
        # Deleted, or no longer visible with the scopes the athlete granted.
        _remove_local(db, athlete, event.object_id)
        athlete.last_sync_at = _now()
        db.commit()
        return "processed", "not_visible"

    owner = (item.get("athlete") or {}).get("id")
    if owner is not None and int(owner) != event.owner_id:
        return "ignored", "owner_mismatch"
    is_private = item.get("private") or item.get("visibility") in PRIVATE_VISIBILITY
    if is_private and not includes_private:
        _remove_local(db, athlete, event.object_id)
        athlete.last_sync_at = _now()
        db.commit()
        return "processed", "removed_private"
    upsert_activity(db, athlete, item)
    athlete.last_sync_at = _now()
    db.commit()
    return "processed", "upserted"


def _deauthorization_confirmed(db: Session, athlete: Athlete, client: StravaClient) -> bool:
    """Deleting an athlete is irreversible, so confirm the revocation with Strava first.

    After a real deauthorization every token Strava issued to this app for the
    athlete is invalid: the request (and the forced refresh) is rejected. If the
    athlete's credentials still work, the event did not come from a revocation.
    """
    try:
        call_with_token(db, athlete, client, client.athlete)
    except StravaAuthError:
        return True
    return False


def process_event(db: Session, event_id: int, client: StravaClient | None = None) -> str | None:
    """Claim and process one event. Returns its outcome/status, or None if not claimable."""
    event = claim_event(db, event_id)
    if event is None:
        return None
    client = client or StravaClient()
    try:
        status, outcome = _apply(db, event, client)
        return _finish(db, event, status, outcome)
    except SubscriptionUnverified:
        db.rollback()
        # Waiting for the subscription id is not a processing failure: keep the
        # event queued without consuming one of its attempts.
        event.attempts = max(event.attempts - 1, 0)
        event.status, event.last_error = "retry", "subscription_unverified"
        event.next_attempt_at = _now() + timedelta(seconds=UNVERIFIED_RETRY_SECONDS)
        db.commit()
        logger.warning("strava_webhook_event id=%s deferred: subscription id not verified yet", event.id)
        return "retry"
    except StravaRateLimitError as e:
        db.rollback()
        return _schedule_retry(db, event, "rate_limited", e.retry_after)
    except StravaTransientError:
        db.rollback()
        return _schedule_retry(db, event, "strava_unavailable")
    except StravaAuthError:
        db.rollback()
        # The athlete has been flagged as reauth_required; retrying cannot succeed.
        event.status, event.outcome, event.last_error = "failed", "athlete_auth_invalid", "auth_rejected"
        event.next_attempt_at, event.processed_at = None, _now()
        db.commit()
        logger.warning("strava_webhook_event id=%s failed: athlete credentials rejected", event.id)
        return "failed"
    except StravaError as e:
        db.rollback()
        event.status, event.outcome, event.last_error = "failed", "strava_error", str(e)[:120]
        event.next_attempt_at, event.processed_at = None, _now()
        db.commit()
        logger.warning("strava_webhook_event id=%s failed with a non-retryable Strava error", event.id)
        return "failed"
    except Exception:
        db.rollback()
        logger.exception("strava_webhook_event id=%s raised an unexpected error", event.id)
        return _schedule_retry(db, event, "internal_error")


def process_event_in_new_session(event_id: int) -> None:
    """Background-task entry point: one DB session per event."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        process_event(db, event_id)
    except Exception:
        logger.exception("Could not process strava_webhook_event id=%s", event_id)
    finally:
        db.close()


def release_expired_leases(db: Session) -> int:
    """Return events stuck in ``processing`` (worker crashed or redeployed) to the retry queue."""
    result = db.execute(
        update(StravaWebhookEvent)
        .where(StravaWebhookEvent.status == "processing", StravaWebhookEvent.next_attempt_at < _now())
        .values(status="retry", next_attempt_at=_now(), last_error="lease_expired")
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount or 0


def process_due_events(db: Session, client: StravaClient | None = None, limit: int = 50) -> dict[str, int]:
    """Process pending/retry events whose backoff has elapsed. Makes no calls when the queue is empty."""
    released = release_expired_leases(db)
    now = _now()
    ids = db.scalars(
        select(StravaWebhookEvent.id)
        .where(
            StravaWebhookEvent.status.in_(RETRYABLE),
            or_(StravaWebhookEvent.next_attempt_at.is_(None), StravaWebhookEvent.next_attempt_at <= now),
        )
        .order_by(StravaWebhookEvent.event_time, StravaWebhookEvent.id)
        .limit(limit)
    ).all()
    result = {"released": released, "attempted": 0, "processed": 0, "ignored": 0, "retry": 0, "failed": 0}
    if ids and client is None:
        client = StravaClient()
    for event_id in ids:
        if process_event(db, event_id, client) is None:
            continue
        event = db.get(StravaWebhookEvent, event_id)
        result["attempted"] += 1
        result[event.status] = result.get(event.status, 0) + 1
        if event.status == "retry" and event.last_error == "rate_limited":
            break  # Stop draining the queue until the rate-limit window resets.
    return result


def purge_old_events(db: Session, *, keep_days: int = 30, keep_failed_days: int = 90) -> int:
    now = _now()
    result = db.execute(delete(StravaWebhookEvent).where(or_(
        (StravaWebhookEvent.status.in_(("processed", "ignored"))) & (StravaWebhookEvent.received_at < now - timedelta(days=keep_days)),
        (StravaWebhookEvent.status == "failed") & (StravaWebhookEvent.received_at < now - timedelta(days=keep_failed_days)),
        (StravaWebhookEvent.last_error == "subscription_unverified") & (StravaWebhookEvent.received_at < now - timedelta(days=keep_failed_days)),
    )))
    db.commit()
    return result.rowcount or 0


def event_summary(db: Session, recent_failures: int = 20) -> dict:
    counts = dict(db.execute(select(StravaWebhookEvent.status, func.count(StravaWebhookEvent.id)).group_by(StravaWebhookEvent.status)).all())
    outcomes = dict(db.execute(select(StravaWebhookEvent.outcome, func.count(StravaWebhookEvent.id)).where(StravaWebhookEvent.outcome.is_not(None)).group_by(StravaWebhookEvent.outcome)).all())
    failures = db.scalars(
        select(StravaWebhookEvent)
        .where(StravaWebhookEvent.status.in_(("failed", "retry")))
        .order_by(StravaWebhookEvent.received_at.desc())
        .limit(recent_failures)
    ).all()
    last = db.scalar(select(func.max(StravaWebhookEvent.received_at)))
    return {
        "by_status": counts,
        "by_outcome": outcomes,
        "last_received_at": last.isoformat() if last else None,
        "unresolved": [
            {
                "id": e.id, "object_type": e.object_type, "aspect_type": e.aspect_type, "object_id": e.object_id,
                "status": e.status, "attempts": e.attempts, "last_error": e.last_error,
                "next_attempt_at": e.next_attempt_at.isoformat() if e.next_attempt_at else None,
            }
            for e in failures
        ],
    }


def requeue_failed(db: Session, event_ids: list[int] | None = None) -> int:
    """Manual action: give failed events another round of attempts."""
    stmt = update(StravaWebhookEvent).where(StravaWebhookEvent.status == "failed")
    if event_ids:
        stmt = stmt.where(StravaWebhookEvent.id.in_(event_ids))
    result = db.execute(stmt.values(status="retry", attempts=0, next_attempt_at=_now(), outcome=None).execution_options(synchronize_session=False))
    db.commit()
    return result.rowcount or 0
