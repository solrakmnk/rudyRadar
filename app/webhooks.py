from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
# Set once the subscription is confirmed; incoming events from other ids are ignored.
active_subscription_id: int | None = None
SUBSCRIPTIONS_URL = "https://www.strava.com/api/v3/push_subscriptions"


async def ensure_strava_webhook(client: httpx.AsyncClient | None = None) -> int | None:
    """Create the app's single Strava subscription when it does not exist."""
    settings = get_settings()
    if not all((settings.strava_client_id, settings.strava_client_secret, settings.webhook_verify_token)):
        logger.info("Strava webhook registration skipped: configuration is incomplete")
        return None

    callback_url = f"{settings.app_base_url.rstrip('/')}/webhooks/strava"
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.get(
            SUBSCRIPTIONS_URL,
            params={"client_id": settings.strava_client_id, "client_secret": settings.strava_client_secret},
        )
        response.raise_for_status()
        subscriptions = response.json()
        for subscription in subscriptions:
            if subscription.get("callback_url") == callback_url:
                logger.warning("Strava webhook subscription ready: id=%s", subscription.get("id"))
                return subscription.get("id")
        if subscriptions:
            logger.error("Strava already has a different webhook subscription; refusing to replace it")
            return None

        response = await client.post(
            SUBSCRIPTIONS_URL,
            data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret,
                "callback_url": callback_url,
                "verify_token": settings.webhook_verify_token,
            },
        )
        response.raise_for_status()
        subscription_id = response.json().get("id")
        logger.warning("Strava webhook subscription created: id=%s", subscription_id)
        return subscription_id
    except (httpx.HTTPError, ValueError, TypeError):
        logger.exception("Unable to ensure Strava webhook subscription")
        return None
    finally:
        if owns_client:
            await client.aclose()


_last_lookup: float | None = None  # monotonic time of the last lookup; None = never
LOOKUP_INTERVAL_SECONDS = 300


def resolve_subscription_id(client: httpx.Client | None = None) -> int | None:
    """Return this app's subscription id, looking it up in Strava when unknown.

    Used by the event processor so events received before startup registration
    finished are verified instead of trusted. Lookups are throttled to one every
    five minutes; the call uses the app's client credentials, not athlete tokens.
    """
    global active_subscription_id, _last_lookup
    if active_subscription_id is not None:
        return active_subscription_id
    if _last_lookup is not None and time.monotonic() - _last_lookup < LOOKUP_INTERVAL_SECONDS:
        return None
    _last_lookup = time.monotonic()
    settings = get_settings()
    if not (settings.strava_client_id and settings.strava_client_secret):
        return None
    callback_url = f"{settings.app_base_url.rstrip('/')}/webhooks/strava"
    owns_client = client is None
    client = client or httpx.Client(timeout=15)
    try:
        response = client.get(SUBSCRIPTIONS_URL, params={"client_id": settings.strava_client_id, "client_secret": settings.strava_client_secret})
        response.raise_for_status()
        for subscription in response.json():
            if subscription.get("callback_url") == callback_url and isinstance(subscription.get("id"), int):
                active_subscription_id = subscription["id"]
                logger.warning("Strava webhook subscription verified: id=%s", active_subscription_id)
                return active_subscription_id
        logger.error("No Strava webhook subscription matches %s", callback_url)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        logger.exception("Unable to look up the Strava webhook subscription")
    finally:
        if owns_client:
            client.close()
    return None


async def register_strava_webhook_after_startup() -> None:
    global active_subscription_id
    # Give Railway time to put the healthy deployment behind the public domain
    # before Strava performs its synchronous callback verification.
    await asyncio.sleep(10)
    subscription_id = await ensure_strava_webhook()
    if isinstance(subscription_id, int):
        active_subscription_id = subscription_id


async def retry_webhook_events_periodically() -> None:
    """Retry due webhook events from the queue. Reads the database only; Strava is
    called solely for events that previously failed with a transient error."""
    interval = get_settings().webhook_retry_interval_seconds
    if interval <= 0:
        return
    from app.database import SessionLocal
    from app.strava_events import process_due_events

    def run_once():
        db = SessionLocal()
        try:
            return process_due_events(db)
        finally:
            db.close()

    await asyncio.sleep(30)
    while True:
        try:
            result = await asyncio.to_thread(run_once)
            if result.get("attempted") or result.get("released"):
                logger.info("Webhook retry pass: %s", result)
        except Exception:
            logger.exception("Webhook retry pass failed")
        await asyncio.sleep(interval)
