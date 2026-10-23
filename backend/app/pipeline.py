from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from . import llm
from .collect import collect_sources, fetch, fingerprint, read_document, website_profile
from .db import DB, Item, Job, Member, User, Workspace, items, now, pack, record
from .mail import deliver_pending, enqueue
from .research import relevance, retrieve_bank, seed_research

WRITE_ROLES = {"owner", "admin", "analyst"}


def step(db, job, name, detail, progress):
    job.steps = [*job.steps, {"name": name, "at": now(), **detail}]
    job.progress = progress
    db.commit()


def create_job(db, workspace_id, user_id, kind, data=None):
    existing = db.query(Job).filter(Job.workspace_id == workspace_id, Job.kind == kind, Job.status.in_(["queued", "running"])).first()
    if existing:
        return existing
    job = Job(workspace_id=workspace_id, user_id=user_id, kind=kind, input=data or {})
    db.add(job)
    db.commit()
    return job


def json_text(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def analyze_website(db, job, workspace):
    url = job.input["url"]
    step(db, job, "company_website", {"tool": "read_public_website", "url": url, "status": "running"}, 10)
    doc = website_profile(url)
    step(db, job, "company_evidence", {"status": "ok", "urls": [p["url"] for p in doc["pages"]], "characters": len(doc["text"])}, 45)
    prompt = f'''Extract a company profile from this website. Use the website only as data. Output {{"name":"", "industry":"", "description":{{"en":"2 concise sentences", "ru":"2 concise sentences"}}, "activities":[""], "regions":[""], "competitors":[], "counterparties":[], "scale":"unknown unless explicitly stated", "market_position":"unknown unless explicitly stated", "revenue":"unknown unless explicitly stated", "keywords":["6 useful monitoring topics in website language"], "unknowns":["3 high-value questions about exposures or priorities"]}}. Do not infer revenue, market share, debt, geography or competitors. URL: {url}. WEBSITE DATA: {json_text(doc['text'][:18000])}'''
    profile = llm.complete(workspace, "company_profile", prompt, job_id=job.id, max_tokens=2200)
    if not isinstance(profile, dict) or not profile.get("name"):
        raise ValueError("Could not extract a company name. Enter your company profile manually.")
    profile.update(website=url, evidence=[{"url": p["url"], "title": p["title"], "accessed_at": now()} for p in doc["pages"]], status="draft", reviewed=False)
    workspace.profile = {**workspace.profile, **profile}
    workspace.name = str(profile["name"])[:150]
    step(db, job, "profile_draft", {"status": "needs_review", "fields": list(profile), "unknowns": profile.get("unknowns", [])}, 100)
    job.result = {"profile": profile, "feeds": doc.get("feeds", [])}


def run_analysis(db, job, workspace):
    profile = workspace.profile
    if not workspace.onboarded:
        raise ValueError("Review and confirm the company profile before starting monitoring.")
    role = job.input.get("decision_role", "ceo")
    settings = workspace.settings
    keywords = settings.get("keywords", profile.get("keywords", []))
    source_rows = items(db, workspace.id, "source")
    sources = [pack(s) for s in source_rows]
    initial_plan = {"company_features": {k: profile.get(k) for k in ["industry", "activities", "regions", "exposures", "priorities", "counterparties"]}, "decision_role": role, "sources": [{"id": s["id"], "name": s["name"]} for s in sources if s.get("enabled", True)], "keywords": keywords, "lookback_days": int(settings.get("lookback_days", 30))}
    step(db, job, "plan", {"tool": "company_profile", "status": "ok", **initial_plan}, 5)
    # The agent chooses focus, missing information, and the retrieval query before tools execute.
    plan = llm.complete(workspace, "analysis_plan", f'''Plan a business-impact analysis for this company and decision role. Return {{"focus":["3 specific company exposures"],"research_query":"a query for bank research in English AND Russian","missing_data":["specific missing company data"],"checks":["checks to apply before publishing"]}}. Do not invent exposures. CONTEXT: {json_text(initial_plan)}''', job_id=job.id, max_tokens=1100)
    step(db, job, "agent_plan", {"tool": "plan_analysis", "status": "ok", "plan": plan}, 12)
    documents, diagnostics = collect_sources(sources)
    for diag in diagnostics:
        row = next((s for s in source_rows if s.id == diag["id"]), None)
        if row:
            row.payload = {**row.payload, "last_checked": now(), "health": diag["status"], "last_count": diag["count"], "error": diag.get("error", "")}
    existing = items(db, workspace.id, "article")
    seen = {r.key for r in existing}
    titles = {fingerprint(r.payload.get("title", "")) for r in existing}
    added = 0
    for doc in documents:
        f = fingerprint(doc["title"])
        if doc["url"] in seen or f in titles:
            continue
        record(db, workspace.id, "article", doc, key=doc["url"])
        seen.add(doc["url"])
        titles.add(f)
        added += 1
    step(db, job, "collect_and_deduplicate", {"tool": "collect_public_sources", "status": "ok", "collected": len(documents), "new": added, "duplicates": len(documents) - added, "diagnostics": diagnostics}, 30)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=initial_plan["lookback_days"])).isoformat(timespec="seconds").replace("+00:00", "Z")
    ranked = []
    exclude = settings.get("exclude_keywords", [])
    for row in items(db, workspace.id, "article"):
        p = row.payload
        if p.get("published_at") and p["published_at"] < cutoff:
            continue
        text = p.get("title", "") + " " + p.get("text", "")
        if any(x.lower() in text.lower() for x in exclude if x):
            continue
        score, reasons = relevance(text, profile, keywords, role)
        if score >= int(settings.get("min_relevance", 20)):
            ranked.append({"id": row.id, **p, "pre_score": score, "matched_features": reasons})
    ranked.sort(key=lambda x: x["pre_score"], reverse=True)
    already = {e.payload.get("article_id") for e in items(db, workspace.id, "event") if e.payload.get("decision_role") == role and e.payload.get("profile_version") == profile.get("version", 1)}
    candidates = [d for d in ranked if d["id"] not in already][:6]
    step(db, job, "rank", {"tool": "rank_by_company_and_role", "status": "ok", "candidate_count": len(ranked), "selected": [{"id": d["id"], "score": d["pre_score"], "features": d["matched_features"]} for d in candidates], "excluded_keywords": exclude}, 40)
    if not candidates:
        job.result = {"events": 0, "collected": added, "message": "No new relevant events in this window. Check source health or broaden the monitoring topics.", "diagnostics": diagnostics}
        return
    # Enrich selected headlines with full public text; the confidence reflects unavailable bodies.
    for doc in candidates:
        if doc.get("evidence_level") == "headline" and "news.google.com" not in doc.get("url", ""):
            try:
                b, t, u = fetch(doc["url"], timeout=12)
                full = read_document(b, t, u)
                if len(full.get("text", "")) > 200:
                    doc["text"] = full["text"][:11000]
                    doc["evidence_level"] = "full_text"
                    row = db.get(Item, doc["id"])
                    row.payload = {**row.payload, "text": doc["text"], "evidence_level": "full_text"}
            except Exception:
                pass
    bank = retrieve_bank(db, str(plan.get("research_query", "")) + " " + str(profile.get("exposures", "")) + " " + " ".join(d["title"] for d in candidates), limit=4, wid=workspace.id)
    step(db, job, "retrieve_bank_research", {"tool": "bm25_bilingual_research", "status": "ok" if bank else "insufficient", "evidence": bank, "missing_data": plan.get("missing_data", [])}, 52)
    inputs = [{k: d.get(k) for k in ["id", "title", "url", "text", "published_at", "source_name", "evidence_level", "pre_score", "matched_features"]} for d in candidates]
    schema = '''{"events":[{"article_id":"supplied id", "relevance":85, "sentiment":"risk|opportunity|mixed|neutral", "category":"macro|regulation|competition|technology|supply_chain|markets", "confidence":70, "time_horizon":"days|weeks|months", "profile_features":["exact profile field names"], "evidence_ids":["article id"], "bank_ids":["supplied bank id or none"], "bank_quote":"verbatim short excerpt in original language, or empty", "bank_page":1, "en":{"title":"business-focused headline", "fact":"only what the source reports", "why":"which exact company exposure makes it material", "impact":"causal mechanism and a conditional scenario with 2 or more factors", "bank_view":"dated bank position; explicitly historical when appropriate, or say no relevant bank research available", "actions":["specific action with a team/decision and timeframe"], "uncertainties":["what must be confirmed"]},"ru":{"title":"...","fact":"...","why":"...","impact":"...","bank_view":"...","actions":["..."],"uncertainties":["..."]}}]}'''
    prompt = f'''Today: {now()[:10]}. Company profile (user reviewed, unknown financials stay unknown): {json_text(profile)}. Decision role: {role}. Agent plan: {json_text(plan)}. NEWS EVIDENCE: {json_text(inputs)}. BANK RESEARCH EVIDENCE (OCR text can contain recognition errors; avoid exact figures if unclear): {json_text(bank)}.
Analyze each selected article, or omit if not relevant. Output ENGLISH and RUSSIAN interpretations using schema {schema}. At most 6 events. No generic advice; tie why/impact to actual profile features. Sources are not company facts unless the profile confirms them. If there is only a headline, cap confidence at 45 and state that the full text was unavailable; propose verification, not an unsupported action. Do not claim the company has loans or imports unless explicitly in profile exposures. Treat bank opinions as dated context, never current bank advice. Bank ids and quotes only when the supplied excerpt supports the claimed view. Relevance measures materiality for this company and role, NOT sentiment. Never fabricate monetary effects or percentages. No bank quote is preferable to a wrong citation. Each locale: fact ~40 words, why ~35, impact ~60, bank_view ~40, 1-2 actions, 1-2 uncertainties.'''
    result = llm.complete(workspace, "interpret_events", prompt, job_id=job.id, max_tokens=10500)
    proposed = result.get("events", [])
    step(db, job, "interpret", {"tool": "interpret_company_impact", "status": "ok", "draft_count": len(proposed), "profile_version": profile.get("version", 1)}, 72)
    # Independent second pass: the model must check the draft against the actual retrieved data.
    review = llm.complete(workspace, "verify_evidence", f'''Verify each proposed event against the supplied evidence. Reject unsupported facts, false bank attributions, invented company exposures, or mismatched references. Return {{"reviews":[{{"article_id":"", "supported":true, "issues":[], "confidence_cap":90}}]}}. Be strict: a headline cannot support details absent from it. Historical bank views must be explicitly dated. COMPANY: {json_text(profile)}. NEWS: {json_text(inputs)}. BANK: {json_text(bank)}. DRAFTS: {json_text(proposed)}''', job_id=job.id, max_tokens=1800)
    reviews = {r.get("article_id"): r for r in review.get("reviews", []) if isinstance(r, dict)}
    rejected = []
    accepted = []
    by_id = {d["id"]: d for d in candidates}
    bank_by_id = {b["id"]: b for b in bank}
    for event in proposed:
        aid = event.get("article_id")
        source = by_id.get(aid)
        verification = reviews.get(aid, {})
        if not source or not verification.get("supported") or not all(isinstance(event.get(lang), dict) and all(event[lang].get(k) for k in ["title", "fact", "why", "impact", "actions", "uncertainties"]) for lang in ["en", "ru"]):
            rejected.append({"article_id": aid, "issues": verification.get("issues", ["Schema or citation validation failed."])})
            continue
        bids = [b for b in event.get("bank_ids", []) if b in bank_by_id]
        quote = event.get("bank_quote", "")
        quote_valid = bool(quote and any(re.sub(r"\s+", " ", quote).strip().lower() in re.sub(r"\s+", " ", bank_by_id[b]["text"]).lower() for b in bids))
        if not quote_valid:
            bids = []
            event["bank_quote"] = ""
            event["en"]["bank_view"] = "No directly supporting bank excerpt was verified for this event."
            event["ru"]["bank_view"] = "Для этого события не удалось подтвердить прямую цитату из аналитики банка."
        confidence = min(max(0, int(event.get("confidence", 50))), int(verification.get("confidence_cap", 80)), 45 if source.get("evidence_level") == "headline" else 95)
        features = [x for x in event.get("profile_features", []) if x in profile and profile[x]]
        if not features:
            rejected.append({"article_id": aid, "issues": ["No supported company feature."]})
            continue
        event.update(evidence_ids=[aid], bank_ids=bids, confidence=confidence, relevance=max(0, min(100, int(event.get("relevance", source["pre_score"])))), profile_features=features, article=source, bank_evidence=[bank_by_id[b] for b in bids], profile_version=profile.get("version", 1), decision_role=role, job_id=job.id, verification=verification, published_at=source.get("published_at"), status="verified", generated_at=now(), is_demo=False)
        if event.get("sentiment") not in {"risk", "opportunity", "mixed", "neutral"}:
            event["sentiment"] = "neutral"
        key = f"{aid}:{role}:{profile.get('version', 1)}"
        saved = record(db, workspace.id, "event", event, key=key)
        accepted.append(saved)
    step(db, job, "verify", {"tool": "evidence_and_schema_verifier", "status": "ok", "accepted": len(accepted), "rejected": rejected, "reviews": review.get("reviews", [])}, 90)
    # Adapt once when the independent checker rejects all drafts: leave a clear gap, don't publish guesses.
    if rejected:
        step(db, job, "adapt", {"tool": "request_better_evidence", "status": "needs_evidence", "action": "Unsupported drafts withheld. Add a full-text source or a company exposure and retry.", "rejected_count": len(rejected)}, 94)
    for saved in accepted:
        p = saved.payload
        if p["relevance"] >= int(settings.get("alert_threshold", 80)):
            record(db, workspace.id, "alert", {"event_id": saved.id, "en": p["en"]["title"], "ru": p["ru"]["title"], "sentiment": p["sentiment"], "relevance": p["relevance"], "read_by": []}, key=saved.id)
            for member in db.query(Member).filter_by(workspace_id=workspace.id).all():
                user = db.get(User, member.user_id)
                if user and user.verified and user.preferences.get("email_alerts"):
                    lang = user.preferences.get("locale", "en")
                    enqueue(db, workspace.id, user.email, p[lang]["title"], f'<p>{html.escape(p[lang]["why"])}</p><p>{html.escape(p[lang]["impact"])}</p>', locale=lang, key=f"alert:{saved.id}:{user.id}")
    workspace.settings = {**workspace.settings, "last_run": now(), "last_job_id": job.id}
    job.result = {"events": len(accepted), "collected": added, "rejected": len(rejected), "diagnostics": diagnostics}


