from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
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


async def register_strava_webhook_after_startup() -> None:
    # Give Railway time to put the healthy deployment behind the public domain
    # before Strava performs its synchronous callback verification.
    await asyncio.sleep(10)
    await ensure_strava_webhook()
