from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import socket
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request, Response

from .db import Admin, Member, Session, User, Workspace, now

hasher = PasswordHasher()
_attempts = defaultdict(deque)
SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"


def hash_token(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_ok(encoded, plain):
    try:
        return hasher.verify(encoded, plain)
    except Argon2Error:
        return False


def rate_limit(request: Request, bucket="auth", limit=12, seconds=300):
    key = (request.client.host, bucket)
    q = _attempts[key]
    t = time.monotonic()
    while q and q[0] < t - seconds:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many requests. Try again shortly.")
    q.append(t)


def issue_session(db, response: Response, user_id: str, realm="product"):
    token = secrets.token_urlsafe(40)
    expires = (datetime.now(timezone.utc) + timedelta(days=14 if realm == "product" else 1)).isoformat(timespec="seconds").replace("+00:00", "Z")
    db.add(Session(token_hash=hash_token(token), user_id=user_id, realm=realm, expires_at=expires))
    response.set_cookie({"admin": "sd_admin", "guest": "sd_guest"}.get(realm, "sd_session"), token, httponly=True, secure=SECURE, samesite="lax", max_age=86400 * (14 if realm == "product" else 1), path="/api/ops" if realm == "admin" else "/")


def is_guest(user):
    return user.preferences.get("account_kind") == "guest" or (user.email.startswith("demo-") and user.email.endswith("@example.invalid"))


def require_account(user):
    if is_guest(user):
        raise HTTPException(403, "This is a read-only tour. Create an account or sign in to your own workspace.")


def current_user(request, db, realm="product", allow_unverified=False):
    if realm == "product" and request.headers.get("x-signaldesk-tour") == "1":
        realm = "guest"
    token = request.cookies.get({"admin": "sd_admin", "guest": "sd_guest"}.get(realm, "sd_session"), "")
    session = db.get(Session, hash_token(token)) if token else None
    if not session or session.realm != realm or session.expires_at < now():
        raise HTTPException(401, "Please sign in.")
    user = db.get(Admin if realm == "admin" else User, session.user_id)
    if not user or getattr(user, "disabled", False):
        raise HTTPException(401, "Please sign in.")
    if realm in {"product", "guest"} and is_guest(user) and request.method not in {"GET", "HEAD"}:
        require_account(user)
    if realm == "product" and not allow_unverified and not user.verified and not is_guest(user):
        raise HTTPException(403, "Confirm your email before opening your workspace.")
    return user


def access(request, db, wid, roles=None):
    user = current_user(request, db)
    tail = request.url.path.partition(f"/workspaces/{wid}")[2]
    if is_guest(user) and (request.method not in {"GET", "HEAD"} or tail.startswith(("/export", "/members", "/datasets", "/model"))):
        require_account(user)
    member = db.query(Member).filter_by(user_id=user.id, workspace_id=wid).first()
    if not member:
        raise HTTPException(404, "Workspace not found.")
    if roles and (member.role not in roles or is_guest(user)):
        raise HTTPException(403, "Your workspace role does not allow this action.")
    workspace = db.get(Workspace, wid)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    if is_guest(user) and (workspace.demo or not workspace.settings.get("showcase")):
        raise HTTPException(404, "This workspace is not part of the public tour.")
    return user, workspace, member


def safe_url(value: str, resolve=True):
    """Only public HTTP(S); repeat this check for each redirect to prevent SSRF."""
    try:
        parsed = urlsplit(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            raise ValueError()
        host = parsed.hostname.lower().rstrip(".")
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
            raise ValueError()
        literal = None
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            try:
                literal = ipaddress.ip_address(socket.inet_aton(host))
            except OSError:
                pass
        if literal and not literal.is_global:
            raise ValueError()
        if resolve:
            addresses = {x[4][0] for x in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)}
            if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
                raise ValueError()
        return value.strip()
    except (ValueError, OSError):
        raise ValueError("Use a public website URL with https:// and a standard port.")


def cipher():
    key = os.environ.get("APP_SECRET", "development-only-replace-in-production")
    import base64
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def encrypt(value):
    return cipher().encrypt(value.encode()).decode() if value else ""


def decrypt(value):
    return cipher().decrypt(value.encode()).decode() if value else ""