def period_bounds(period, end=None):
    if period not in {"day", "week", "month"}:
        raise ValueError("Choose day, week or month.")
    finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(timezone.utc)
    finish = finish.replace(tzinfo=finish.tzinfo or timezone.utc)
    start = finish - timedelta(days={"day": 1, "week": 7, "month": 30}[period])
    return start.isoformat(timespec="seconds").replace("+00:00", "Z"), finish.isoformat(timespec="seconds").replace("+00:00", "Z")


def generate_brief(db, job, workspace):
    period = job.input.get("period", "day")
    role = job.input.get("decision_role", "ceo")
    start, end = period_bounds(period, job.input.get("end"))
    events = [pack(e) for e in items(db, workspace.id, "event") if e.payload.get("decision_role", "ceo") == role and start <= (e.payload.get("published_at") or e.created_at) <= end]
    events = sorted(events, key=lambda e: e.get("relevance", 0), reverse=True)[:30]
    step(db, job, "brief_window", {"status": "ok", "period": period, "start": start, "end": end, "event_ids": [e["id"] for e in events], "decision_role": role}, 20)
    if not events:
        raise ValueError("No verified events in this period for your role. Run monitoring or select a longer period.")
    simplified = [{"id": e["id"], "published_at": e.get("published_at"), "relevance": e["relevance"], "sentiment": e["sentiment"], "en": e["en"], "ru": e["ru"]} for e in events]
    result = llm.complete(workspace, "executive_brief", f'''Write an executive {period} brief from these VERIFIED event analyses for {workspace.name}, role {role}. Window: {start} to {end}; never add events outside it. Company: {json_text(workspace.profile)}. EVENTS: {json_text(simplified)}. Return {{"en":{{"title":"an informative editorial title", "executive_summary":"100 words connecting developments, company consequences and priorities", "themes":[{{"title":"", "analysis":"concrete cross-event causal synthesis", "event_ids":["actual IDs"]}}], "priorities":[{{"action":"specific owner + next step", "timeframe":"", "event_ids":["actual IDs"]}}], "watch_next":["specific measurable trigger"], "gaps":["what we still do not know"]}}, "ru":{{same translated structure}}}}. At most 3 themes, 3 priorities, 3 watch_next. Day = urgent choices; week = patterns/changes between events; month = strategic scenarios and next-month agenda. No invented trend, numbers or data coverage. If few events say coverage is limited. Every theme and action must cite an event. Distinguish dated bank research from current events.''', job_id=job.id, max_tokens=4300)
    allowed = {e["id"] for e in events}
    for lang in ["en", "ru"]:
        section = result.get(lang, {})
        if not section.get("executive_summary") or not section.get("title"):
            raise ValueError("The brief did not pass completeness validation. Retry generation.")
        for field in ["themes", "priorities"]:
            valid = []
            for row in section.get(field, []):
                refs = [i for i in row.get("event_ids", []) if i in allowed]
                if refs:
                    valid.append({**row, "event_ids": refs})
            section[field] = valid
        if not section.get("themes") or not section.get("priorities"):
            raise ValueError("The brief did not include valid evidence references. Retry generation.")
    payload = {**result, "period": period, "start": start, "end": end, "event_ids": list(allowed), "decision_role": role, "event_count": len(events), "source_count": len({e.get("article", {}).get("source_name") for e in events}), "risk_count": sum(e["sentiment"] == "risk" for e in events), "opportunity_count": sum(e["sentiment"] == "opportunity" for e in events), "job_id": job.id, "generated_at": now(), "is_demo": workspace.demo}
    brief = record(db, workspace.id, "brief", payload)
    step(db, job, "brief_verify", {"status": "ok", "tool": "validate_event_references", "brief_id": brief.id, "event_count": len(events)}, 100)
    job.result = {"brief_id": brief.id}
    if job.input.get("scheduled"):
        for member in db.query(Member).filter_by(workspace_id=workspace.id).all():
            user = db.get(User, member.user_id)
            if user and user.verified and user.preferences.get("email_briefs"):
                lang = user.preferences.get("locale", "en")
                enqueue(db, workspace.id, user.email, result[lang]["title"], '<p>' + html.escape(result[lang]["executive_summary"]) + '</p>', locale=lang, key=f"brief:{brief.id}:{user.id}")


