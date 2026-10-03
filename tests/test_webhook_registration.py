import asyncio
from types import SimpleNamespace

import httpx
from app.webhooks import ensure_strava_webhook


def settings():
    return SimpleNamespace(
        strava_client_id="25116",
        strava_client_secret="secret",
        webhook_verify_token="verify",
        app_base_url="https://rudo-radar.up.railway.app",
    )


def test_existing_webhook_is_reused(monkeypatch):
    monkeypatch.setattr("app.webhooks.get_settings", settings)

    def handler(request):
        assert request.url.params["client_id"] == "25116"
        return httpx.Response(200, json=[{"id": 42, "callback_url": "https://rudo-radar.up.railway.app/webhooks/strava"}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await ensure_strava_webhook(client) == 42
    asyncio.run(run())


def test_missing_webhook_is_created(monkeypatch):
    monkeypatch.setattr("app.webhooks.get_settings", settings)
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        assert b"verify_token=verify" in request.content
        assert b"callback_url=https%3A%2F%2Frudo-radar.up.railway.app%2Fwebhooks%2Fstrava" in request.content
        return httpx.Response(201, json={"id": 84})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await ensure_strava_webhook(client) == 84
    asyncio.run(run())
    assert [request.method for request in requests] == ["GET", "POST"]


def test_different_existing_webhook_is_not_replaced(monkeypatch):
    monkeypatch.setattr("app.webhooks.get_settings", settings)
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json=[{"id": 12, "callback_url": "https://example.com/webhook"}])

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await ensure_strava_webhook(client) is None
    asyncio.run(run())
    assert methods == ["GET"]
