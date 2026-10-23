from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func

from . import llm
from .collect import canonical, fingerprint, read_document
from .case_context import build_context, client_id, company_choices, dataset_report, status, value
from .db import Admin, Audit, Base, DB, Item, Job, Member, Session, Usage, User, Workspace, audit, engine, get_db, items, now, pack, record, uid
from .discovery import saved_discovery
from .mail import enqueue
from .pipeline import WRITE_ROLES, create_job, start_worker, stop_worker
from .research import relevance, retrieve_bank, seed_research
from .security import access, current_user, encrypt, hash_token, hasher, is_guest, issue_session, password_ok, rate_limit, require_account, safe_url


class Credentials(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(default="", max_length=100)
    invite_token: str = Field(default="", max_length=150)


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class URLIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=8, max_length=2000)
    type: str = "rss"
    kind: str = "news"
    enabled: bool = True
    respect_robots: bool = True
    limit: int = Field(default=12, ge=1, le=30)


class MaterialIn(BaseModel):
    title: str = Field(min_length=3, max_length=400)
    text: str = Field(min_length=60, max_length=200000)
    url: str = Field(default="", max_length=2000)
    kind: str = "news"
    published_at: str | None = None


class InviteIn(BaseModel):
    email: str = Field(max_length=254)
    role: str = "viewer"


