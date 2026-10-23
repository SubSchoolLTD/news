from __future__ import annotations

import base64
import html
import os
from datetime import datetime, timedelta, timezone

import httpx

from .db import DB, Item, items, now, record


def template(title, body, button_label="Open SignalDesk", button_url=None, locale="en"):
    url = button_url or os.getenv("PUBLIC_URL", "https://analytics.subschool.us")
    foot = "Вы получили это письмо от вашего рабочего пространства SignalDesk. Настроить уведомления можно в профиле." if locale == "ru" else "Sent by your SignalDesk workspace. Manage email preferences in your profile."
    return f'''<!doctype html><html lang="{locale}"><body style="margin:0;background:#f6f5f8;font:15px/1.6 Arial,sans-serif;color:#25212b"><div style="max-width:580px;margin:40px auto;padding:0 20px"><div style="font-size:22px;font-weight:bold;margin:0 0 24px;color:#a24cb8">◈ SignalDesk</div><div style="background:white;border:1px solid #e7e4eb;border-radius:20px;padding:32px"><h1 style="font-size:25px;line-height:1.25;margin:0 0 24px">{html.escape(title)}</h1><div>{body}</div><a href="{html.escape(url,quote=True)}" style="display:inline-block;margin-top:24px;padding:12px 22px;background:#a24cb8;border-radius:10px;text-decoration:none;color:white;font-weight:bold">{html.escape(button_label)}</a></div><p style="font-size:12px;color:#77717e;margin-top:24px">{foot}</p><p style="font-size:12px;color:#999">SignalDesk · Business intelligence by SubSchool</p></div></body></html>'''


def enqueue(db, wid, to, subject, body, *, link=None, locale="en", key=None):
    if key and db.query(Item).filter_by(workspace_id=wid, kind="mail", key=key).first():
        return
    record(db, wid, "mail", {"to": to, "subject": subject, "html": template(subject, body, button_url=link, locale=locale), "status": "pending", "attempts": 0, "next_attempt": now()}, key=key)


def deliver_pending():
    with DB() as db:
        pending = db.query(Item).filter_by(kind="mail").order_by(Item.created_at).limit(500).all()
        pending = [x for x in pending if x.payload.get("status") == "pending" and x.payload.get("next_attempt", "") <= now()][:10]
        if not pending:
            return
        mode = os.getenv("EMAIL_DELIVERY", "disabled")
        if mode != "sendpulse":
            for row in pending:
                row.payload = {**row.payload, "status": "disabled", "error": "Email delivery is disabled in this environment."}
            db.commit()
            return
        client_id, secret = os.getenv("SENDPULSE_ID"), os.getenv("SENDPULSE_SECRET")
        token = None
        try:
            if not client_id or not secret:
                raise ValueError("SendPulse credentials are not configured.")
            response = httpx.post("https://api.sendpulse.com/oauth/access_token", json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": secret}, timeout=20)
            response.raise_for_status()
            token = response.json()["access_token"]
        except Exception:
            token = None
        for row in pending:
            p = dict(row.payload)
            try:
                if not token:
                    raise ValueError("SendPulse authentication is unavailable.")
                response = httpx.post("https://api.sendpulse.com/smtp/emails", headers={"Authorization": f"Bearer {token}"}, json={"email": {"html": base64.b64encode(p["html"].encode()).decode(), "text": p["subject"], "subject": p["subject"], "from": {"name": "SignalDesk", "email": os.getenv("EMAIL_FROM", "maksim@subschool.us")}, "to": [{"email": p["to"]}]}}, timeout=25)
                response.raise_for_status()
                if not response.json().get("result"):
                    raise ValueError("SendPulse did not accept the email.")
                p.update(status="sent", sent_at=now(), provider_id=response.json().get("id", ""), error="")
            except Exception:
                attempts = p.get("attempts", 0) + 1
                p.update(attempts=attempts, status="failed" if attempts >= 3 else "pending", error="Email delivery failed. Check SendPulse status and sender verification.", next_attempt=(datetime.now(timezone.utc) + timedelta(minutes=5 * attempts)).isoformat(timespec="seconds").replace("+00:00", "Z"))
            row.payload = p
        db.commit()
