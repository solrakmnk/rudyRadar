from __future__ import annotations
from datetime import UTC, datetime, timedelta
import httpx
import logging
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

class StravaError(RuntimeError): pass


def is_club_member(clubs: list[dict], club_id: int | None = None) -> bool:
    return any(int(club.get("id", 0)) == (club_id or get_settings().strava_club_id) for club in clubs)

class StravaClient:
    base_url = "https://www.strava.com/api/v3"
    oauth_url = "https://www.strava.com/oauth"
    def __init__(self, client: httpx.Client | None = None): self.client = client or httpx.Client(timeout=15, follow_redirects=True)
    def authorization_url(self, state: str, *, include_private: bool = False) -> str:
        s = get_settings()
        scope = STRAVA_PRIVATE_SCOPE if include_private else STRAVA_VISIBLE_SCOPE
        return str(httpx.URL(f"{self.oauth_url}/authorize", params={"client_id": s.strava_client_id, "redirect_uri": s.strava_redirect_uri, "response_type": "code", "approval_prompt": "force", "scope": scope, "state": state}))
    def _request(self, method: str, path: str, **kwargs):
        try: r = self.client.request(method, f"{self.base_url}{path}", **kwargs)
        except httpx.TimeoutException as e: raise StravaError("Strava did not respond in time") from e
        if r.status_code == 429: raise StravaError("Strava rate limit reached; try again later")
        if r.status_code >= 400:
            try:
                body = r.json()
                reason = body.get("message") if isinstance(body, dict) else None
            except ValueError:
                reason = None
            logger.warning("Strava request failed: method=%s path=%s status=%s reason=%s", method, path, r.status_code, reason or "unavailable")
            if r.status_code == 403:
                raise StravaError("Strava rechazó el acceso a los clubes. Revisa el acceso de la aplicación en Strava.")
            raise StravaError("Strava request failed")
        return r.json()
    def exchange_code(self, code: str):
        s = get_settings()
        r = self.client.post(f"{self.oauth_url}/token", data={"client_id":s.strava_client_id,"client_secret":s.strava_client_secret,"code":code,"grant_type":"authorization_code"})
        if r.status_code >= 400: raise StravaError("Unable to complete Strava authorization")
        return r.json()
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
    def activities(self, token: str, after: datetime):
        page, all_items = 1, []
        while True:
            items = self._request("GET", "/athlete/activities", headers={"Authorization":f"Bearer {token}"}, params={"after":int(after.timestamp()),"page":page,"per_page":200})
            all_items.extend(items)
            if len(items) < 200: return all_items
            page += 1
    def activity(self, token: str, activity_id: int):
        return self._request("GET", f"/activities/{activity_id}", headers={"Authorization": f"Bearer {token}"})
    def refresh(self, refresh_token: str):
        s=get_settings(); r=self.client.post(f"{self.oauth_url}/token", data={"client_id":s.strava_client_id,"client_secret":s.strava_client_secret,"refresh_token":refresh_token,"grant_type":"refresh_token"})
        if r.status_code >= 400: raise StravaError("Unable to refresh Strava access")
        return r.json()
    def deauthorize(self, token: str): self._request("POST", "/oauth/deauthorize", data={"access_token":token})

def get_valid_access_token(db: Session, athlete: Athlete, client: StravaClient) -> str:
    crypto = Crypto()
    if athlete.token_expires_at and athlete.token_expires_at > datetime.now(UTC) + timedelta(minutes=5): return crypto.decrypt(athlete.access_token_encrypted)
    payload=client.refresh(crypto.decrypt(athlete.refresh_token_encrypted))
    athlete.access_token_encrypted=crypto.encrypt(payload["access_token"]); athlete.refresh_token_encrypted=crypto.encrypt(payload["refresh_token"]); athlete.token_expires_at=datetime.fromtimestamp(payload["expires_at"], UTC)
    if payload.get("scope"): athlete.authorized_scopes=",".join(sorted(parse_scopes(payload["scope"])))
    db.commit()
    return payload["access_token"]