def valid_email(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise HTTPException(422, "Enter a valid email address.")
    return value


def public_user(u):
    return {"id": u.id, "email": u.email, "name": u.name, "verified": u.verified, "is_guest": is_guest(u), "preferences": u.preferences}


def request_locale(request):
    return "ru" if request.headers.get("accept-language", "en").lower().startswith("ru") else "en"


def public_settings(settings):
    s = dict(settings)
    s.pop("profile_draft", None)
    c = s.get("model", {})
    if c:
        s["model"] = {k: v for k, v in c.items() if k != "key_encrypted"}
        s["model"]["key_configured"] = bool(c.get("key_encrypted")) if c.get("mode") == "custom" else bool(os.getenv("ALFA_API_KEY"))
    return s


def ws_public(w, member):
    return {"id": w.id, "name": w.name, "profile": w.profile, "draft_profile": w.settings.get("profile_draft"), "settings": public_settings(w.settings), "onboarded": w.onboarded, "demo": w.demo, "role": member.role, "decision_role": member.decision_role, "created_at": w.created_at}


def job_public(j):
    return {**{k: getattr(j, k) for k in ["id", "workspace_id", "kind", "status", "progress", "result", "steps", "error", "created_at", "started_at", "finished_at"]}, "input": {k:v for k,v in (j.input or {}).items() if k in {"period", "decision_role", "url", "scheduled", "end"}}}


def base_url(request):
    host = request.headers.get("host", "").split(":")[0]
    if host == "analytics.subschool.ru":
        return "https://analytics.subschool.ru"
    return os.getenv("PUBLIC_URL", "http://localhost:5173").rstrip("/")


def token_record(db, user, kind, invite_token=""):
    token = secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=24 if kind == "verification" else 1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    record(db, "auth", kind, {"user_id": user.id, "expires_at": expiry, "used": False, "invite_token": invite_token}, key=hash_token(token))
    return token


@asynccontextmanager
async def lifespan(app):
    if os.getenv("APP_ENV") == "production" and (len(os.getenv("APP_SECRET", "")) < 32 or os.getenv("COOKIE_SECURE") != "true"):
        raise RuntimeError("Production requires APP_SECRET (32+ characters) and COOKIE_SECURE=true.")
    Base.metadata.create_all(engine)
    with DB() as db:
        seed_research(db)
        email, password = os.getenv("ADMIN_EMAIL"), os.getenv("ADMIN_PASSWORD")
        if email and password and not db.query(Admin).filter_by(email=email.lower()).first():
            if len(password) < 14:
                raise RuntimeError("ADMIN_PASSWORD must contain at least 14 characters.")
            db.add(Admin(email=email.lower(), password=hasher.hash(password)))
            db.commit()
    if os.getenv("WORKER_ENABLED", "true") == "true":
        start_worker()
    yield
    stop_worker()


app = FastAPI(title="SignalDesk API", version="1.2.0", description="Evidence-grounded business news intelligence. Session authentication; every workspace operation verifies membership and role.", lifespan=lifespan)


@app.middleware("http")
async def safety_headers(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        allowed = set(os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","))
        if origin and origin not in allowed:
            return JSONResponse({"detail": "This request origin is not permitted."}, status_code=403)
        try:
            if int(request.headers.get("content-length", "0")) > 12 * 1024 * 1024:
                return JSONResponse({"detail": "Upload limit is 12 MB."}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Invalid request size."}, status_code=400)
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin", "X-Frame-Options": "SAMEORIGIN", "X-Robots-Tag": "noindex, nofollow", "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    if os.getenv("APP_ENV") == "production":
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=422)


@app.exception_handler(llm.ModelUnavailable)
async def model_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.get("/api/health", tags=["System"])
def health(db=Depends(get_db)):
    db.execute(__import__("sqlalchemy").text("SELECT 1"))
    return {"status": "ok", "version": "1.2.0", "release": os.getenv("RELEASE_ID", "development"), "time": now()}


@app.get("/api/config", tags=["System"])
def client_config():
    return {"approved_models": llm.APPROVED_MODELS, "email_enabled": os.getenv("EMAIL_DELIVERY") == "sendpulse", "model_configured": bool(os.getenv("ALFA_API_KEY"))}


@app.get("/api/showcase/summary", tags=["Demonstration"])
def showcase_summary(db=Depends(get_db)):
    result = []
    for w in db.query(Workspace).filter_by(onboarded=True, demo=False).all():
        if not w.settings.get("showcase"):
            continue
        events = [pack(e) for e in items(db, w.id, "event") if not e.payload.get("is_demo") and e.payload.get("decision_role", "ceo") == "ceo" and e.payload.get("profile_version", 1) == w.profile.get("version", 1)]
        events.sort(key=lambda e: e.get("relevance", 0), reverse=True)
        result.append({"name": w.name, "variant": w.settings.get("showcase_variant"), "industry": w.profile.get("industry"), "regions": w.profile.get("regions", []), "event_count": len(events), "risk_count": sum(e.get("sentiment") == "risk" for e in events), "events": [{k: e.get(k) for k in ["en", "ru", "relevance", "sentiment", "published_at"]} for e in events[:2]], "dates": [e.get("published_at") or e["created_at"] for e in events], "updated_at": w.settings.get("last_run")})
    return result


@app.post("/api/auth/register", tags=["Account"])
def register(data: Credentials, request: Request, response: Response, db=Depends(get_db)):
    rate_limit(request)
    email = valid_email(data.email)
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(409, "An account with this email already exists. Sign in or reset your password.")
    lang = request_locale(request)
    user = User(email=email, name=data.name.strip() or email.split("@")[0], password=hasher.hash(data.password), preferences={"locale": lang, "email_alerts": False, "email_briefs": False})
    db.add(user);db.flush()
    issue_session(db, response, user.id)
    invitation = db.query(Item).filter_by(kind="invite", key=hash_token(data.invite_token)).first() if data.invite_token else None
    resume_invite = data.invite_token if invitation and invitation.payload["email"] == email and not invitation.payload.get("accepted") and invitation.payload["expires_at"] >= now() else ""
    token = token_record(db, user, "verification", resume_invite)
    enqueue(db, "auth", user.email, "Добро пожаловать в SignalDesk" if lang == "ru" else "Welcome to SignalDesk", "<p>Подтвердите почту, чтобы открыть рабочее пространство, настроить компанию и получать важные события и сводки.</p>" if lang == "ru" else "<p>Your next informed decision starts here. Confirm your email to unlock company onboarding, your workspace and business alerts.</p>", link=base_url(request) + "/verify?token=" + token, locale=lang)
    audit(db, user.id, "account.registered")
    db.commit()
    return public_user(user)


@app.post("/api/auth/login", tags=["Account"])
def login(data: Credentials, request: Request, response: Response, db=Depends(get_db)):
    rate_limit(request)
    user = db.query(User).filter_by(email=data.email.strip().lower()).first()
    if not user or user.disabled or not password_ok(user.password, data.password):
        raise HTTPException(401, "Email or password is incorrect.")
    issue_session(db, response, user.id)
    audit(db, user.id, "account.signed_in")
    db.commit()
    return public_user(user)


@app.post("/api/auth/logout", tags=["Account"])
def logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get("sd_session", "")
    row = db.get(Session, hash_token(token))
    if row:
        db.delete(row);db.commit()
    response.delete_cookie("sd_session", path="/")
    return {"ok": True}


@app.get("/api/auth/me", tags=["Account"])
def me(request: Request, db=Depends(get_db)):
    return public_user(current_user(request, db, allow_unverified=True))


@app.patch("/api/auth/me", tags=["Account"])
def update_me(request: Request, data: dict = Body(...), db=Depends(get_db)):
    user = current_user(request, db)
    if "name" in data:
        user.name = str(data["name"])[:100]
    prefs = {k: v for k, v in data.get("preferences", {}).items() if k in {"locale", "email_alerts", "email_briefs", "theme"}}
    if prefs.get("locale") not in {None, "en", "ru"}:
        raise HTTPException(422, "Unsupported language.")
    user.preferences = {**user.preferences, **prefs}
    db.commit()
    return public_user(user)


@app.post("/api/auth/verify", tags=["Account"])
def verify_email(request: Request, response: Response, data: dict = Body(...), db=Depends(get_db)):
    rate_limit(request, "verify", 20)
    row = db.query(Item).filter_by(workspace_id="auth", kind="verification", key=hash_token(str(data.get("token", "")))).first()
    if not row or row.payload.get("used") or row.payload["expires_at"] < now():
        raise HTTPException(400, "This verification link has expired or has already been used.")
    user = db.get(User, row.payload["user_id"])
    user.verified = True
    row.payload = {**row.payload, "used": True}
    issue_session(db, response, user.id)
    db.commit()
    return {"ok": True, "user": public_user(user), "invite_token": row.payload.get("invite_token", "")}


@app.post("/api/auth/resend-verification", tags=["Account"])
def resend(request: Request, db=Depends(get_db)):
    user = current_user(request, db, allow_unverified=True)
    require_account(user)
    rate_limit(request, "resend", 3, 3600)
    if not user.verified:
        prior = next((r for r in items(db, "auth", "verification") if r.payload.get("user_id") == user.id and r.payload.get("invite_token")), None)
        token = token_record(db, user, "verification", prior.payload["invite_token"] if prior else "")
        lang = user.preferences.get("locale", "en")
        enqueue(db, "auth", user.email, "Подтвердите почту SignalDesk" if lang == "ru" else "Confirm your SignalDesk email", "<p>Подтвердите почту, чтобы получать важные события и сводки.</p>" if lang == "ru" else "<p>Confirm your email to unlock your workspace, business alerts and brief delivery.</p>", link=base_url(request) + "/verify?token=" + token, locale=lang)
        db.commit()
    return {"ok": True, "delivery_enabled": os.getenv("EMAIL_DELIVERY") == "sendpulse"}


@app.post("/api/auth/reset-request", tags=["Account"])
def request_reset(request: Request, data: dict = Body(...), db=Depends(get_db)):
    rate_limit(request, "reset", 4, 3600)
    user = db.query(User).filter_by(email=str(data.get("email", "")).strip().lower()).first()
    if user:
        token = token_record(db, user, "reset")
        lang = user.preferences.get("locale", "en")
        enqueue(db, "auth", user.email, "Восстановление пароля SignalDesk" if lang == "ru" else "Reset your SignalDesk password", "<p>Перейдите по ссылке ниже, чтобы задать новый пароль. Ссылка действует один час.</p>" if lang == "ru" else "<p>Use the link below to choose a new password. This link expires in one hour.</p>", link=base_url(request) + "/reset?token=" + token, locale=lang)
        db.commit()
    return {"ok": True}


@app.post("/api/auth/reset", tags=["Account"])
def reset(request: Request, response: Response, data: dict = Body(...), db=Depends(get_db)):
    rate_limit(request, "reset-confirm", 10)
    password = str(data.get("password", ""))
    if len(password) < 10 or len(password) > 200:
        raise HTTPException(422, "Use a password with 10–200 characters.")
    row = db.query(Item).filter_by(workspace_id="auth", kind="reset", key=hash_token(str(data.get("token", "")))).first()
    if not row or row.payload.get("used") or row.payload["expires_at"] < now():
        raise HTTPException(400, "This password reset link is invalid or expired.")
    user = db.get(User, row.payload["user_id"])
    user.password = hasher.hash(password)
    row.payload = {**row.payload, "used": True}
    db.query(Session).filter_by(user_id=user.id, realm="product").delete()
    issue_session(db, response, user.id)
    audit(db, user.id, "account.password_reset")
    db.commit()
    return public_user(user)


@app.post("/api/demo", tags=["Demonstration"])
def demo(request: Request, response: Response, data: dict = Body(default={}), db=Depends(get_db)):
    rate_limit(request, "demo", 8, 3600)
    published = [w for w in db.query(Workspace).filter_by(onboarded=True, demo=False).all() if w.settings.get("showcase")]
    if not published:
        raise HTTPException(503, "The live tour is being prepared. Please create an account to analyse your company.")
    user = User(email=f"demo-{uid()}@example.invalid", name="Guest visitor", password=hasher.hash(secrets.token_urlsafe(30)), preferences={"account_kind": "guest", "locale": request_locale(request), "email_alerts": False, "email_briefs": False})
    db.add(user);db.flush()
    for w in published:
        db.add(Member(workspace_id=w.id, user_id=user.id, role="viewer", decision_role="ceo"))
    ws = next((w for w in published if w.settings.get("showcase_variant") == data.get("variant", "industrial")), published[0])
    issue_session(db, response, user.id, "guest")
    db.commit()
    return {"user": public_user(user), "workspace_id": ws.id}


@app.get("/api/workspaces", tags=["Workspaces"])
def workspace_list(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    if is_guest(user):
        published = [w for w in db.query(Workspace).filter_by(onboarded=True, demo=False).all() if w.settings.get("showcase")]
        result = []
        for w in published:
            member = db.query(Member).filter_by(user_id=user.id, workspace_id=w.id).first()
            if not member:
                member = Member(user_id=user.id, workspace_id=w.id, role="viewer", decision_role="ceo")
                db.add(member);db.flush()
            result.append(ws_public(w, member))
        db.commit()
        return result
    return [ws_public(db.get(Workspace, m.workspace_id), m) for m in db.query(Member).filter_by(user_id=user.id).all() if db.get(Workspace, m.workspace_id)]


@app.post("/api/workspaces", tags=["Workspaces"])
def workspace_create(data: WorkspaceIn, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    require_account(user)
    if db.query(Member).filter_by(user_id=user.id, role="owner").count() >= 10:
        raise HTTPException(422, "You can own up to 10 workspaces.")
    ws = Workspace(name=data.name.strip(), settings={"auto_monitor": True, "interval_minutes": 360, "alert_threshold": 80, "min_relevance": 20, "lookback_days": 30, "scheduled_briefs": ["day", "week", "month"]})
    db.add(ws);db.flush()
    member = Member(user_id=user.id, workspace_id=ws.id, role="owner")
    db.add(member);db.flush()
    audit(db, user.id, "workspace.created", ws.id)
    db.commit()
    return ws_public(ws, member)


@app.get("/api/workspaces/{wid}", tags=["Workspaces"])
def workspace_get(wid: str, request: Request, db=Depends(get_db)):
    _, ws, member = access(request, db, wid)
    return ws_public(ws, member)


@app.put("/api/workspaces/{wid}/profile", tags=["Onboarding"])
def profile_update(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid, {"owner", "admin", "analyst"})
    allowed = {"name", "website", "industry", "description", "activities", "customers", "regions", "competitors", "counterparties", "scale", "revenue", "market_position", "exposures", "priorities", "keywords", "unknowns", "evidence", "reviewed"}
    for field in ["activities", "customers", "regions", "competitors", "counterparties", "exposures", "priorities", "keywords", "unknowns"]:
        if field in data and (not isinstance(data[field], list) or any(not isinstance(x, str) for x in data[field])):
            raise HTTPException(422, f"{field} must be a list of text values.")
    for field in ["name", "website", "industry"]:
        if field in data and not isinstance(data[field], str):
            raise HTTPException(422, f"{field} must be text.")
    profile = {**(ws.settings.get("profile_draft") or ws.profile), **{k: v for k, v in data.items() if k in allowed}}
    if "regions" in data:
        profile["regions_origin"] = "user_confirmed"
    if len(json.dumps(profile)) > 35000:
        raise HTTPException(422, "Company profile is too large.")
    if profile.get("website"):
        safe_url(profile["website"])
    if profile.get("regions"):
        profile["unknowns"] = [x for x in profile.get("unknowns", []) if not re.search(r"geograph|primary market regions|географ|регион", x, re.I)]
    if not data.get("reviewed") and ws.onboarded:
        ws.settings = {**ws.settings, "profile_draft": {**profile, "reviewed": False, "status": "draft"}}
        audit(db, user.id, "company.profile_draft_saved", wid)
        db.commit()
        return ws_public(ws, member)
    if data.get("reviewed"):
        # Imported anonymised case clients have no established public identity. This
        # server-owned provenance cannot be set by an ordinary profile request.
        imported_case = bool(profile.get("synthetic_company_id") and profile.get("dataset_features"))
        if not profile.get("name") or not profile.get("industry") or not profile.get("exposures") or not (profile.get("website") or imported_case):
            raise HTTPException(422, "Add a company website, name, industry and at least one business exposure before confirming.")
        ws.onboarded = True
        profile["status"] = "confirmed"
        profile["reviewed_at"] = now()
        profile["version"] = int(ws.profile.get("version", 0)) + 1
        ws.settings = {k: v for k, v in ws.settings.items() if k != "profile_draft"}
    ws.profile = profile
    ws.name = str(profile.get("name") or ws.name)[:150]
    if "decision_role" in data:
        if data["decision_role"] not in {"ceo", "cfo", "owner", "treasury", "accountant", "strategy"}:
            raise HTTPException(422, "Unsupported decision role.")
        member.decision_role = data["decision_role"]
    if "keywords" in data:
        ws.settings = {**ws.settings, "keywords": [str(x)[:100] for x in data["keywords"][:30]]}
    audit(db, user.id, "company.profile_updated", wid, version=profile.get("version"), reviewed=bool(data.get("reviewed")))
    db.commit()
    return ws_public(ws, member)


@app.post("/api/workspaces/{wid}/profile/discover", tags=["Onboarding"])
def discover(wid: str, data: URLIn, request: Request, db=Depends(get_db)):
    user, ws, _ = access(request, db, wid, WRITE_ROLES)
    rate_limit(request, "website", 12, 3600)
    safe_url(data.url)
    return job_public(create_job(db, wid, user.id, "website", {"url": data.url}))


@app.get("/api/workspaces/{wid}/source-suggestions", tags=["Sources"])
def source_suggestions(wid: str, request: Request, db=Depends(get_db)):
    _, ws, _ = access(request, db, wid)
    return saved_discovery(db, ws)["sources"]


@app.post("/api/workspaces/{wid}/source-discovery", tags=["Sources"])
def find_sources(wid: str, request: Request, db=Depends(get_db)):
    user, ws, _ = access(request, db, wid, WRITE_ROLES)
    rate_limit(request, "source_discovery", 8, 3600)
    profile = ws.settings.get("profile_draft") or ws.profile
    if not profile.get("industry"):
        raise HTTPException(422, "Add a company industry before searching for sources.")
    return job_public(create_job(db, wid, user.id, "sources", {}))


@app.get("/api/workspaces/{wid}/sources", tags=["Sources"])
def sources(wid: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    return [pack(s) for s in items(db, wid, "source")]


@app.post("/api/workspaces/{wid}/sources", tags=["Sources"])
def source_add(wid: str, data: SourceIn, request: Request, db=Depends(get_db)):
    user, ws, _ = access(request, db, wid, {"owner", "admin", "analyst"})
    safe_url(data.url)
    if data.kind not in {"news", "bank"} or data.type not in {"rss", "html"}:
        raise HTTPException(422, "Unsupported source type.")
    if len(items(db, wid, "source")) >= 30:
        raise HTTPException(422, "A workspace can monitor up to 30 sources.")
    matched = next((s for s in saved_discovery(db, ws)["sources"] if canonical(s["url"]) == canonical(data.url)), {})
    provenance = {k: matched[k] for k in ("publisher", "country", "target_market", "discovered_from", "search_provider", "search_query", "search_title", "verified_at", "sample_count", "latest_publication", "sample_headlines", "sample_urls", "reason") if k in matched}
    row = record(db, wid, "source", {**provenance, **data.model_dump(), "health": "not_checked"}, key=canonical(data.url))
    audit(db, user.id, "source.added", wid, source_id=row.id)
    db.commit()
    return pack(row)


@app.patch("/api/workspaces/{wid}/sources/{sid}", tags=["Sources"])
def source_edit(wid: str, sid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, _, _ = access(request, db, wid, WRITE_ROLES)
    row = db.query(Item).filter_by(id=sid, workspace_id=wid, kind="source").first()
    if not row:
        raise HTTPException(404, "Source not found.")
    p = SourceIn(**{**row.payload, **data}).model_dump()
    safe_url(p["url"])
    row.payload = {**row.payload, **p}
    audit(db, user.id, "source.updated", wid, source_id=sid)
    db.commit()
    return pack(row)


@app.delete("/api/workspaces/{wid}/sources/{sid}", tags=["Sources"])
def source_delete(wid: str, sid: str, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid, WRITE_ROLES)
    row = db.query(Item).filter_by(id=sid, workspace_id=wid, kind="source").first()
    if not row:
        raise HTTPException(404, "Source not found.")
    db.delete(row);audit(db, user.id, "source.deleted", wid, source_id=sid);db.commit()
    return {"ok": True}


@app.patch("/api/workspaces/{wid}/settings", tags=["Workspaces"])
def settings_update(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid, {"owner", "admin"})
    allowed = {"keywords", "exclude_keywords", "auto_monitor", "interval_minutes", "alert_threshold", "min_relevance", "lookback_days", "scheduled_briefs"}
    updates = {k: v for k, v in data.items() if k in allowed}
    for key in ["keywords", "exclude_keywords"]:
        if key in updates:
            if not isinstance(updates[key], list):
                raise HTTPException(422, "Monitoring keywords must be a list.")
            updates[key] = [str(x)[:100].strip() for x in updates[key][:30] if str(x).strip()]
    for key, low, high in [("interval_minutes", 30, 1440), ("alert_threshold", 0, 100), ("min_relevance", 0, 100), ("lookback_days", 1, 90)]:
        if key in updates:
            updates[key] = max(low, min(high, int(updates[key])))
    if "scheduled_briefs" in updates:
        updates["scheduled_briefs"] = [x for x in updates["scheduled_briefs"] if x in {"day", "week", "month"}]
    ws.settings = {**ws.settings, **updates}
    audit(db, user.id, "workspace.settings_updated", wid, fields=list(updates));db.commit()
    return ws_public(ws, member)


@app.post("/api/workspaces/{wid}/materials", tags=["Sources"])
def material_add(wid: str, data: MaterialIn, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid, WRITE_ROLES)
    if data.url:
        safe_url(data.url)
    if data.kind not in {"news", "bank"}:
        raise HTTPException(422, "Choose news or bank research.")
    if data.published_at:
        try:
            date = datetime.fromisoformat(data.published_at.replace("Z", "+00:00"))
            data.published_at = date.replace(tzinfo=date.tzinfo or timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except ValueError:
            raise HTTPException(422, "Use an ISO publication date.")
    kind = "bank" if data.kind == "bank" else "article"
    payload = {**data.model_dump(), "source_name": "Workspace upload", "evidence_level": "user_supplied", "uploaded_by": user.id, "user_attributed": data.kind == "bank"}
    row = record(db, wid, kind, payload, key=data.url or fingerprint(data.title + data.text[:300]))
    audit(db, user.id, "material.added", wid, material_id=row.id, kind=kind);db.commit()
    return pack(row)


@app.post("/api/workspaces/{wid}/upload", tags=["Sources"])
async def upload(wid: str, request: Request, file: UploadFile = File(...), db=Depends(get_db)):
    user, _, _ = access(request, db, wid, WRITE_ROLES)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Upload limit is 10 MB.")
    name = Path(file.filename or "document.txt").name
    if name.lower().endswith(".csv"):
        text = data.decode("utf-8-sig")
        sample = text[:5000]
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = []
        for i, row in enumerate(reader):
            if i >= 2000:
                break
            rows.append(row)
        if not rows:
            raise HTTPException(422, "This CSV has no data rows.")
        kind = "client_dataset" if "SYNTHETIC_U" in rows[0] else "payment_dataset" if {"PAYER", "BENEFICIARY"}.issubset(rows[0]) else "csv_dataset"
        row = record(db, wid, kind, {"filename": name, "rows": rows, "columns": reader.fieldnames, "row_count": len(rows), "truncated": len(rows) == 2000, "uploaded_by": user.id, "quality": dataset_report(rows) if kind == "client_dataset" else {}})
        audit(db, user.id, "dataset.uploaded", wid, kind=kind, rows=len(rows));db.commit()
        return {"id": row.id, "kind": kind, "row_count": len(rows), "columns": reader.fieldnames, "sample": rows[:8], "truncated": len(rows) == 2000}
    if not name.lower().endswith((".pdf", ".txt", ".md", ".html")):
        raise HTTPException(422, "Upload a searchable PDF, text, HTML or CSV file.")
    doc = read_document(data, file.content_type or "text/plain", name)
    return {"title": doc["title"] or name, "text": doc["text"], "filename": name}


@app.get("/api/workspaces/{wid}/datasets", tags=["Onboarding"])
def datasets(wid: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    return [{"id": r.id, "kind": r.kind, "filename": r.payload["filename"], "row_count": r.payload["row_count"], "columns": r.payload["columns"], "sample": r.payload["rows"][:20], "quality": dataset_report(r.payload["rows"]) if r.kind == "client_dataset" else {}, "companies": company_choices(r.payload["rows"]) if r.kind == "client_dataset" else []} for r in db.query(Item).filter(Item.workspace_id == wid, Item.kind.in_(["client_dataset", "payment_dataset", "csv_dataset"])).all()]


@app.get("/api/workspaces/{wid}/datasets/{did}/companies", tags=["Onboarding"])
def search_case_companies(wid: str, did: str, request: Request, q: str = "", db=Depends(get_db)):
    access(request, db, wid)
    dataset = db.query(Item).filter_by(id=did, workspace_id=wid, kind="client_dataset").first()
    if not dataset:
        raise HTTPException(404, "Dataset not found.")
    return company_choices(dataset.payload["rows"], q[:150])


@app.get("/api/workspaces/{wid}/case-sample/{kind}", tags=["Onboarding"])
def case_sample(wid: str, kind: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    if kind not in {"clients", "payments"}:
        raise HTTPException(404, "Sample not found.")
    path = Path(__file__).resolve().parents[2] / "data" / f"demo_{kind}.csv"
    if not path.exists():
        raise HTTPException(404, "Sample not found.")
    return FileResponse(path, media_type="text/csv", filename=f"case-{kind}.csv")


@app.post("/api/workspaces/{wid}/datasets/{did}/select", tags=["Onboarding"])
def select_client(wid: str, did: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid, WRITE_ROLES)
    dataset = db.query(Item).filter_by(id=did, workspace_id=wid, kind="client_dataset").first()
    matches = [r for r in dataset.payload["rows"] if client_id(r) == data.get("company_id")] if dataset else []
    if not matches:
        raise HTTPException(404, "Company ID not found in this dataset.")
    if len(matches) != 1:
        raise HTTPException(422, "This technical company ID is duplicated. Select an unambiguous client record.")
    selected = matches[0]
    if status(selected) in {"prospect", "closed"}:
        raise HTTPException(422, "The banking scenario is for active clients. This record is a prospect or closed client.")
    company_id = client_id(selected)
    same_company = ws.profile.get("synthetic_company_id") == company_id
    exposures = list(ws.profile.get("exposures", [])) if same_company else []
    for field, exposure in [("CL_PRODUCT_LOA_MARK", "Credit products / borrowing costs"), ("CL_PRODUCT_LEA_MARK", "Leasing obligations"), ("CL_PRODUCT_DEP_MARK", "Deposits / treasury liquidity"), ("FACTORING_MARK", "Factoring / receivables financing"), ("FTS_FLAG", "Cross-border trade")]:
        if str(selected.get(field, "")).lower() in {"1", "1.0", "true", "да", "y"}:
            exposures.append(exposure)
    linked = []
    for payment in items(db, wid, "payment_dataset"):
        linked += [p for p in payment.payload["rows"] if p.get("PAYER") == company_id or p.get("BENEFICIARY") == company_id]
    context, clean = build_context(selected, dataset.payload["rows"], linked)
    base = ws.profile if same_company else {"name": "Case client " + company_id, "website": "", "activities": [value(selected, "MAINOKVED_NAME")], "customers": [], "priorities": [], "keywords": [], "unknowns": ["Official company identity and website", "Operating and customer markets", "Debt terms and maturities"]}
    imported = {**base, "synthetic_company_id": company_id, "industry": value(selected, "MAINOKVED_NAME") or (ws.profile.get("industry", "") if same_company else ""), "okved": value(selected, "MAINOKVED_CODE"), "revenue": context["revenue"]["amount"] if context["revenue"]["amount"] is not None else "Unknown", "regions": ws.profile.get("regions", []) if same_company and ws.profile.get("regions_origin") == "user_confirmed" else [], "group_id": context["group"]["id"], "exposures": list(dict.fromkeys(exposures)), "dataset_features": clean, "case_context": context, "payment_connections": context["payments"]["external_links"], "reviewed": False}
    if ws.onboarded:
        ws.settings = {**ws.settings, "profile_draft": imported}
    else:
        ws.profile = imported
    audit(db, user.id, "company.dataset_selected", wid, company_id=company_id);db.commit()
    return ws_public(ws, member)


@app.get("/api/workspaces/{wid}/research", tags=["Sources"])
def research(wid: str, request: Request, q: str = "", db=Depends(get_db)):
    access(request, db, wid)
    if q:
        return retrieve_bank(db, q[:500], limit=8, wid=wid)
    return [{"id": r.id, "title": r.payload["title"], "url": r.payload.get("url", ""), "published_at": r.payload.get("published_at"), "pages": r.payload.get("pages", 1), "ocr": r.payload.get("ocr", False), "preview": r.payload.get("text", "")[:800], "origin": "case_material" if r.workspace_id == "global" else "workspace_upload"} for r in items(db, "global", "bank") + items(db, wid, "bank")]


@app.post("/api/workspaces/{wid}/analyze", tags=["Analysis"])
def analyze(wid: str, request: Request, db=Depends(get_db)):
    user, ws, member = access(request, db, wid, WRITE_ROLES)
    rate_limit(request, "analyze", 20, 3600)
    if not ws.onboarded:
        raise HTTPException(422, "Confirm the company profile first.")
    audit(db, user.id, "analysis.requested", wid);db.commit()
    return job_public(create_job(db, wid, user.id, "analyze", {"decision_role": member.decision_role}))


@app.get("/api/workspaces/{wid}/events", tags=["Analysis"])
def events(wid: str, request: Request, q: str = "", sentiment: str = "", category: str = "", days: int = 30, db=Depends(get_db)):
    user, ws, member = access(request, db, wid)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(365, days)))).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = [pack(e) for e in items(db, wid, "event") if e.payload.get("decision_role", "ceo") == member.decision_role and e.payload.get("profile_version", 1) == ws.profile.get("version", 1) and cutoff <= (e.payload.get("published_at") or e.created_at) <= now()]
    if sentiment:
        result = [e for e in result if e.get("sentiment") == sentiment]
    if category:
        result = [e for e in result if e.get("category") == category]
    if q:
        result = [e for e in result if q.lower() in json.dumps(e, ensure_ascii=False).lower()]
    hidden = {r.payload["event_id"] for r in items(db, wid, "event_visibility") if r.payload.get("user_id") == user.id and r.payload.get("hidden")}
    return [{**e, "hidden_for_me": e["id"] in hidden} for e in sorted(result, key=lambda e: e.get("relevance", 0), reverse=True)[:200]]


@app.post("/api/workspaces/{wid}/events/{eid}/visibility", tags=["Analysis"])
def event_visibility(wid: str, eid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    if not db.query(Item).filter_by(id=eid, workspace_id=wid, kind="event").first():
        raise HTTPException(404, "Event not found.")
    if not isinstance(data.get("hidden"), bool):
        raise HTTPException(422, "Specify whether this signal is hidden.")
    record(db, wid, "event_visibility", {"event_id": eid, "user_id": user.id, "hidden": data["hidden"]}, key=f"{eid}:{user.id}")
    audit(db, user.id, "event.hidden" if data["hidden"] else "event.restored", wid, event_id=eid)
    db.commit()
    return {"event_id": eid, "hidden": data["hidden"]}


@app.get("/api/workspaces/{wid}/events/{eid}", tags=["Analysis"])
def event_detail(wid: str, eid: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    row = db.query(Item).filter_by(id=eid, workspace_id=wid, kind="event").first()
    if not row:
        raise HTTPException(404, "Event not found.")
    return pack(row)


@app.post("/api/workspaces/{wid}/events/{eid}/feedback", tags=["Analysis"])
def feedback(wid: str, eid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    if not db.query(Item).filter_by(id=eid, workspace_id=wid, kind="event").first():
        raise HTTPException(404, "Event not found.")
    if data.get("rating") not in {"useful", "irrelevant", "incorrect"}:
        raise HTTPException(422, "Choose a feedback rating.")
    record(db, wid, "feedback", {"event_id": eid, "user_id": user.id, "rating": data["rating"], "comment": str(data.get("comment", ""))[:1500]}, key=f"{eid}:{user.id}")
    audit(db, user.id, "event.feedback", wid, event_id=eid, rating=data["rating"]);db.commit()
    return {"ok": True}


@app.post("/api/workspaces/{wid}/events/{eid}/save", tags=["Analysis"])
def save_event(wid: str, eid: str, request: Request, data: dict = Body(default={}), db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    if not db.query(Item).filter_by(id=eid, workspace_id=wid, kind="event").first():
        raise HTTPException(404, "Event not found.")
    row = record(db, wid, "saved", {"event_id": eid, "user_id": user.id, "saved": bool(data.get("saved", True))}, key=f"{eid}:{user.id}")
    db.commit();return pack(row)


@app.get("/api/workspaces/{wid}/saved", tags=["Analysis"])
def saved(wid: str, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    return [r.payload["event_id"] for r in items(db, wid, "saved") if r.payload.get("user_id") == user.id and r.payload.get("saved")]


@app.get("/api/workspaces/{wid}/alerts", tags=["Notifications"])
def alerts(wid: str, request: Request, db=Depends(get_db)):
    user, ws, member = access(request, db, wid)
    return [{**pack(r), "read": user.id in r.payload.get("read_by", [])} for r in items(db, wid, "alert") if r.payload.get("decision_role", "ceo") == member.decision_role and r.payload.get("profile_version", 1) == ws.profile.get("version", 1)][:100]


@app.post("/api/workspaces/{wid}/alerts/read", tags=["Notifications"])
def alerts_read(wid: str, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    for row in items(db, wid, "alert"):
        row.payload = {**row.payload, "read_by": list(set([*row.payload.get("read_by", []), user.id]))}
    db.commit();return {"ok": True}


@app.get("/api/workspaces/{wid}/briefs", tags=["Briefs"])
def briefs(wid: str, request: Request, db=Depends(get_db)):
    _, ws, member = access(request, db, wid)
    return [pack(r) for r in items(db, wid, "brief") if r.payload.get("decision_role", "ceo") == member.decision_role and r.payload.get("profile_version",1)==ws.profile.get("version",1)]


@app.post("/api/workspaces/{wid}/briefs", tags=["Briefs"])
def brief_generate(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, _, member = access(request, db, wid, WRITE_ROLES)
    rate_limit(request, "briefs", 20, 3600)
    if data.get("period") not in {"day", "week", "month"}:
        raise HTTPException(422, "Choose day, week or month.")
    return job_public(create_job(db, wid, user.id, "brief", {"period": data["period"], "decision_role": member.decision_role}))


@app.get("/api/workspaces/{wid}/jobs", tags=["Analysis"])
def jobs(wid: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    return [job_public(j) for j in db.query(Job).filter_by(workspace_id=wid).order_by(Job.created_at.desc()).limit(30)]


@app.get("/api/workspaces/{wid}/jobs/{jid}", tags=["Analysis"])
def get_job(wid: str, jid: str, request: Request, db=Depends(get_db)):
    access(request, db, wid)
    job = db.query(Job).filter_by(id=jid, workspace_id=wid).first()
    if not job:
        raise HTTPException(404, "Analysis run not found.")
    return job_public(job)


@app.post("/api/workspaces/{wid}/jobs/{jid}/retry", tags=["Analysis"])
def retry_job(wid: str, jid: str, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid, WRITE_ROLES)
    old = db.query(Job).filter_by(id=jid, workspace_id=wid).first()
    if not old or old.status != "failed":
        raise HTTPException(422, "Only failed runs can be retried.")
    rate_limit(request, "retry", 12, 3600)
    return job_public(create_job(db, wid, user.id, old.kind, old.input))


@app.post("/api/workspaces/{wid}/assistant", tags=["Analysis"])
def assistant(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid)
    rate_limit(request, "assistant", 25, 3600)
    question = str(data.get("question", "")).strip()[:1500]
    if len(question) < 4:
        raise HTTPException(422, "Ask a question about your company's events or business exposures.")
    language = "ru" if data.get("locale") == "ru" else "en"
    all_events = items(db, wid, "event")
    candidates = [pack(e) for e in all_events if (e.id == data["event_id"] if data.get("event_id") else e.payload.get("decision_role", "ceo") == member.decision_role and e.payload.get("profile_version", 1) == ws.profile.get("version", 1))]
    candidates = sorted(candidates, key=lambda e: relevance(json.dumps(e.get(language, {}), ensure_ascii=False), ws.profile, [question], member.decision_role)[0], reverse=True)[:7]
    aliases = {f"E{i+1}": e["id"] for i,e in enumerate(candidates)}
    client_host=(urlsplit(ws.profile.get("website", "")).hostname or "").removeprefix("www.")
    evidence = [{"id": alias, "published_at": e.get("published_at"), "historical_context": e.get("profile_version",1) != ws.profile.get("version",1), "source_publisher": e.get("article",{}).get("source_name"), "source_url": e.get("article",{}).get("url"), "source_is_company": bool(client_host and (urlsplit(e.get("article",{}).get("url", "")).hostname or "").removeprefix("www.")==client_host), "reported_fact": (e.get(language) or {}).get("fact"), "company_relevance": (e.get(language) or {}).get("why"), "conditional_implication": (e.get(language) or {}).get("impact"), "limitations": (e.get(language) or {}).get("uncertainties", []), "source_excerpt": e.get("article",{}).get("text", "")[:1800]} for alias,e in zip(aliases,candidates)]
    needs_bank = re.search(r"\b(?:banks?|alfa|rates?|credit|financ\w*|refinanc\w*|liquid\w*|cash.flow|inflation|debt|borrow\w*|treasury)\b|банк|альфа|ставк|кредит|финанс|ликвид|денежн|инфляц", question, re.I) or re.search(r"loan|credit|leas|borrow|кредит|лизинг", " ".join(ws.profile.get("exposures", [])), re.I)
    bank = retrieve_bank(db, question + " " + " ".join(ws.profile.get("exposures", [])), limit=2, wid=wid) if needs_bank else []
    bank_aliases = {f"B{i+1}": b["id"] for i,b in enumerate(bank)}
    bank_context = [{**{k:b.get(k) for k in ["title","published_at","page","text"]},"id":alias} for alias,b in zip(bank_aliases,bank)]
    history = [{k:r.payload.get(k) for k in ["question"]} for r in items(db,wid,"message") if r.payload.get("user_id")==user.id][:2]
    context = f"Company: {json.dumps(ws.profile,ensure_ascii=False)}. Role: {member.decision_role}. Source-reported facts and separately labelled AI hypotheses: {json.dumps(evidence,ensure_ascii=False)}." + (f" Dated bank research: {json.dumps(bank_context,ensure_ascii=False)}." if bank else "")
    db.commit()
    rules = "Use only supplied evidence. Non-empty confirmed profile fields take precedence over older questions in unknowns. Keep jurisdiction-specific programs and regulation in their actual country: US ESSER funding is NOT evidence of Australian funding changes. If local coverage is missing, say so and propose collecting it; do not fill the gap with an assumed cross-country analogy. Distinguish reporting decisions for a news publisher from procurement decisions for a school. The source publisher is NOT automatically the analysed company. source_is_company=false means a different publisher, NOT proof the client has never published the same story. Missing evidence of a client action means unverified, not that the action did not happen. External reporting is valid evidence of external developments; do not call it absent merely because the client is not the publisher. External reporting creates a possible editorial angle; it does NOT demonstrate the client has covered that story or has a proven capability. Never attribute source publication, implementation or achievements to the client unless reported_fact explicitly names it as the actor or source_is_company=true. Company relevance and conditional_implication are hypotheses, not evidence of completed company actions. Prior chat is not evidence and must not override the original source. When asked for a fact and an action, write distinct Source fact, Suggested test, and Unknowns paragraphs. The test is a proposal to validate audience value, not a company achievement. Tie the proposed test directly to a cited local fact and its topic. Do not substitute an unrelated country, program or topic when local evidence is available. A missing metric is a gap to measure, not a reason to invent a different editorial theme. If asked for one test, give one concrete test. Do not invent company contracts, audience metrics or bank views. State dates for bank research. Recommendations are suggested tests, not mandatory pivots or legal obligations. The server will quote the selected reported_fact verbatim with its publisher. Do not restate those facts or invent client publication history. Write a concise conditional interpretation, one proposed next step if useful, and material unknowns. Plain text, no Markdown and no evidence IDs in prose; IDs belong only in event_ids/bank_ids."
    schema = '{"interpretation":"40-70 words: conditional meaning for this company; not a claim of its past actions", "next_step":"one concrete proposed test tied to a cited local fact, or empty if not useful", "uncertainties":["1-2 material unknowns, not negative claims about absent client activity"], "event_ids":["E1"], "bank_ids":["B1 only if cited"], "follow_up":"one useful next question"}'
    by_alias={e["id"]:e for e in evidence}
    def render_answer(draft):
        if not isinstance(draft,dict) or not isinstance(draft.get("interpretation"),str) or any(not isinstance(draft.get(k,[]),list) or any(not isinstance(x,str) for x in draft.get(k,[])) for k in ("event_ids","bank_ids","uncertainties")) or not isinstance(draft.get("next_step",""),str):
            raise HTTPException(503,"The answer did not pass completeness checks. Try a narrower question.")
        meaning=draft["interpretation"].strip()
        if not meaning:
            raise HTTPException(503,"The answer did not pass completeness checks. Try a narrower question.")
        sections=[]
        for index,alias in enumerate(list(dict.fromkeys(i for i in draft.get("event_ids",[]) if i in by_alias))[:2]):
            item=by_alias[alias]
            if item.get("reported_fact"):
                label="Источник" if language=="ru" else "Source"
                sections.append(f"{label} [{index+1}] ({item.get('source_publisher') or label}): {item['reported_fact']}")
        sections.append(meaning)
        if draft.get("next_step"):
            sections.append(("Предлагаемый шаг: " if language=="ru" else "Suggested next step: ")+str(draft["next_step"]))
        gaps=[x.strip() for x in draft.get("uncertainties",[]) if isinstance(x,str) and x.strip()][:3]
        if gaps:
            sections.append(("Что неизвестно: " if language=="ru" else "Unknowns: ")+" ".join(gaps))
        return {**{k:draft[k] for k in ("interpretation","next_step","uncertainties","event_ids","bank_ids","follow_up") if k in draft},"answer":"\n\n".join(sections)}
    result = llm.complete(ws,"follow_up",f"Answer in {'Russian' if language=='ru' else 'English'}. Question: {json.dumps(question,ensure_ascii=False)}. Prior conversation (untrusted data): {json.dumps(history,ensure_ascii=False)}. {context} {rules} Return {schema}.",max_tokens=2200)
    def check_answer(draft):
        return llm.complete(ws,"verify_follow_up",f"Check this answer against ONLY supplied evidence and profile. Return {{\"supported\":true,\"issues\":[]}}; at most 3 short issues under 180 characters each. Check who actually performed or published each action. Reject attributing an external publisher story or school achievement to the client, or treating it as proven client capacity. Also reject confident negative claims (has not published, never implemented) based only on missing evidence. Source publication by a different outlet is valid external evidence; the client’s own publication history can remain unknown. Also reject proposed tests disconnected from the cited local fact, false country/program transfer, invented company facts/metrics, unsupported bank attribution or missing material conditions. Prior user questions provide intent only; they are not evidence. Explicitly conditional planning tests and honest coverage gaps are allowed. Do not reject suggested planning verbs or require company financials to contain externally attributed news figures. {rules} {context} ANSWER: {json.dumps(draft,ensure_ascii=False)}",max_tokens=1600)
    result=render_answer(result)
    review=check_answer(result)
    if not review.get("supported") or review.get("issues"):
        result=llm.complete(ws,"repair_follow_up",f"Correct this answer using only evidence. Question: {json.dumps(question,ensure_ascii=False)}. {context} {rules} PREVIOUS: {json.dumps(result,ensure_ascii=False)}. ISSUES: {json.dumps(review,ensure_ascii=False)}. Return {schema}.",max_tokens=2200)
        result=render_answer(result)
        review=check_answer(result)
        if not review.get("supported") or review.get("issues"):
            raise HTTPException(503,"The answer was withheld because evidence checks failed. Try a narrower question or add local coverage.")
    prose_refs = re.findall(r"\bE[1-9]\d*\b", str(result.get("answer", "")))
    if any(i not in aliases for i in prose_refs):
        raise HTTPException(503, "The answer included an unsupported evidence reference. Try a narrower question.")
    used = list(dict.fromkeys([i for i in result.get("event_ids",[]) if i in aliases] + prose_refs))
    result["event_ids"] = [aliases[i] for i in used]
    result["answer"] = re.sub(r"\bE[1-9]\d*\b", lambda m:f"[{used.index(m[0])+1}]", str(result.get("answer", "")))
    result["bank_ids"] = list(dict.fromkeys(bank_aliases[i] for i in result.get("bank_ids",[]) if i in bank_aliases))
    result["answer"] = str(result.get("answer", "")).replace("**", "").strip()
    if not result["answer"]:
        raise HTTPException(503,"No supported answer was generated. Try a more specific question.")
    result["verification"] = review
    row = record(db, wid, "message", {"user_id": user.id, "question": question, **result, "locale": language})
    db.commit();return pack(row)


@app.get("/api/workspaces/{wid}/assistant", tags=["Analysis"])
def assistant_history(wid: str, request: Request, db=Depends(get_db)):
    user, _, _ = access(request, db, wid)
    return [pack(r) for r in reversed(items(db, wid, "message")) if r.payload.get("user_id") == user.id][-40:]


@app.get("/api/workspaces/{wid}/members", tags=["Team"])
def members(wid: str, request: Request, db=Depends(get_db)):
    _, _, current = access(request, db, wid)
    result = []
    for m in db.query(Member).filter_by(workspace_id=wid).all():
        user = db.get(User, m.user_id)
        result.append({"id": m.id, "user_id": user.id, "name": user.name, "email": user.email, "role": m.role, "decision_role": m.decision_role})
    invites = [{"id": r.id, "email": r.payload["email"], "role": r.payload["role"], "expires_at": r.payload["expires_at"], "accepted": r.payload.get("accepted", False)} for r in items(db, wid, "invite")] if current.role in {"owner", "admin"} else []
    return {"members": result, "invitations": invites}


@app.patch("/api/workspaces/{wid}/members/{mid}", tags=["Team"])
def change_role(wid: str, mid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, _, actor = access(request, db, wid, {"owner", "admin"})
    m = db.query(Member).filter_by(id=mid, workspace_id=wid).first()
    if not m or m.role == "owner" or m.user_id == user.id:
        raise HTTPException(403, "The owner role and your own role cannot be changed here.")
    if data.get("role") not in {"admin", "analyst", "viewer"} or (actor.role == "admin" and (m.role == "admin" or data["role"] == "admin")):
        raise HTTPException(403, "Only the owner can manage administrators.")
    m.role = data["role"]
    audit(db, user.id, "member.role_changed", wid, member_id=mid, role=m.role);db.commit()
    return {"ok": True}


@app.delete("/api/workspaces/{wid}/members/{mid}", tags=["Team"])
def remove_member(wid: str, mid: str, request: Request, db=Depends(get_db)):
    user, _, actor = access(request, db, wid, {"owner", "admin"})
    m = db.query(Member).filter_by(id=mid, workspace_id=wid).first()
    if not m:
        raise HTTPException(404, "Member not found.")
    if m.role == "owner" or (m.role == "admin" and actor.role != "owner") or m.user_id == user.id:
        raise HTTPException(403, "This member cannot be removed by your role.")
    db.delete(m);audit(db, user.id, "member.removed", wid, member_id=mid);db.commit()
    return {"ok": True}


@app.post("/api/workspaces/{wid}/invites", tags=["Team"])
def invite(wid: str, data: InviteIn, request: Request, db=Depends(get_db)):
    user, ws, actor = access(request, db, wid, {"owner", "admin"})
    rate_limit(request, "invite", 20, 3600)
    email = valid_email(data.email)
    if data.role not in {"admin", "analyst", "viewer"} or (data.role == "admin" and actor.role != "owner"):
        raise HTTPException(403, "Only the owner can invite administrators.")
    if ws.demo:
        raise HTTPException(422, "Create a real workspace to invite your team. Demo workspaces are personal sandboxes.")
    if not user.verified:
        raise HTTPException(403, "Confirm your email before inviting teammates.")
    existing = db.query(User).filter_by(email=email).first()
    if existing and db.query(Member).filter_by(user_id=existing.id, workspace_id=wid).first():
        raise HTTPException(409, "This user already belongs to the workspace.")
    token = secrets.token_urlsafe(32)
    expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
    row = record(db, wid, "invite", {"email": email, "role": data.role, "expires_at": expiry, "accepted": False, "invited_by": user.id}, key=hash_token(token))
    link = base_url(request) + "/invite?token=" + token
    lang = existing.preferences.get("locale", "en") if existing else request_locale(request)
    translated_role = {"admin": "администратор", "analyst": "аналитик", "viewer": "наблюдатель"}[data.role]
    enqueue(db, wid, email, f"Приглашение в {ws.name} · SignalDesk" if lang == "ru" else f"Join {ws.name} on SignalDesk", f"<p>{html.escape(user.name)} приглашает вас в <strong>{html.escape(ws.name)}</strong>. Ваша роль: {translated_role}.</p><p>Приглашение действует семь дней.</p>" if lang == "ru" else f"<p>{html.escape(user.name)} invited you to <strong>{html.escape(ws.name)}</strong> as {html.escape(data.role)}.</p><p>This invitation expires in seven days.</p>", link=link, locale=lang)
    audit(db, user.id, "member.invited", wid, role=data.role);db.commit()
    return {"id": row.id, "invite_url": link, "delivery_enabled": os.getenv("EMAIL_DELIVERY") == "sendpulse"}


@app.get("/api/invites/{token}", tags=["Team"])
def invite_info(token: str, db=Depends(get_db)):
    row = db.query(Item).filter_by(kind="invite", key=hash_token(token)).first()
    if not row or row.payload.get("accepted") or row.payload["expires_at"] < now():
        raise HTTPException(404, "This invitation is invalid or has expired.")
    ws = db.get(Workspace, row.workspace_id)
    return {"workspace": ws.name, "role": row.payload["role"], "email_hint": re.sub(r"^(.).+(@.*)$", r"\1•••\2", row.payload["email"])}


@app.post("/api/invites/{token}/accept", tags=["Team"])
def accept_invite(token: str, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    require_account(user)
    row = db.query(Item).filter_by(kind="invite", key=hash_token(token)).first()
    if not row or row.payload.get("accepted") or row.payload["expires_at"] < now():
        raise HTTPException(404, "This invitation is invalid or has expired.")
    if user.email != row.payload["email"]:
        raise HTTPException(403, "Sign in with the email address this invitation was sent to.")
    if not db.query(Member).filter_by(user_id=user.id, workspace_id=row.workspace_id).first():
        db.add(Member(user_id=user.id, workspace_id=row.workspace_id, role=row.payload["role"]))
    row.payload = {**row.payload, "accepted": True}
    audit(db, user.id, "member.joined", row.workspace_id);db.commit()
    return {"workspace_id": row.workspace_id}


@app.patch("/api/workspaces/{wid}/decision-role", tags=["Workspaces"])
def decision_role(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid)
    if data.get("role") not in {"ceo", "cfo", "owner", "treasury", "accountant", "strategy"}:
        raise HTTPException(422, "Unsupported decision role.")
    member.decision_role = data["role"]
    audit(db, user.id, "member.decision_role_updated", wid, role=member.decision_role);db.commit()
    return ws_public(ws, member)


@app.put("/api/workspaces/{wid}/model", tags=["Models"])
def model_config(wid: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    user, ws, member = access(request, db, wid, {"owner"})
    mode = data.get("mode", "case")
    if mode == "case":
        model = data.get("model", llm.APPROVED_MODELS[2])
        if model not in llm.APPROVED_MODELS:
            raise HTTPException(422, "Select an approved case model.")
        cfg = {"mode": "case", "model": model}
    elif mode == "custom":
        base = str(data.get("base_url", ""))[:2000]
        safe_url(base)
        if urlsplit(base).scheme != "https":
            raise HTTPException(422, "Model connections require HTTPS.")
        if urlsplit(base).query:
            raise HTTPException(422, "Use a base URL without query parameters.")
        key = str(data.get("api_key", ""))
        old = ws.settings.get("model", {})
        if not key and old.get("mode") != "custom":
            raise HTTPException(422, "Enter an API key.")
        if not data.get("model"):
            raise HTTPException(422, "Enter a model ID.")
        cfg = {"mode": "custom", "base_url": base, "model": str(data["model"])[:200], "key_encrypted": encrypt(key) if key else old.get("key_encrypted", "")}
    else:
        raise HTTPException(422, "Unsupported model connection.")
    if ws.demo and mode == "custom":
        raise HTTPException(422, "Create a real workspace before adding a private model connection.")
    ws.settings = {**ws.settings, "model": cfg}
    audit(db, user.id, "model.connection_updated", wid, mode=mode, model=cfg["model"]);db.commit()
    return ws_public(ws, member)


@app.post("/api/workspaces/{wid}/model/test", tags=["Models"])
def test_model(wid: str, request: Request, db=Depends(get_db)):
    _, ws, _ = access(request, db, wid, {"owner"})
    rate_limit(request, "model-test", 6, 3600)
    result = llm.complete(ws, "connection_test", 'Return {"ok":true}.', max_tokens=500)
    return {"ok": result.get("ok") is True, "model": llm.config(ws)["model"]}


@app.get("/api/workspaces/{wid}/export", tags=["Workspaces"])
def export_workspace(wid: str, request: Request, db=Depends(get_db)):
    user, ws, member = access(request, db, wid, {"owner", "admin"})
    data = {"analysis_notice": {"en": "AI-generated decision support. Model interpretations are not the bank’s official position. Not an individual investment recommendation.", "ru": "Аналитика подготовлена с помощью ИИ. Выводы модели не являются официальной позицией банка. Не является индивидуальной инвестиционной рекомендацией."}, "workspace": ws_public(ws, member), "events": [pack(r) for r in items(db, wid, "event")], "briefs": [pack(r) for r in items(db, wid, "brief")], "sources": [pack(r) for r in items(db, wid, "source")], "exported_at": now()}
    audit(db, user.id, "workspace.exported", wid);db.commit()
    return Response(json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="signaldesk-export.json"'})


# Independent administrator realm. Product accounts are never accepted by these endpoints.
@app.post("/api/ops/login", tags=["Operations"])
def admin_login(data: Credentials, request: Request, response: Response, db=Depends(get_db)):
    rate_limit(request, "ops-login", 6, 900)
    admin = db.query(Admin).filter_by(email=data.email.strip().lower()).first()
    if not admin or not password_ok(admin.password, data.password):
        raise HTTPException(401, "Administrator credentials are incorrect.")
    issue_session(db, response, admin.id, "admin")
    audit(db, admin.id, "ops.signed_in");db.commit()
    return {"email": admin.email}


@app.get("/api/ops/me", tags=["Operations"])
def admin_me(request: Request, db=Depends(get_db)):
    admin = current_user(request, db, "admin")
    return {"email": admin.email}


@app.post("/api/ops/logout", tags=["Operations"])
def admin_logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get("sd_admin", "")
    row = db.get(Session, hash_token(token))
    if row:
        db.delete(row);db.commit()
    response.delete_cookie("sd_admin", path="/api/ops")
    return {"ok": True}


@app.get("/api/ops/overview", tags=["Operations"])
def admin_overview(request: Request, db=Depends(get_db)):
    current_user(request, db, "admin")
    recent = db.query(Job).order_by(Job.created_at.desc()).limit(100).all()
    usage = db.query(Usage).order_by(Usage.created_at.desc()).limit(500).all()
    feedback_rows = db.query(Item).filter_by(kind="feedback").all()
    feedback_counts = {k: sum(r.payload.get("rating") == k for r in feedback_rows) for k in ["useful", "irrelevant", "incorrect"]}
    events_count = sum(r.payload.get("status") == "verified" and not r.payload.get("is_demo") for r in db.query(Item).filter_by(kind="event"))
    all_users = db.query(User).all()
    registered_users = [u for u in all_users if not is_guest(u)]
    return {"users": len(registered_users), "guest_sessions": len(all_users) - len(registered_users), "verified_users": sum(u.verified for u in registered_users), "workspaces": db.query(Workspace).count(), "live_workspaces": db.query(Workspace).filter_by(demo=False).count(), "events": events_count, "jobs": [job_public(j) for j in recent], "usage": [{k: getattr(r,k) for k in ["id","workspace_id","purpose","model","tokens","latency_ms","status","created_at"]} for r in usage], "feedback": feedback_counts, "email": {status: sum(r.payload.get("status") == status for r in db.query(Item).filter_by(kind="mail").all()) for status in ["sent","failed","pending","disabled"]}, "model_configured": bool(os.getenv("ALFA_API_KEY")), "email_enabled": os.getenv("EMAIL_DELIVERY") == "sendpulse"}


@app.get("/api/ops/users", tags=["Operations"])
def admin_users(request: Request, db=Depends(get_db)):
    current_user(request, db, "admin")
    return [{**public_user(u), "disabled": u.disabled, "created_at": u.created_at, "workspace_count": db.query(Member).filter_by(user_id=u.id).count()} for u in db.query(User).order_by(User.created_at.desc()).limit(500)]


@app.patch("/api/ops/users/{user_id}", tags=["Operations"])
def admin_user_update(user_id: str, request: Request, data: dict = Body(...), db=Depends(get_db)):
    admin = current_user(request, db, "admin")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found.")
    user.disabled = bool(data.get("disabled", False))
    if user.disabled:
        db.query(Session).filter_by(user_id=user.id, realm="product").delete()
    audit(db, admin.id, "ops.user_access_updated", target_user=user.id, disabled=user.disabled);db.commit()
    return {"ok": True}


@app.get("/api/ops/audit", tags=["Operations"])
def admin_audit(request: Request, db=Depends(get_db)):
    current_user(request, db, "admin")
    return [{k: getattr(r,k) for k in ["id","workspace_id","actor_id","action","detail","created_at"]} for r in db.query(Audit).order_by(Audit.created_at.desc()).limit(300)]


@app.get("/api/ops/feedback", tags=["Operations"])
def admin_feedback(request: Request, db=Depends(get_db)):
    current_user(request, db, "admin")
    return [{"workspace_id": r.workspace_id, **pack(r)} for r in db.query(Item).filter_by(kind="feedback").order_by(Item.created_at.desc()).limit(200)]


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


static_dir = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if static_dir.exists() and (static_dir / "assets").exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith(("api/", ".", "data/")):
        raise HTTPException(404, "Not found.")
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "SignalDesk API is running. Start the frontend development server on port 5173."})
