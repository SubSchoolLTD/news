from __future__ import annotations

import hashlib
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

from .security import safe_url

HEADERS = {"User-Agent": "SignalDeskBot/1.0 (+https://analytics.subschool.us; research and company-requested monitoring)", "Accept": "text/html,application/rss+xml,application/atom+xml,application/pdf;q=0.9,*/*;q=0.8"}
MAX_BYTES = 5 * 1024 * 1024


def fetch(url: str, *, timeout=18):
    """Bounded, redirect-checked, credential-free public fetch."""
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=7), headers=HEADERS, trust_env=False) as client:
        for _ in range(5):
            safe_url(url)
            with client.stream("GET", url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                size, chunks = 0, []
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Source exceeds the 5 MB download limit.")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers.get("content-type", ""), url
    raise ValueError("Too many source redirects.")


def canonical(url):
    p = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))])
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", query, ""))


def fingerprint(title):
    return hashlib.sha256(re.sub(r"[^\w]", "", title.lower()).encode()).hexdigest()


def extract_html(data, url=""):
    soup = BeautifulSoup(data, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    description = soup.find("meta", attrs={"name": "description"})
    description = description.get("content", "") if description else ""
    published = soup.find("meta", attrs={"property": "article:published_time"})
    published = published.get("content") if published else None
    feeds = [urljoin(url, x.get("href", "")) for x in soup.select('link[rel="alternate"]') if any(v in x.get("type", "") for v in ["rss", "atom"])]
    links = []
    for a in soup.select("a[href]"):
        text = a.get_text(" ", strip=True)
        href = urljoin(url, a.get("href", ""))
        if len(text) > 25 and urlsplit(href).hostname == urlsplit(url).hostname:
            score = sum(2 for hint in ["/news", "/press", "/blog", "/article", "/research", "/analytics"] if hint in href.lower())
            if score:
                links.append({"title": text[:250], "url": href, "score": score})
    for node in soup.select("script,style,noscript,nav,header,footer,form,svg,aside"):
        node.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = re.sub(r"[ \t]+", " ", main.get_text("\n", strip=True))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"title": title[:300], "description": description[:1500], "text": text[:45000], "published_at": published, "feeds": feeds[:4], "links": sorted(links, key=lambda x: x["score"], reverse=True)[:15], "url": url}


def read_document(data: bytes, content_type: str, url: str):
    if "pdf" in content_type or data[:4] == b"%PDF":
        r = PdfReader(io.BytesIO(data))
        if len(r.pages) > 80:
            raise ValueError("Please upload a PDF with at most 80 pages.")
        text = "\n\n".join(f"[Page {i+1}]\n{p.extract_text() or ''}" for i, p in enumerate(r.pages))
        if len(re.sub(r"\[Page \d+\]", "", text).strip()) < 60:
            raise ValueError("This PDF needs OCR. Please provide a searchable PDF or paste the extracted text.")
        return {"title": (r.metadata.title if r.metadata else "") or urlsplit(url).path.split("/")[-1], "text": text[:200000], "url": url}
    if "html" in content_type or data.lstrip().startswith((b"<html", b"<!DOCTYPE", b"<!doctype")):
        return extract_html(data, url)
    return {"title": urlsplit(url).path.split("/")[-1], "text": data.decode("utf-8-sig", errors="replace")[:200000], "url": url}


def website_profile(url):
    data, typ, final = fetch(url)
    doc = read_document(data, typ, final)
    pages = [doc]
    # Follow one company about page when available; never guess company financials.
    soup = BeautifulSoup(data, "html.parser")
    for a in soup.select("a[href]"):
        target = urljoin(final, a.get("href", ""))
        if urlsplit(target).hostname == urlsplit(final).hostname and re.search(r"(?:about|company|o-kompanii|о-компании)", urlsplit(target).path, re.I):
            try:
                b, t, u = fetch(target, timeout=12)
                pages.append(read_document(b, t, u))
            except Exception:
                pass
            break
    return {"pages": pages, "title": doc["title"], "description": doc.get("description", ""), "text": "\n".join(p["text"][:15000] for p in pages), "feeds": doc.get("feeds", [])}


def allowed_by_robots(url):
    parsed = urlsplit(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        data, _, _ = fetch(robots_url, timeout=8)
        rp = RobotFileParser()
        rp.parse(data.decode("utf-8", errors="replace").splitlines())
        return rp.can_fetch("SignalDeskBot", url)
    except httpx.HTTPStatusError as e:
        return e.response.status_code in {404, 410}
    except Exception:
        # Conservative on unreachable policy; visible source diagnostic explains this.
        return False


def parse_date(entry):
    raw = entry.get("published") or entry.get("updated") or ""
    try:
        dt = parsedate_to_datetime(raw)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except Exception:
            return None


def collect_source(source):
    url = source["url"]
    if source.get("respect_robots", True) and not allowed_by_robots(url):
        raise ValueError("Collection is blocked by robots.txt or its policy is unreachable.")
    data, typ, final = fetch(url)
    feed = feedparser.parse(data) if "xml" in typ or data.lstrip().startswith(b"<?xml") or b"<rss" in data[:300] or b"<feed" in data[:300] else None
    if feed and feed.entries:
        entries = feed.entries
    else:
        page = extract_html(data, final)
        entries = []
        for feed_url in page["feeds"][:1]:
            b, _, _ = fetch(feed_url)
            entries = feedparser.parse(b).entries
        if not entries:
            return [{"title": x["title"], "url": canonical(x["url"]), "text": x["title"], "published_at": None, "source_id": source["id"], "source_name": source["name"], "kind": source.get("kind", "news"), "evidence_level": "headline"} for x in page["links"][:source.get("limit", 12)]]
    result = []
    for entry in entries[:min(int(source.get("limit", 12)), 30)]:
        link, title = entry.get("link"), entry.get("title")
        if not link or not title:
            continue
        try:
            safe_url(link, resolve=False)
        except ValueError:
            continue
        text = BeautifulSoup(entry.get("summary", "") or entry.get("description", ""), "html.parser").get_text(" ", strip=True)
        content = entry.get("content", [])
        if content:
            text += "\n" + BeautifulSoup(content[0].get("value", ""), "html.parser").get_text(" ", strip=True)
        result.append({"title": BeautifulSoup(title, "html.parser").get_text(" ", strip=True)[:400], "url": canonical(link), "text": (title + "\n" + text)[:18000], "published_at": parse_date(entry), "source_id": source["id"], "source_name": source["name"], "kind": source.get("kind", "news"), "evidence_level": "feed" if len(text) > 150 else "headline"})
    return result


def collect_sources(sources):
    documents, diagnostics = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(collect_source, s): s for s in sources if s.get("enabled", True)}
        for future in as_completed(jobs):
            s = jobs[future]
            try:
                docs = future.result()
                documents.extend(docs)
                diagnostics.append({"id": s["id"], "name": s["name"], "status": "ok", "count": len(docs), "error": ""})
            except Exception as e:
                diagnostics.append({"id": s["id"], "name": s["name"], "status": "error", "count": 0, "error": str(e)[:240]})
    return documents, diagnostics
