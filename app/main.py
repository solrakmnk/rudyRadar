from __future__ import annotations
import hashlib, hmac, secrets
import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from app.config import get_settings
from app.database import get_db
from app.models import Activity, Athlete
from app.analytics import activity_highlights, athlete_discipline_stats, athlete_period_stats, period_comparison, rankings, team_group_stats, team_highlights, team_leaderboard, team_overview, team_sport_highlights
from app.services import Crypto, StravaClient, StravaError, get_valid_access_token, is_club_member
from app.sync import sync_activities, upsert_activity
from app.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, preferred_locale, translate

settings=get_settings(); app=FastAPI(title="Radar Rudo"); app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=settings.app_base_url.startswith("https://"), same_site="lax"); app.mount("/static",StaticFiles(directory="app/static"),name="static")
def template_context(request: Request):
    locale = preferred_locale(request.query_params.get("lang"), request.session)
    request.session["locale"] = locale
    return {"locale": locale, "t": lambda key, **values: translate(locale, key, **values)}
templates=Jinja2Templates(directory="app/templates", context_processors=[template_context])
def mexico_time(value: datetime) -> str:
    return value.astimezone(ZoneInfo(settings.app_timezone)).strftime("%d/%m · %H:%M")
templates.env.filters["mexico_time"] = mexico_time
def duration(value: int | float) -> str:
    minutes = round(value / 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"
templates.env.filters["duration"] = duration
logger=logging.getLogger(__name__)

@app.get("/health")
def health(): return {"status":"ok"}
@app.get("/",response_class=HTMLResponse)
def index(request: Request): return templates.TemplateResponse(request,"index.html")
@app.get("/language/{locale}")
def language(request: Request, locale: str, next: str = "/"):
    request.session["locale"] = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    return RedirectResponse(next if next.startswith("/") and not next.startswith("//") else "/", status_code=303)
@app.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request): return templates.TemplateResponse(request, "privacy.html")
@app.post("/privacy/delete")
def delete_my_data(request: Request, db: Session = Depends(get_db)):
    athlete_id = request.session.get("athlete_id")
    athlete = db.get(Athlete, athlete_id) if athlete_id else None
    if athlete:
        try:
            StravaClient().deauthorize(Crypto().decrypt(athlete.access_token_encrypted))
        except Exception:
            logger.warning("Could not revoke Strava authorization for athlete_id=%s", athlete.id)
        db.delete(athlete); db.commit()
    request.session.clear()
    return RedirectResponse("/?deleted=1", status_code=303)
@app.get("/auth/strava")
def auth(request:Request):
    state=secrets.token_urlsafe(32); request.session["oauth_state"]=state; return RedirectResponse(StravaClient().authorization_url(state))
@app.get("/auth/strava/callback",response_class=HTMLResponse)
def callback(request:Request, code:str|None=None, state:str|None=None, error:str|None=None, db:Session=Depends(get_db)):
    expected=request.session.pop("oauth_state",None)
    if error: return templates.TemplateResponse(request,"error.html",{"message":"La autorización fue cancelada."},status_code=400)
    if not expected or not state or not hmac.compare_digest(expected,state): return templates.TemplateResponse(request,"error.html",{"message":"La conexión expiró. Inténtalo nuevamente."},status_code=400)
    try:
        client=StravaClient(); payload=client.exchange_code(code or ""); token=payload["access_token"]; clubs=client.clubs(token)
    except StravaError as e: return templates.TemplateResponse(request,"error.html",{"message":str(e)},status_code=502)
    if not is_club_member(clubs): return templates.TemplateResponse(request,"not_member.html")
    source=payload["athlete"]; athlete=db.scalar(select(Athlete).where(Athlete.strava_athlete_id==source["id"]))
    if not athlete: athlete=Athlete(strava_athlete_id=source["id"],firstname=source.get("firstname","Rudy"),lastname=source.get("lastname","")); db.add(athlete)
    crypto=Crypto(); athlete.profile_url=source.get("profile"); athlete.access_token_encrypted=crypto.encrypt(token); athlete.refresh_token_encrypted=crypto.encrypt(payload["refresh_token"]); athlete.token_expires_at=datetime.fromtimestamp(payload["expires_at"],UTC); athlete.is_active=True; athlete.is_club_member=True; db.commit()
    count=sync_activities(db,athlete,StravaClient()) if settings.strava_sync_enabled else 0
    request.session["athlete_id"] = athlete.id; request.session["sync_count"] = count
    return RedirectResponse("/radar", status_code=303)
