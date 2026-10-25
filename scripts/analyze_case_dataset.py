"""Reproduce the presentation's aggregate case-data analysis without publishing raw data.

The original organiser CSVs remain local. Row counts describe the provided files,
not a representative sample of Russian businesses or a complete corporate group.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path


def rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(8192)
        stream.seek(0)
        yield from csv.DictReader(stream, delimiter=";" if sample.splitlines()[0].count(";") > sample.splitlines()[0].count(",") else ",")


def number(value):
    try:
        result = Decimal((value or "").strip().replace(",", "."))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def analyze(companies, payments, people=None):
    clients = list(rows(companies))
    ids = Counter(row["SYNTHETIC_U"] for row in clients)
    unique = [row for row in clients if ids[row["SYNTHETIC_U"]] == 1]
    active = [row for row in unique if row["CL_TYPE"] == "CLIENT"]
    large = [row for row in active if (number(row["REVENUE_COMPANY"]) or 0) > 15_000_000_000]
    flag = lambda row, field: number(row.get(field)) == 1
    company = {
        "rows": len(clients), "unique_ids": len(ids),
        "ambiguous_duplicate_ids": sum(n > 1 for n in ids.values()),
        "ambiguous_rows_excluded_from_segment": sum(n for n in ids.values() if n > 1),
        "types_by_row": dict(Counter(row["CL_TYPE"] for row in clients)),
        "active_unique_unambiguous_rows": len(active),
        "sentinel_1000_rows": sum(number(row["REVENUE_COMPANY"]) == 1000 for row in clients),
        "large_active_legal_entities": len(large),
        "large_active_features": {
            "credit": sum(flag(row, "CL_PRODUCT_LOA_MARK") for row in large),
            "leasing": sum(flag(row, "CL_PRODUCT_LEA_MARK") for row in large),
            "foreign_trade": sum(flag(row, "FTS_FLAG") for row in large),
            "credit_or_leasing": sum(flag(row, "CL_PRODUCT_LOA_MARK") or flag(row, "CL_PRODUCT_LEA_MARK") for row in large),
        },
    }
    payment = {"rows": 0, "self_rows": 0, "rows_with_missing_counterparty_profile": 0}
    total = Decimal(0)
    own = Decimal(0)
    for row in rows(payments):
        payment["rows"] += 1
        amount = number(row["PAY_AMT"])
        if amount is not None and amount >= 0:
            total += amount
        if row["PAYER"] == row["BENEFICIARY"]:
            payment["self_rows"] += 1
            if amount is not None and amount >= 0:
                own += amount
        if row["PAYER"] not in ids or row["BENEFICIARY"] not in ids:
            payment["rows_with_missing_counterparty_profile"] += 1
    payment.update(total_amount_rub=str(total), self_amount_rub=str(own), self_amount_share_pct=float(100 * own / total) if total else None)
    files = [companies, payments] + ([people] if people else [])
    report = {"companies": company, "payments": payment,
              "sources": [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files],
              "method": "CLIENT only; ambiguous IDs excluded; 2025 legal-entity revenue > RUB 15bn; no group-revenue inference. Payment rows are observed transfers, not proven operational dependencies."}
    if people:
        report["physical_person_links"] = {"rows": sum(1 for _ in rows(people))}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", type=Path, required=True)
    parser.add_argument("--payments", type=Path, required=True)
    parser.add_argument("--people-links", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze(args.companies, args.payments, args.people_links)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Aggregate analysis saved to {args.output}")
