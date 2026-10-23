"""Search public indexes and verify publishers. No catalogue of recommended outlets."""
from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import feedparser
from bs4 import BeautifulSoup

from . import llm
from .collect import allowed_by_robots, canonical, collect_source, extract_html, fetch
from .db import Item, now, record
from .security import safe_url


def profile_fingerprint(profile):
    fields = {k: profile.get(k) for k in ("website", "industry", "activities", "customers", "regions", "exposures", "priorities", "keywords")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def saved_discovery(db, workspace):
    profile = workspace.settings.get("profile_draft") or workspace.profile
    row = db.query(Item).filter_by(workspace_id=workspace.id, kind="source_discovery", key=profile_fingerprint(profile)).first()
    return row.payload if row else {"sources": [], "status": "not_searched"}


def search_index(query):
    """Official, key-free GDELT DOC API; query terms contain public topics/markets only."""
    args = {"query": query, "mode": "artlist", "format": "json", "timespan": "30d", "maxrecords": 50, "sort": "hybridrel"}
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(args)
    data, _, _ = fetch(url, timeout=12)
    try:
        result = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("The news search index did not return usable results. Retry source discovery.")
    return [{"url": a.get("url", ""), "title": a.get("title", ""), "country": a.get("sourcecountry", ""), "language": a.get("language", ""), "seen_at": a.get("seendate", ""), "provider": "GDELT DOC 2.0", "query": query} for a in result.get("articles", [])]


def search_web(query):
    """Public HTML search fallback; a challenge is an error, never bypassed."""
    data, _, _ = fetch("https://html.duckduckgo.com/html/?" + urlencode({"q": query}), timeout=20)
    soup = BeautifulSoup(data, "html.parser")
    if soup.select("#challenge-form, .anomaly-modal"):
        raise ValueError("The web search provider requires a challenge. No results were substituted.")
    found = []
    for row in soup.select(".result")[:12]:
        a = row.select_one(".result__a")
        if not a:
            continue
        url = a.get("href", "")
        if "duckduckgo.com/l/" in url:
            url = parse_qs(urlsplit(url).query).get("uddg", [""])[0]
        found.append({"url": url, "title": a.get_text(" ", strip=True), "snippet": row.get_text(" ", strip=True)[:700], "country": "", "provider": "DuckDuckGo web search", "query": query})
    return found


def search_directory(query):
    """Research actual organisations/official links through MediaWiki's public API."""
    base = "https://en.wikipedia.org/w/api.php?"
    data, _, _ = fetch(base + urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"}), timeout=12)
    pages = json.loads(data).get("query", {}).get("search", [])
    if not pages:
        return []
    data, _, _ = fetch(base + urlencode({"action": "query", "prop": "extlinks", "pageids": "|".join(str(p["pageid"]) for p in pages[:2]), "ellimit": 50, "format": "json"}), timeout=12)
    result = []
    for page in json.loads(data).get("query", {}).get("pages", {}).values():
        for link in page.get("extlinks", []):
            url = link.get("*", "")
            if urlsplit(url).scheme in {"https", "http"} and not re.search(r"\.(pdf|jpg|png|zip)(?:\?|$)", url, re.I):
                result.append({"url": url, "title": page.get("title", ""), "country": "", "provider": "MediaWiki public source research", "query": query, "directory_page": "https://en.wikipedia.org/?curid=" + str(page["pageid"])})
    return result[:30]


def verify_publisher(hit):
    safe_url(hit["url"])
    root = urlsplit(hit["url"])
    homepage = hit["url"] if hit["provider"] == "Public publisher website inspection" else f"{root.scheme}://{root.netloc}/"
    if not allowed_by_robots(homepage):
        raise ValueError("Publisher robots policy blocks verification or is unavailable.")
    data, _, final = fetch(homepage, timeout=10)
    page = extract_html(data, final)
    soup = BeautifulSoup(data, "html.parser")
    site_meta = soup.select_one('meta[property="og:site_name"]')
    site_name = (site_meta.get("content") if site_meta else None) or root.hostname
    if not page["feeds"]:
        for link in soup.select("a[href]"):
            href = urljoin(final, link.get("href", ""))
            if urlsplit(href).hostname == root.hostname and re.search(r"/(newsroom|news|press|media)(?:/|$)", urlsplit(href).path, re.I):
                try:
                    if allowed_by_robots(href):
                        child, _, child_url = fetch(href, timeout=10)
                        page = extract_html(child, child_url)
                        soup = BeautifulSoup(child, "html.parser")
                        final = child_url
                except Exception:
                    pass
                break
    # RSS addresses must be advertised by the actual page; never guess /feed paths.
    feeds = list(page["feeds"])
    for a in soup.select("a[href]"):
        href = urljoin(final, a.get("href", ""))
        if re.search(r"rss|\.xml(?:\?|$)|/feed/?$", href, re.I) and urlsplit(href).hostname == urlsplit(final).hostname:
            feeds.append(href)
    candidates = list(dict.fromkeys(feeds))[:3] + [final]
    for address in candidates:
        try:
            source = {"id": "discovery", "name": site_name, "url": address, "type": "rss" if address in feeds else "html", "kind": "news", "limit": 6, "respect_robots": True}
            docs = collect_source(source)
            if len(docs) < 2:
                continue
            dates = [d["published_at"] for d in docs if d.get("published_at")]
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat().replace("+00:00", "Z")
            if not dates or max(dates) < cutoff:
                continue  # A working archive/testimonial feed is not current news coverage.
            return {**source, "name": source["name"][:150], "publisher": root.hostname, "country": hit.get("country", ""), "target_market": hit.get("target_market", ""), "discovered_from": hit["url"], "search_provider": hit["provider"], "search_query": hit["query"], "search_title": hit["title"], "verified_at": now(), "sample_count": len(docs), "latest_publication": max(dates) if dates else None, "sample_headlines": [d["title"] for d in docs], "sample_urls": [d["url"] for d in docs]}
        except Exception:
            continue
    raise ValueError("No collectable advertised feed or news page was verified.")


def discover_sources(db, job, workspace, progress):
    profile = workspace.settings.get("profile_draft") or workspace.profile
    fingerprint = profile_fingerprint(profile)
    context = {k: profile.get(k) for k in ("industry", "activities", "customers", "regions", "exposures", "priorities", "keywords")}
    progress("source_search_plan", {"status": "running", "company_context": context}, 8)
    plan = llm.complete(workspace, "source_search_plan", f'''Plan source discovery for this reviewed company context: {json.dumps(context, ensure_ascii=False)}. Return {{"markets":["confirmed market names only"],"publisher_candidates":[{{"url":"publisher homepage, not a guessed feed","market":"confirmed market this candidate is intended for"}}],"queries":[{{"news_query":"GDELT keyword query", "web_query":"plain web search for specialist news or an official regulator and an RSS feed", "directory_query":"2-4 word public encyclopedia search: industry, market, research or media"}}]}}. At most 2 queries, covering different confirmed markets or business drivers. Also propose 6-8 real specialist or official publisher homepages across those markets for public website inspection. These are unverified search leads only, not recommendations: never invent an RSS address. Their feeds and actual publications will be fetched and checked independently. Avoid general media when a specialist/primary source exists. Never default to Russia because the UI or bank research is Russian. Do not search for company revenue, private counterparties or other confidential values. GDELT syntax: (education OR edtech) sourcecountry:australia sourcelang:english; sourcecountry uses full English country name without spaces (unitedstates, unitedkingdom, australia, russia). Use one country per query. Choose broad industry terms, not all monitoring keywords ANDed together. If geography is unknown, omit sourcecountry and disclose unknown market. Prefer the source language used in the confirmed market. web_query must use broad industry + market terms, never site: restrictions.''', job_id=job.id, max_tokens=1400)
    queries = plan.get("queries", [])[:2]
    if not queries:
        raise ValueError("No source-search queries were produced. Review company industry and regions.")
    progress("search_public_indexes", {"status": "running", "markets": plan.get("markets", []), "queries": queries}, 20)
    hits, diagnostics = [], []
    for i, query in enumerate(queries):
        if i:
            time.sleep(5.1)  # GDELT's public per-IP request interval.
        q = str(query.get("news_query", ""))[:240]
        try:
            hits.extend(search_index(q))
        except Exception as exc:
            diagnostics.append({"provider": "GDELT", "query": q, "error": str(exc)[:180]})
        if query.get("web_query"):
            try:
                hits.extend(search_web(str(query.get("web_query", ""))[:240]))
            except Exception as exc:
                diagnostics.append({"provider": "Web search", "error": str(exc)[:180]})
        if len(hits) < 6:
            markets = plan.get("markets") or [""]
            market = str(markets[min(i, len(markets)-1)])
            industry_term = str(context.get("industry") or "business").split()[0]
            directory_query = str(query.get("directory_query") or f"{industry_term} {market} research news")
            try:
                hits.extend(search_directory(directory_query[:200]))
            except Exception as exc:
                diagnostics.append({"provider": "MediaWiki source research", "error": str(exc)[:180]})
    index_result_count = len(hits)
    # Model-suggested URLs are only search leads. Real page/feed inspection below
    # is mandatory, and the UI records this provenance separately from index hits.
    for lead in plan.get("publisher_candidates", [])[:8]:
        hits.append({"url": str(lead.get("url", "")), "title": "Unverified publisher lead", "country": "", "target_market": str(lead.get("market", "")), "provider": "Public publisher website inspection", "query": str(lead.get("market", ""))})
    # Keep publishers from each searched market and never trust search-provided URLs blindly.
    unique = {}
    for hit in hits:
        try:
            safe_url(hit["url"], resolve=False)
            host = urlsplit(hit["url"]).hostname
            if host and host not in unique:
                unique[host] = hit
        except ValueError:
            continue
    if not unique:
        progress("search_unavailable", {"status": "error", "diagnostics": diagnostics}, 40)
        raise ValueError("No public source search results are available. Retry discovery or add a trusted source manually. No default outlets were substituted.")
    buckets = {}
    for hit in unique.values():
        buckets.setdefault(hit["query"], []).append(hit)
    candidates = []
    while buckets and len(candidates) < 12:
        for key in list(buckets):
            candidates.append(buckets[key].pop(0))
            if not buckets[key]:
                del buckets[key]
            if len(candidates) == 12:
                break
    progress("verify_discovered_publishers", {"status": "running", "index_results": index_result_count, "publisher_leads": len(plan.get("publisher_candidates", [])), "publishers": [urlsplit(h["url"]).hostname for h in candidates]}, 45)
    verified = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(verify_publisher, h): h for h in candidates}
        for future in as_completed(futures):
            hit = futures[future]
            try:
                verified.append(future.result())
            except Exception as exc:
                diagnostics.append({"publisher": urlsplit(hit["url"]).hostname, "error": str(exc)[:180]})
    normal = lambda s: re.sub(r"[^a-z]", "", str(s).lower())
    missing = [m for m in plan.get("markets", []) if not any(normal(m) in {normal(s.get("target_market")), normal(s.get("country"))} for s in verified)]
    if missing:
        progress("adapt_source_search", {"status": "running", "missing_markets": missing, "failed_publishers": diagnostics}, 66)
        alternatives = llm.complete(workspace, "repair_source_discovery", f'''Public website inspection found no collectable source for these markets: {json.dumps(missing)}. Company: {json.dumps(context, ensure_ascii=False)}. Failed publishers: {json.dumps(diagnostics)}. Return {{"publisher_candidates":[{{"url":"actual publisher homepage or specialist section, NOT a guessed RSS path","market":"one missing market"}}]}}. Propose up to 5 different reputable specialist or primary publishers for the missing markets only. Research institutes, trade publications and professional associations are useful alternatives when government sites block bots. Avoid every failed host. A real news section is allowed if the homepage is too broad. These are unverified leads that will be fetched; never claim they work. Do not invent domains.''', job_id=job.id, max_tokens=900)
        repair_hits = []
        for lead in alternatives.get("publisher_candidates", [])[:5]:
            hit = {"url": str(lead.get("url", "")), "title": "Adaptive publisher lead", "country": "", "target_market": lead.get("market", ""), "provider": "Public publisher website inspection", "query": str(lead.get("market", ""))}
            try:
                safe_url(hit["url"], resolve=False)
                if urlsplit(hit["url"]).hostname not in unique:
                    repair_hits.append(hit)
            except ValueError:
                continue
        with ThreadPoolExecutor(max_workers=3) as pool:
            tasks = {pool.submit(verify_publisher,h):h for h in repair_hits}
            for task in as_completed(tasks):
                try:
                    verified.append(task.result())
                except Exception as exc:
                    diagnostics.append({"publisher":urlsplit(tasks[task]["url"]).hostname,"error":str(exc)[:180]})
    if not verified:
        progress("source_verification_failed", {"status": "error", "diagnostics": diagnostics}, 75)
        raise ValueError("Search found publishers, but no working feed or news page passed collection checks. Add a source manually or retry.")
    choices = [{"id": f"S{i+1}", **{k: v for k, v in s.items() if k != "id"}} for i, s in enumerate(verified)]
    progress("rank_verified_sources", {"status": "running", "candidates": choices}, 80)
    ranked = llm.complete(workspace, "rank_sources", f'''Choose up to 5 genuinely useful monitoring sources from these VERIFIED candidates, using only their S-prefixed IDs. Context: {json.dumps(context, ensure_ascii=False)}. Candidates: {json.dumps(choices, ensure_ascii=False)}. Return {{"sources":[{{"id":"S1","eligible":true,"reason":{{"en":"one concise sentence explaining actual coverage useful to this company and market","ru":"same in Russian"}}}}]}}. Return ONLY accepted sources, eligible=true; omit every rejected source entirely. Reject promotional pages, testimonials, archives, unrelated markets and broad outlets whose sampled articles do not match company drivers. Do not select Russian domestic outlets for US/Australian education unless a confirmed Russian exposure makes them relevant. Prefer specialist/primary coverage and diversity across the confirmed markets. A search match alone is insufficient; check actual sample headlines. Publication country is not the same thing as market coverage. Never invent a feed, source URL or evidence of coverage. No deliberation or correction text in reason. Zero suitable sources is a valid result.''', job_id=job.id, max_tokens=1700)
    by_id = {c["id"]: c for c in choices}
    selected = []
    for row in ranked.get("sources", []):
        candidate = by_id.get(row.get("id"))
        reason = row.get("reason", {})
        if candidate and row.get("eligible") is True and all(isinstance(reason.get(lang), str) and 8 <= len(reason[lang]) <= 600 for lang in ("en", "ru")) and all(s.get("url") != candidate["url"] for s in selected):
            selected.append({k: v for k, v in {**candidate, "reason": reason}.items() if k != "id"})
    coverage_gaps = [m for m in plan.get("markets", []) if not any(normal(m) in {normal(v.get("target_market")), normal(v.get("country"))} for v in selected)]
    result = {"status": "completed", "coverage_gaps": coverage_gaps, "profile_fingerprint": fingerprint, "searched_at": now(), "markets": plan.get("markets", []), "queries": queries, "index_result_count": index_result_count, "publisher_lead_count": len(plan.get("publisher_candidates", [])), "verified_count": len(verified), "sources": selected[:5], "diagnostics": diagnostics}
    record(db, workspace.id, "source_discovery", result, key=fingerprint)
    job.result = result
    progress("source_recommendations", {"status": "ok", "verified_count": len(verified), "recommended": len(selected), "profile_fingerprint": fingerprint}, 100)
