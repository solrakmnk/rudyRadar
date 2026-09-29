from __future__ import annotations
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo
import httpx
import logging
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.config import get_settings
from app.models import Activity, Athlete

logger = logging.getLogger(__name__)

def normalize_sport(value: str | None) -> str | None:
    s = value or ""
    if s == "Swim": return "swim"
    if s in {"Ride", "MountainBikeRide", "GravelRide"}: return "bike"
    if s in {"Run", "TrailRun"}: return "run"
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

class StravaClient:
    base_url = "https://www.strava.com/api/v3"
    oauth_url = "https://www.strava.com/oauth"
    def __init__(self, client: httpx.Client | None = None): self.client = client or httpx.Client(timeout=15, follow_redirects=True)
    def authorization_url(self, state: str) -> str:
        s = get_settings()
        return str(httpx.URL(f"{self.oauth_url}/authorize", params={"client_id": s.strava_client_id, "redirect_uri": s.strava_redirect_uri, "response_type": "code", "approval_prompt": "auto", "scope": "read,profile:read_all,activity:read", "state": state}))
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
            return self._request("GET", "/athlete/clubs", headers={"Authorization":f"Bearer {token}"})
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
    athlete.access_token_encrypted=crypto.encrypt(payload["access_token"]); athlete.refresh_token_encrypted=crypto.encrypt(payload["refresh_token"]); athlete.token_expires_at=datetime.fromtimestamp(payload["expires_at"], UTC); db.commit()
    return payload["access_token"]

def upsert_activity(db: Session, athlete: Athlete, item: dict) -> Activity:
    activity = db.scalar(select(Activity).where(Activity.strava_activity_id == item["id"]))
    if not activity: activity=Activity(athlete=athlete, strava_activity_id=item["id"]); db.add(activity)
    activity.name=item.get("name", "Actividad"); activity.sport_type=item.get("sport_type", item.get("type", "")); activity.normalized_sport=normalize_sport(activity.sport_type)
    activity.start_date=datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")); activity.start_date_local=datetime.fromisoformat(item["start_date_local"].replace("Z", "+00:00")) if item.get("start_date_local") else None
    activity.timezone=item.get("timezone"); activity.distance_m=item.get("distance",0); activity.moving_time_s=item.get("moving_time",0); activity.elapsed_time_s=item.get("elapsed_time",0); activity.total_elevation_gain_m=item.get("total_elevation_gain",0); activity.manual=item.get("manual",False); activity.trainer=item.get("trainer",False); activity.commute=item.get("commute",False)
    return activity

def sync_activities(db: Session, athlete: Athlete, client: StravaClient) -> int:
    token=get_valid_access_token(db, athlete, client); items=client.activities(token, datetime.now(UTC)-timedelta(days=365)); count=0
    for item in items: upsert_activity(db, athlete, item); count += 1
    athlete.last_sync_at=datetime.now(UTC); db.commit(); return count

def sync_all_active_athletes(db: Session) -> dict[str, int]:
    client = StravaClient(); result = {"athletes": 0, "activities": 0, "failed": 0}
    for athlete in db.scalars(select(Athlete).where(Athlete.is_active.is_(True), Athlete.is_club_member.is_(True))):
        try:
            result["activities"] += sync_activities(db, athlete, client); result["athletes"] += 1
        except StravaError:
            db.rollback(); result["failed"] += 1
            logger.exception("sync failed for internal athlete_id=%s", athlete.id)
    return result

def athlete_period_stats(db: Session, athlete_id: int, kind: str, now: datetime | None = None):
    now=now or datetime.now(UTC); start,end=period_bounds(kind,now,get_settings().app_timezone)
    acts=db.scalars(select(Activity).where(Activity.athlete_id==athlete_id,Activity.start_date>=start,Activity.start_date<end)).all()
    return {"distance_m":sum(a.distance_m for a in acts),"moving_time_s":sum(a.moving_time_s for a in acts),"activity_count":len(acts),"active_days":len({a.start_date.astimezone(ZoneInfo(get_settings().app_timezone)).date() for a in acts}),"elevation_m":sum(a.total_elevation_gain_m for a in acts)}

def period_bounds(kind: str, now: datetime, tz_name: str):
    local=now.astimezone(ZoneInfo(tz_name)); start=local.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "week": start -= timedelta(days=start.weekday()); end=start+timedelta(days=7)
    elif kind == "month": start=start.replace(day=1); end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)
    else: raise ValueError("Unknown period")
    return start.astimezone(UTC), end.astimezone(UTC)

def rankings(db: Session, kind: str, now: datetime | None = None):
    now=now or datetime.now(UTC); start,end=period_bounds(kind,now,get_settings().app_timezone); acts=db.scalars(select(Activity).where(Activity.start_date>=start,Activity.start_date<end,Activity.normalized_sport.is_not(None))).all(); result={s:[] for s in ("swim","bike","run")}
    totals={}
    for a in acts: totals[(a.normalized_sport,a.athlete_id)] = totals.get((a.normalized_sport,a.athlete_id),0)+a.distance_m
    names={a.id:f"{a.firstname} {a.lastname}".strip() for a in db.scalars(select(Athlete)).all()}
    for (sport,athlete_id),distance in totals.items(): result[sport].append({"name":names[athlete_id],"distance_m":distance})
    for sport in result: result[sport].sort(key=lambda x:x["distance_m"], reverse=True); result[sport]=result[sport][:3]
    return result

def monthly_comparison(db: Session, athlete_id: int, sport: str, now: datetime | None = None):
    now=now or datetime.now(UTC); current_start,current_end=period_bounds("month",now,get_settings().app_timezone); previous_end=current_start; previous_start=(current_start-timedelta(days=1)).replace(day=1)
    acts=db.scalars(select(Activity).where(Activity.athlete_id==athlete_id, Activity.normalized_sport==sport)).all()
    total=lambda start,end:sum(a.distance_m for a in acts if start<=a.start_date<end)
    previous,current=total(previous_start,previous_end),total(current_start,current_end); absolute=current-previous
    return {"previous_distance":previous,"current_distance":current,"absolute_change":absolute,"percentage_change":None if previous==0 else absolute/previous*100}