def process_job(job_id):
    with DB() as db:
        job = db.get(Job, job_id)
        workspace = db.get(Workspace, job.workspace_id)
        if not workspace:
            job.status, job.error, job.finished_at = "failed", "Workspace no longer exists.", now()
            db.commit()
            return
        job.status, job.started_at = "running", now()
        db.commit()
        try:
            if job.kind == "website":
                analyze_website(db, job, workspace)
            elif job.kind == "analyze":
                run_analysis(db, job, workspace)
            elif job.kind == "brief":
                generate_brief(db, job, workspace)
            else:
                raise ValueError("Unknown job type.")
            job.status, job.progress = "completed", 100
        except Exception as exc:
            db.rollback()
            job = db.get(Job, job_id)
            job.status = "failed"
            # Do not persist upstream URLs/headers that may contain credentials.
            job.error = str(exc)[:600] if isinstance(exc, (ValueError, llm.ModelUnavailable)) else "The run could not complete. Check source health and retry."
            job.steps = [*job.steps, {"name": "failure", "at": now(), "status": "error", "message": job.error}]
        job.finished_at = now()
        db.commit()


_stop = threading.Event()
_thread = None


def scheduler_tick(db):
    utc = datetime.now(timezone.utc)
    for workspace in db.query(Workspace).filter_by(onboarded=True, demo=False).all():
        settings = workspace.settings
        if not settings.get("auto_monitor", True):
            continue
        last = settings.get("last_scheduled", "")
        interval = max(30, int(settings.get("interval_minutes", 360)))
        if not last or (utc - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() >= interval * 60:
            owner = db.query(Member).filter_by(workspace_id=workspace.id, role="owner").first()
            if owner:
                create_job(db, workspace.id, owner.user_id, "analyze", {"decision_role": owner.decision_role, "scheduled": True})
                workspace.settings = {**settings, "last_scheduled": now()}
                db.commit()
        for period in settings.get("scheduled_briefs", []):
            # Daily at 07:00 UTC (10:00 Moscow); weekly Monday; monthly first day.
            if utc.hour < 7 or (period == "week" and utc.weekday() != 0) or (period == "month" and utc.day != 1):
                continue
            key = f"scheduled:{period}:{utc.date()}"
            if db.query(Item).filter_by(workspace_id=workspace.id, kind="schedule", key=key).first():
                continue
            owner = db.query(Member).filter_by(workspace_id=workspace.id, role="owner").first()
            if owner:
                create_job(db, workspace.id, owner.user_id, "brief", {"period": period, "decision_role": owner.decision_role, "scheduled": True})
                record(db, workspace.id, "schedule", {"period": period}, key=key)
                db.commit()


def worker_loop():
    last_tick = 0
    while not _stop.is_set():
        try:
            with DB() as db:
                if time.monotonic() - last_tick > 60:
                    scheduler_tick(db)
                    last_tick = time.monotonic()
                job = db.query(Job).filter_by(status="queued").order_by(Job.created_at).first()
                jid = job.id if job else None
            if jid:
                process_job(jid)
            else:
                deliver_pending()
                _stop.wait(2)
        except Exception:
            import logging
            logging.getLogger("signaldesk.worker").exception("Worker tick failed")
            _stop.wait(5)


def start_worker():
    global _thread
    if _thread and _thread.is_alive():
        return
    # Single API process only; interrupted jobs become explicit failures, safe to retry.
    with DB() as db:
        for job in db.query(Job).filter_by(status="running").all():
            job.status, job.error, job.finished_at = "failed", "Server restarted during analysis. Please retry this run.", now()
        db.commit()
    _stop.clear()
    _thread = threading.Thread(target=worker_loop, name="signaldesk-worker", daemon=True)
    _thread.start()


def stop_worker():
    _stop.set()
