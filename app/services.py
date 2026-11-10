from __future__ import annotations
from collections import Counter
from datetime import UTC, datetime, timedelta
import httpx
import logging
import threading
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Athlete

logger = logging.getLogger(__name__)

STRAVA_VISIBLE_SCOPE = "read,profile:read_all,activity:read"
STRAVA_PRIVATE_SCOPE = "read,profile:read_all,activity:read_all"


def parse_scopes(value: str | None) -> set[str]:
    return {item for item in (value or "").replace(",", " ").split() if item}

def normalize_sport(value: str | None, workout_type: int | None = None) -> str | None:
    s = value or ""
    # Strava represents pool and open-water swimming as Swim.  Its swim
    # workout type identifies open-water activities with value 2.
    if s in {"OpenWaterSwim", "OpenWater"} or (s == "Swim" and workout_type == 2): return "open_water"
    if s == "Swim": return "swim"
    if s in {"Ride", "MountainBikeRide", "GravelRide"}: return "bike"
    if s in {"Run", "TrailRun"}: return "run"
    if s in {"Walk", "Hike"}: return "walk"
    if s in {"WeightTraining", "Crossfit", "HighIntensityIntervalTraining", "Workout"}: return "strength"
    if s in {"Yoga", "Pilates", "PhysicalTherapy"}: return "wellbeing"
    if s in {"Elliptical", "StairStepper", "Rowing", "IndoorRowing"}: return "cardio"
    if get_settings().include_virtual_activities and s == "VirtualRide": return "bike"
    if get_settings().include_virtual_activities and s == "VirtualRun": return "run"
    return None

class Crypto:
    def __init__(self):
        key = get_settings().token_encryption_key
        self.fernet = Fernet(key.encode()) if key else None
    def encrypt(self, value: str) -> str:
        if not self.fernet: raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for Strava tokens")
        return self.fernet.encrypt(value.encode()).decode()
    def decrypt(self, value: str) -> str:
        if not self.fernet: raise RuntimeError("TOKEN_ENCRYPTION_KEY is required for Strava tokens")
        return self.fernet.decrypt(value.encode()).decode()

class StravaError(RuntimeError):
    """Base error for Strava calls. Subclasses describe how the caller should react."""
    status_code: int | None = None


class StravaTransientError(StravaError):
    """Timeouts, network failures and 5xx responses: safe to retry later."""


class StravaRateLimitError(StravaTransientError):
    """HTTP 429. ``retry_after`` is the number of seconds until the window resets."""
    status_code = 429

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


class StravaAuthError(StravaError):
    """HTTP 401 or a rejected refresh token. The access token is not usable."""
    status_code = 401


class StravaForbiddenError(StravaError):
    """HTTP 403: the token lacks the scope for this resource."""
    status_code = 403


class StravaNotFoundError(StravaError):
    """HTTP 404: the resource is gone or not visible with the granted scopes."""
    status_code = 404


