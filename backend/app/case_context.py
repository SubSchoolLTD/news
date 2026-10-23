"""Interpret anonymised bank fields using the organiser's webinar clarifications.

Original uploads remain evidence. This module produces bounded, typed context;
it never treats payment links, servicing locations or missing values as markets.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import re


def value(row, *names):
    fields = {str(k).strip().upper().replace("_", ""): v for k, v in row.items()}
    for name in names:
        result = fields.get(name.upper().replace("_", ""))
        if result is not None and str(result).strip().lower() not in {"", "null", "none", "nan"}:
            return str(result).strip()
    return ""


def number(raw):
    try:
        result = Decimal(str(raw).replace(" ", "").replace(",", "."))
        return float(result) if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def client_id(row):
    return value(row, "SYNTHETIC_U")


def status(row):
    raw = value(row, "CL_TYPE").upper().replace(" ", "_")
    return {"CLIENT": "client", "PROSPECT": "prospect", "CLOSE_CLIENT": "closed", "CLOSED_CLIENT": "closed"}.get(raw, "unknown")


def dataset_report(rows):
    counts = Counter(client_id(r) for r in rows if client_id(r))
    return {"duplicate_ids": [k for k, n in counts.items() if n > 1],
            "missing_revenue_rows": sum(number(value(r, "REVENUE_COMPANY")) in {None, 0, 1000} for r in rows),
            "active_clients": sum(status(r) == "client" for r in rows),
            "revenue_year": 2025, "revenue_currency": "RUB"}


def company_choices(rows, query=""):
    counts = Counter(client_id(r) for r in rows)
    result = []
    for row in rows:
        cid = client_id(row)
        industry = value(row, "MAINOKVED_NAME")
        if cid and counts[cid] == 1 and status(row) in {"client", "unknown"} and query.lower() in (cid + " " + industry).lower():
            result.append({"id": cid, "industry": industry, "client_status": status(row)})
    return result[:30]


def build_context(selected, companies, payments):
    cid = client_id(selected)
    revenue = number(value(selected, "REVENUE_COMPANY"))
    warnings = []
    if revenue in {None, 0, 1000}:
        revenue = None
        warnings.append("Revenue is missing or an organiser-confirmed placeholder; do not estimate scale from it.")
    group_id = value(selected, "GROUP_ID")
    counts = Counter(client_id(r) for r in companies)
    known = {client_id(r): r for r in companies if counts[client_id(r)] == 1}
    members = [{"id": client_id(r), "industry": value(r, "MAINOKVED_NAME"), "client_status": status(r)} for r in known.values() if group_id and value(r, "GROUP_ID") == group_id and client_id(r) != cid]
    links, self_amount, self_count, invalid = {}, 0.0, 0, 0
    # Re-uploaded identical payment rows must not inflate the context.
    seen = set()
    for row in payments:
        payer, recipient = value(row, "PAYER"), value(row, "BENEFICIARY")
        if cid not in {payer, recipient}:
            continue
        amount, count = number(value(row, "PAY_AMT")), number(value(row, "PAY_CNT"))
        key = (payer, recipient, amount, count)
        if key in seen:
            continue
        seen.add(key)
        if amount is None or count is None or not count.is_integer():
            invalid += 1
            continue
        if payer == recipient:
            self_amount += amount
            self_count += int(count)
            continue
        other = recipient if payer == cid else payer
        direction = "outgoing" if payer == cid else "incoming"
        link = links.setdefault((other, direction), {"counterparty_id": other, "direction": direction, "amount_rub": 0.0, "operation_count": 0,
            "profile_available": other in known, "industry": value(known.get(other, {}), "MAINOKVED_NAME"),
            "same_group": bool(group_id and other in known and value(known[other], "GROUP_ID") == group_id), "relationship_type": "unknown"})
        link["amount_rub"] += amount
        link["operation_count"] += int(count)
    if invalid:
        warnings.append(f"{invalid} related payment rows have invalid amount/count and were excluded.")
    warnings.extend(["Servicing city/region is not evidence of operating or customer geography.",
        "Payment links show financial interaction, not a customer/supplier contract. Missing counterparties remain unknown.",
        "Company revenue is for 2025 in RUB; it is not group revenue. Do not infer group size or sum incomplete members."])
    context = {"schema_version": 1, "client_id": cid, "client_status": status(selected),
        "revenue": {"amount": revenue, "currency": "RUB", "year": 2025, "scope": "legal_entity"},
        "servicing_location": {"city": value(selected, "CityName", "CITY"), "region": value(selected, "RCName", "REGION")},
        "trade_countries": [s.strip() for s in re.split(r"[,;|]", value(selected, "FTS_COUNTRY_NAME")) if s.strip()],
        "group": {"id": group_id or None, "basis": "organiser ownership/management grouping", "members": members[:20], "member_count_in_upload": len(members), "complete": False},
        "payments": {"currency": "RUB", "period": "since January 1; reporting year not supplied", "self_transfers": {"amount_rub": self_amount, "operation_count": self_count},
            "external_links": sorted(links.values(), key=lambda x: x["amount_rub"], reverse=True)[:20], "external_link_count": len(links), "invalid_rows": invalid},
        "limitations": warnings}
    clean = dict(selected)
    for key in clean:
        if key.upper() == "REVENUE_COMPANY":
            clean[key] = revenue
    return context, clean
