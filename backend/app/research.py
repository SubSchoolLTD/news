from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .db import Item, items, pack, record

STOP = set("the and for with that this from have will are has was not but into which their your about also they its more than на по из для что как при это или его она они если чем без под над уже все так может также будет были этих этой этом компании company business news bank банка альфа alfa".split())
GROUPS = [
    "rate rates interest borrowing debt credit financing refinancing ставка ставки ставку кредит кредитование долг финансирование рефинансирование",
    "inflation price prices costs margin инфляция инфляции цены цен стоимость маржа издержки",
    "education edtech teaching teacher learning training student course school образование образования обучение обучения учитель ученик курс школа",
    "technology software digital ai cloud saas технологии программное цифровой облако искусственный",
    "labor labour wage wages employment staff зарплат зарплаты труд труда работников персонал занятость",
    "fx currency currencies exchange dollar ruble import export валют валюты курс рубль доллар импорт экспорт",
    "regulation compliance law data privacy regulatory закон регулирование требования персональные данные",
    "steel metals mining commodity commodities iron gold copper металл сталь сырье золото медь",
    "oil energy gas electricity нефть газ энергия электроэнергия",
    "consumption consumer demand retail household потребление потребления спрос спроса розница население",
    "deposit liquidity treasury cash bonds deposits депозит ликвидность казначейство облигации денежные",
    "transport logistics supply shipping logistics поставки логистика транспорт перевозки",
]


def tokens(text):
    words = re.findall(r"[\wа-яё]+", str(text).lower())
    return [w[:7] if len(w) > 8 else w for w in words if len(w) > 2 and w not in STOP and not w.isdigit()]


def expand(text):
    original = set(tokens(text))
    expanded = set(original)
    for group in GROUPS:
        group_tokens = set(tokens(group))
        if original & group_tokens:
            expanded |= group_tokens
    return expanded


def relevance(text, profile, keywords=None, decision_role="ceo"):
    focus = " ".join(str(profile.get(k, "")) for k in ["name", "industry", "description", "activities", "customers", "regions", "competitors", "counterparties", "priorities", "exposures"])
    context = profile.get("case_context", {})
    group_industries = " ".join(m.get("industry", "") for m in context.get("group", {}).get("members", []))
    payment_industries = " ".join(link.get("industry", "") for link in context.get("payments", {}).get("external_links", []) if link.get("profile_available"))
    focus += " " + group_industries + " " + payment_industries + " " + " ".join(context.get("trade_countries", []))
    query = expand(focus + " " + " ".join(keywords or []))
    ts = set(tokens(text))
    common = ts & query
    reasons = []
    score = min(65, len(common) * 4)
    if group_industries and ts & expand(group_industries):
        reasons.append("group member industry (transmission unconfirmed)")
    if payment_industries and ts & expand(payment_industries):
        reasons.append("payment counterparty industry (relationship unconfirmed)")
    for field, label in [("industry", "industry"), ("exposures", "business exposures"), ("priorities", "strategic priorities"), ("regions", "operating regions"), ("counterparties", "counterparties")]:
        matches = ts & expand(str(profile.get(field, "")))
        if matches:
            reasons.append(label)
            score += 7
    for keyword in keywords or []:
        if keyword.lower() in text.lower():
            score += 10
            reasons.append(keyword)
    role_focus = {"cfo": "currency debt rate financing inflation liquidity", "treasury": "currency deposits bonds liquidity rate", "accountant": "regulation tax law reporting", "ceo": "demand competition strategy labor", "owner": "growth margins financing risk", "strategy": "competition market growth technology"}
    if ts & expand(role_focus.get(decision_role, "")):
        score += 6
    return min(100, score), list(dict.fromkeys(reasons))[:5]


def retrieve_bank(db, query, limit=4, wid=None):
    """Small-corpus BM25 retrieval with bilingual query expansion and page provenance."""
    rows = items(db, "global", "bank") + (items(db, wid, "bank") if wid else [])
    chunks = []
    for row in rows:
        p = row.payload
        for page in p.get("pages_content") or [{"page": 1, "text": p.get("text", "")}]:
            text = page["text"]
            # Keep overlapping windows so a sentence near a boundary stays retrievable.
            for start in range(0, len(text), 1500):
                fragment = text[start:start + 2100]
                if len(fragment.strip()) > 70:
                    chunks.append({"id": row.id, "page": page["page"], "title": p["title"], "url": p["url"], "published_at": p.get("published_at"), "date_precision": p.get("date_precision", "day"), "text": fragment, "page_text": text[:9000], "ocr": p.get("ocr", False), "user_attributed": p.get("user_attributed", False), "tokens": tokens(fragment)})
    if not chunks:
        return []
    query_terms = expand(query)
    n = len(chunks)
    df = Counter(w for c in chunks for w in set(c["tokens"]))
    avgdl = sum(len(c["tokens"]) for c in chunks) / n
    ranked = []
    for c in chunks:
        tf = Counter(c.pop("tokens"))
        dl = sum(tf.values())
        score = sum(math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5)) * (tf[w] * 2.2) / (tf[w] + 1.2 * (0.25 + 0.75 * dl / max(1, avgdl))) for w in query_terms if w in tf)
        if score > 0:
            c["retrieval_score"] = round(score, 2)
            date = c.get("published_at")
            c["age_days"] = (datetime.now(timezone.utc).date() - datetime.fromisoformat(date[:10]).date()).days if date else None
            ranked.append(c)
    # Diversify across documents while retaining an evidence page from each.
    selected, seen = [], set()
    for c in sorted(ranked, key=lambda c: c["retrieval_score"], reverse=True):
        if c["id"] not in seen:
            c["text"] = c.pop("page_text")
            selected.append(c)
            seen.add(c["id"])
        if len(selected) >= limit:
            break
    return selected


def seed_research(db):
    root = Path(__file__).resolve().parents[2] / "data" / "bank"
    if not root.exists():
        root = Path(__file__).resolve().parents[1] / "data" / "bank"
    for path in root.glob("*.json"):
        data = json.loads(path.read_text())
        if len(data.get("text", "").strip()) > 200:
            record(db, "global", "bank", data, key=data["id"])
    db.commit()