class StravaApiMetrics:
    """Process-local counters for Strava API consumption (exposed in /admin/strava)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with getattr(self, "_lock", threading.Lock()):
            self.calls: Counter[str] = Counter()
            self.statuses: Counter[str] = Counter()
            self.last_usage: dict[str, str] = {}
            self.rate_limited_until: datetime | None = None
            self.started_at = datetime.now(UTC)

    def record(self, endpoint: str, status: int | str, headers: httpx.Headers | None = None):
        with self._lock:
            self.calls[endpoint] += 1
            self.statuses[str(status)] += 1
            if headers is not None:
                for name in ("X-RateLimit-Limit", "X-RateLimit-Usage", "X-ReadRateLimit-Limit", "X-ReadRateLimit-Usage"):
                    if name in headers:
                        self.last_usage[name] = headers[name]

    def block_until(self, until: datetime):
        with self._lock:
            if not self.rate_limited_until or until > self.rate_limited_until:
                self.rate_limited_until = until

    def blocked_for(self) -> int:
        """Seconds left before Strava calls may resume after a 429 (0 when not blocked)."""
        with self._lock:
            if not self.rate_limited_until:
                return 0
            remaining = (self.rate_limited_until - datetime.now(UTC)).total_seconds()
            return max(0, int(remaining) + 1)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "since": self.started_at.isoformat(),
                "calls_by_endpoint": dict(self.calls),
                "responses_by_status": dict(self.statuses),
                "total_calls": sum(self.calls.values()),
                "last_rate_limit_headers": dict(self.last_usage),
                "rate_limited_until": self.rate_limited_until.isoformat() if self.rate_limited_until else None,
            }


api_metrics = StravaApiMetrics()


def _endpoint_label(path: str) -> str:
    """Collapse numeric ids so metrics group by endpoint, never by athlete or activity."""
    return "/".join(":id" if part.isdigit() else part for part in path.split("/"))


def seconds_until_rate_limit_reset(headers: httpx.Headers, now: datetime | None = None) -> int:
    """Strava windows reset every 15 minutes (00, 15, 30, 45) and daily at midnight UTC."""
    now = now or datetime.now(UTC)
    daily_exhausted = False
    for limit_name, usage_name in (("X-RateLimit-Limit", "X-RateLimit-Usage"), ("X-ReadRateLimit-Limit", "X-ReadRateLimit-Usage")):
        try:
            limits = [int(v) for v in headers.get(limit_name, "").split(",")]
            usage = [int(v) for v in headers.get(usage_name, "").split(",")]
        except ValueError:
            continue
        if len(limits) == 2 and len(usage) == 2 and usage[1] >= limits[1]:
            daily_exhausted = True
    if daily_exhausted:
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds()) + 1
    next_window = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0) + timedelta(minutes=15)
    return int((next_window - now).total_seconds()) + 1


def is_club_member(clubs: list[dict], club_id: int | None = None) -> bool:
    return any(int(club.get("id", 0)) == (club_id or get_settings().strava_club_id) for club in clubs)

class StravaClient:
    base_url = "https://www.strava.com/api/v3"
    oauth_url = "https://www.strava.com/oauth"
    def __init__(self, client: httpx.Client | None = None): self.client = client or httpx.Client(timeout=15, follow_redirects=True)
    def authorization_url(self, state: str, *, include_private: bool = False, force_approval: bool = True) -> str:
        s = get_settings()
        scope = STRAVA_PRIVATE_SCOPE if include_private else STRAVA_VISIBLE_SCOPE
        return str(httpx.URL(f"{self.oauth_url}/authorize", params={"client_id": s.strava_client_id, "redirect_uri": s.strava_redirect_uri, "response_type": "code", "approval_prompt": "force" if force_approval else "auto", "scope": scope, "state": state}))
    def _request(self, method: str, path: str, *, url: str | None = None, **kwargs):
        endpoint = _endpoint_label(path)
        blocked = api_metrics.blocked_for()
        if blocked:
            # Do not hit Strava again while a 429 window is still open.
            raise StravaRateLimitError("Strava rate limit reached; try again later", blocked)
        try:
            r = self.client.request(method, url or f"{self.base_url}{path}", **kwargs)
        except httpx.TimeoutException as e:
            api_metrics.record(endpoint, "timeout")
            raise StravaTransientError("Strava did not respond in time") from e
        except httpx.TransportError as e:
            api_metrics.record(endpoint, "network_error")
            raise StravaTransientError("Strava could not be reached") from e
        api_metrics.record(endpoint, r.status_code, r.headers)
        usage = r.headers.get("X-RateLimit-Usage")
        logger.info("strava_api_call method=%s endpoint=%s status=%s usage=%s read_usage=%s", method, endpoint, r.status_code, usage or "-", r.headers.get("X-ReadRateLimit-Usage") or "-")
        if r.status_code == 429:
            retry_after = seconds_until_rate_limit_reset(r.headers)
            api_metrics.block_until(datetime.now(UTC) + timedelta(seconds=retry_after))
            logger.warning("Strava rate limit reached endpoint=%s usage=%s retry_after_s=%s", endpoint, usage or "-", retry_after)
            raise StravaRateLimitError("Strava rate limit reached; try again later", retry_after)
        if r.status_code >= 400:
            try:
                body = r.json()
                reason = body.get("message") if isinstance(body, dict) else None
            except ValueError:
                reason = None
            logger.warning("Strava request failed: method=%s endpoint=%s status=%s reason=%s", method, endpoint, r.status_code, reason or "unavailable")
            if r.status_code == 401:
                raise StravaAuthError("Strava rejected the access token")
            if r.status_code == 403:
                raise StravaForbiddenError("Strava rechazó el acceso al recurso. Revisa el acceso de la aplicación en Strava.")
            if r.status_code == 404:
                raise StravaNotFoundError("Strava resource not found")
            if r.status_code >= 500:
                raise StravaTransientError("Strava is temporarily unavailable")
            raise StravaError("Strava request failed")
        return r.json()
    def _oauth_token(self, data: dict, failure: str):
        try:
            r = self.client.post(f"{self.oauth_url}/token", data=data)
        except httpx.TimeoutException as e:
            api_metrics.record("/oauth/token", "timeout")
            raise StravaTransientError("Strava did not respond in time") from e
        except httpx.TransportError as e:
            api_metrics.record("/oauth/token", "network_error")
            raise StravaTransientError("Strava could not be reached") from e
        api_metrics.record("/oauth/token", r.status_code, r.headers)
        if r.status_code == 429:
            raise StravaRateLimitError("Strava rate limit reached; try again later", seconds_until_rate_limit_reset(r.headers))
        if r.status_code >= 500:
            raise StravaTransientError("Strava is temporarily unavailable")
        if r.status_code >= 400:
            # 400/401 from the token endpoint means the code or refresh token is
            # invalid (expired, already used, or the athlete revoked access).
            logger.warning("Strava token request rejected: grant_type=%s status=%s", data.get("grant_type"), r.status_code)
            raise StravaAuthError(failure)
        return r.json()
    def exchange_code(self, code: str):
        s = get_settings()
        return self._oauth_token({"client_id":s.strava_client_id,"client_secret":s.strava_client_secret,"code":code,"grant_type":"authorization_code"}, "Unable to complete Strava authorization")
    def athlete(self, token: str):
        return self._request("GET", "/athlete", headers={"Authorization": f"Bearer {token}"})
    def clubs(self, token: str):
        try:
            page, all_items = 1, []
            while True:
                items = self._request(
                    "GET",
                    "/athlete/clubs",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"page": page, "per_page": 200},
                )
                all_items.extend(items)
                if len(items) < 200:
                    return all_items
                page += 1
        except StravaError:
            # DetailedAthlete includes clubs; this is an official fallback for
            # applications whose access to the clubs route is restricted.
            profile = self.athlete(token)
            return profile.get("clubs", [])
    def activities(self, token: str, after: datetime, *, max_pages: int = 25):
        """List summary activities after ``after`` using 200-item pages.

        ``max_pages`` bounds a single import (25 x 200 = 5000 activities) so a
        malformed response can never turn into an unbounded loop of requests.
        """
        page, all_items = 1, []
        while True:
            items = self._request("GET", "/athlete/activities", headers={"Authorization":f"Bearer {token}"}, params={"after":int(after.timestamp()),"page":page,"per_page":200})
            all_items.extend(items)
            if len(items) < 200: return all_items
            if page >= max_pages:
                logger.warning("Activity import stopped at the page limit: pages=%s", max_pages)
                return all_items
            page += 1
    def activity(self, token: str, activity_id: int):
        return self._request("GET", f"/activities/{activity_id}", headers={"Authorization": f"Bearer {token}"})
    def refresh(self, refresh_token: str):
        s=get_settings()
        return self._oauth_token({"client_id":s.strava_client_id,"client_secret":s.strava_client_secret,"refresh_token":refresh_token,"grant_type":"refresh_token"}, "Unable to refresh Strava access")
    def deauthorize(self, token: str):
        # The revocation endpoint lives under /oauth, not under /api/v3.
        return self._request("POST", "/oauth/deauthorize", url=f"{self.oauth_url}/deauthorize", data={"access_token": token})


def mark_reauthorization_required(db: Session, athlete: Athlete, reason: str) -> None:
    """Stop using an athlete's credentials after Strava definitively rejected them.

    The athlete is hidden from the team views and skipped by every Strava call
    until they connect again through OAuth. Local data is kept (it is deleted
    when Strava sends the deauthorization event or the athlete deletes it).
    """
    athlete.auth_status = "reauth_required"
    athlete.auth_error = reason[:60]
    athlete.auth_error_at = datetime.now(UTC)
    athlete.is_active = False
    db.commit()
    logger.warning("athlete_id=%s requires Strava re-authorization reason=%s", athlete.id, reason)


def get_valid_access_token(db: Session, athlete: Athlete, client: StravaClient, *, force_refresh: bool = False) -> str:
    """Return a usable access token, refreshing it when it expires within 5 minutes.

    Raises StravaAuthError when the refresh token is rejected. In that case the
    athlete is flagged as ``reauth_required`` so no caller keeps retrying with
    invalid credentials. Transient failures (timeouts, 5xx, 429) propagate as
    StravaTransientError and leave the athlete untouched.
    """
    if athlete.auth_status == "reauth_required":
        raise StravaAuthError("Athlete must reconnect Strava")
    crypto = Crypto()
    if not force_refresh and athlete.token_expires_at and _aware(athlete.token_expires_at) > datetime.now(UTC) + timedelta(minutes=5):
        return crypto.decrypt(athlete.access_token_encrypted)
    try:
        payload=client.refresh(crypto.decrypt(athlete.refresh_token_encrypted))
    except StravaAuthError:
        mark_reauthorization_required(db, athlete, "refresh_token_rejected")
        raise
    athlete.access_token_encrypted=crypto.encrypt(payload["access_token"]); athlete.refresh_token_encrypted=crypto.encrypt(payload["refresh_token"]); athlete.token_expires_at=datetime.fromtimestamp(payload["expires_at"], UTC)
    if payload.get("scope"): athlete.authorized_scopes=",".join(sorted(parse_scopes(payload["scope"])))
    db.commit()
    return payload["access_token"]


def call_with_token(db: Session, athlete: Athlete, client: StravaClient, fn):
    """Run ``fn(token)``; on a 401 refresh once and retry before giving up.

    A single 401 is not treated as a disconnection: the token may simply have
    been invalidated early. Only a rejected refresh marks the athlete.
    """
    token = get_valid_access_token(db, athlete, client)
    try:
        return fn(token)
    except StravaAuthError:
        token = get_valid_access_token(db, athlete, client, force_refresh=True)
        try:
            return fn(token)
        except StravaAuthError:
            mark_reauthorization_required(db, athlete, "access_token_rejected")
            raise


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