@app.get("/radar",response_class=HTMLResponse)
def radar(request: Request, period: str="week", db: Session=Depends(get_db)):
    athlete_id=request.session.get("athlete_id")
    athlete=db.get(Athlete, athlete_id) if athlete_id else None
    if not athlete or not athlete.is_active or not athlete.is_club_member: return RedirectResponse("/",status_code=303)
    if period not in {"week","last_week","month","last_month","two_months_ago"}: period="week"
    count=request.session.pop("sync_count",None)
    return templates.TemplateResponse(request,"radar.html",{"athlete":athlete,"period":period,"stats":athlete_period_stats(db,athlete.id,period),"discipline_stats":athlete_discipline_stats(db,athlete.id,period),"rankings":rankings(db,period),"leaderboard":team_leaderboard(db,period),"comparison":period_comparison(db,athlete.id,period),"highlights":activity_highlights(db,athlete.id,kind=period),"team_highlights":team_highlights(db,kind=period),"team_overview":team_overview(db,period),"team_groups":team_group_stats(db,period),"sport_highlights":team_sport_highlights(db,kind=period),"sync_count":count})
def admin_ok(request:Request):
    supplied=request.headers.get("x-admin-secret",""); auth=request.headers.get("authorization","")
    if auth.startswith("Bearer "): supplied=auth.removeprefix("Bearer ")
    if not hmac.compare_digest(supplied,settings.admin_secret): raise HTTPException(401,headers={"WWW-Authenticate":"Bearer"})
@app.get("/admin",response_class=HTMLResponse,dependencies=[Depends(admin_ok)])
def admin(request:Request,period:str="week",db:Session=Depends(get_db)):
    athletes=db.scalars(select(Athlete).order_by(Athlete.firstname)).all(); active=sum(a.is_active for a in athletes); activity_count=db.scalar(select(func.count(Activity.id))) or 0; total=db.scalar(select(func.coalesce(func.sum(Activity.distance_m),0))) or 0
    return templates.TemplateResponse(request,"admin.html",{"athletes":athletes,"rankings":rankings(db,period),"period":period,"active":active,"activity_count":activity_count,"distance_m":total})
@app.get("/admin/report",response_class=PlainTextResponse,dependencies=[Depends(admin_ok)])
def report(period:str="week",db:Session=Depends(get_db)):
    r=rankings(db,period); medals=["🥇","🥈","🥉"]; labels={"swim":"🏊 NATACIÓN","bike":"🚴 BICI","run":"🏃 CARRERA"}; lines=["👀 RADAR RUDO",f"Rudy encontró las historias de este {('mes' if period=='month' else 'semana')}..."]
    for sport in ("swim","bike","run"):
        lines.extend(["",labels[sport]])
        if r[sport]: lines.extend(f"{medals[i]} {x['name']} — {x['distance_m']/1000:.1f} km" for i,x in enumerate(r[sport]))
        else: lines.append("Sin actividades todavía")
    return "\n".join(lines)+"\n\n🔴🔵"
@app.get("/webhooks/strava")
def verify_webhook(hub_mode:str|None=None,hub_verify_token:str|None=None,hub_challenge:str|None=None):
    if hub_mode=="subscribe" and settings.webhook_verify_token and hmac.compare_digest(hub_verify_token or "",settings.webhook_verify_token): return {"hub.challenge":hub_challenge}
    raise HTTPException(403)
def process_webhook(payload: dict):
    db=next(get_db())
    try:
        athlete=db.scalar(select(Athlete).where(Athlete.strava_athlete_id==payload.get("owner_id"),Athlete.is_active.is_(True)))
        if not athlete: return
        if payload.get("object_type") == "athlete" and payload.get("updates", {}).get("authorized") == "false":
            db.delete(athlete); db.commit(); return
        if payload.get("object_type") != "activity": return
        activity_id=payload.get("object_id")
        if payload.get("aspect_type")=="delete":
            activity=db.scalar(select(Activity).where(Activity.strava_activity_id==activity_id))
            if activity: db.delete(activity); db.commit()
            return
        token=get_valid_access_token(db,athlete,StravaClient()); upsert_activity(db,athlete,StravaClient().activity(token,activity_id)); db.commit()
    except Exception:
        db.rollback(); logger.exception("Strava webhook processing failed")
    finally: db.close()
@app.post("/webhooks/strava",status_code=200)
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    payload=await request.json(); background_tasks.add_task(process_webhook,payload); return {"status":"accepted"}
