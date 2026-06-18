"""Stage 3 — ENRICH. Scrape homepage/about + reviews; extract email, owner, tech signals.

Deterministic, zero LLM, I/O-bound. Caches by place_id so re-runs are nearly free and tests make
no network calls on a warm cache. Respects robots.txt via the HttpClient.

Reviews are not scraped here in the MVP fixture path — they ride along on the raw place record
(Places provides a few) and are attached if present. The live client would fetch low-star/recent
reviews where complaints (and thus pain signals) live.
"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin

from ..cache import JsonCache
from ..clients import AsyncHttpClient, HttpClient
from ..models import Lead

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Booking-platform / tech signals relevant to common clinic ICP disqualifiers.
_TECH_MARKERS = {
    "practo": "Practo",
    "zocdoc": "Zocdoc",
    "calendly": "Calendly",
    "nexhealth": "NexHealth",
    "book now": "online-booking-widget",
    "/book": "online-booking-link",
}
# "Dr./Doctor <Name>" — homepage path, kept for backward compatibility.
_OWNER_RE = re.compile(r"\b(?:Dr\.?|Doctor)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")
# Explicit role label followed by a name, e.g. "Owner: Ramesh Gupta" or "Proprietor — Sunita Mehta".
_OWNER_LABEL_RE = re.compile(
    r"\b(?:Owner|Founder|Co-?[Ff]ounder|Proprietor|Principal(?:\s+Dentist)?"
    r"|Managing\s+Director|Director)\b\s*[:\-—]?\s+(?:Dr\.?\s+)?"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)


def _best_owner(text: str) -> str | None:
    """Try role-label form first, then Dr./Doctor form. Return None on no match — never guess.

    On-site only by design; off-site/LinkedIn lookup declined on ToS + fragility grounds
    — see Implementations/step07C.
    """
    m = _OWNER_LABEL_RE.search(text)
    if m:
        return m.group(1)
    m = _OWNER_RE.search(text)
    if m:
        return m.group(1)
    return None


def _candidate_pages(homepage_url: str) -> list[str]:
    """Return homepage + fixed on-site candidate paths, deduped, homepage first."""
    seen = {homepage_url}
    pages = [homepage_url]
    for path in ("/about", "/about-us", "/team", "/contact"):
        url = urljoin(homepage_url, path)
        if url not in seen:
            seen.add(url)
            pages.append(url)
    return pages


def _strip_html(html: str) -> str:
    """Best-effort readable text. selectolax if available, else a regex fallback."""
    try:
        from selectolax.parser import HTMLParser  # type: ignore

        tree = HTMLParser(html)
        for tag in tree.css("script, style"):
            tag.decompose()
        body = tree.body
        text = body.text(separator=" ") if body else tree.text()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def _extract(html: str) -> dict:
    text = _strip_html(html)
    lower = (html + " " + text).lower()
    email_match = _EMAIL_RE.search(text)
    owner_match = _OWNER_RE.search(text)
    tech = sorted({label for marker, label in _TECH_MARKERS.items() if marker in lower})
    return {
        "site_text": text[:4000],
        "email": email_match.group(0) if email_match else None,
        "owner_name": owner_match.group(1) if owner_match else None,
        "detected_tech": tech,
    }


def _merge(lead: Lead, cached: dict) -> Lead:
    """Apply non-empty enrich fields onto the lead. Shared by the sync and async paths so they
    can never drift."""
    update = {k: v for k, v in cached.items() if v not in (None, [], "")}
    return lead.model_copy(update=update)


def enrich_lead(lead: Lead, http: HttpClient, cache: JsonCache) -> Lead:
    cached = cache.get("enrich", lead.place_id)
    if cached is None:
        cached = {}
        if lead.website and http.robots_allows(lead.website):
            html = http.fetch(lead.website)
            if html:
                cached = _extract(html)
        # If the homepage didn't yield an owner name, try on-site candidate pages.
        if not cached.get("owner_name") and lead.website:
            for url in _candidate_pages(lead.website)[1:]:
                if http.robots_allows(url):
                    extra_html = http.fetch(url)
                    if extra_html:
                        name = _best_owner(_strip_html(extra_html))
                        if name:
                            cached["owner_name"] = name
                            break
        cache.set("enrich", lead.place_id, cached)

    return _merge(lead, cached)


def enrich(leads: list[Lead], http: HttpClient, cache: JsonCache) -> list[Lead]:
    """Enrich each candidate. Concurrency/politeness cap lives in the live HttpClient; the
    fixture path is synchronous and cache-backed."""
    return [enrich_lead(lead, http, cache) for lead in leads]


async def enrich_async(
    leads: list[Lead], http: AsyncHttpClient, cache: JsonCache
) -> list[Lead]:
    """Live path: same per-lead logic as `enrich_lead`, but awaits robots/fetch and runs leads
    concurrently. The concurrency/politeness cap lives inside the live HttpClient's semaphore."""

    async def _one(lead: Lead) -> Lead:
        cached = cache.get("enrich", lead.place_id)
        if cached is None:
            cached = {}
            if lead.website and await http.robots_allows(lead.website):
                html = await http.fetch(lead.website)
                if html:
                    cached = _extract(html)
            if not cached.get("owner_name") and lead.website:
                for url in _candidate_pages(lead.website)[1:]:
                    if await http.robots_allows(url):
                        extra_html = await http.fetch(url)
                        if extra_html:
                            name = _best_owner(_strip_html(extra_html))
                            if name:
                                cached["owner_name"] = name
                                break
            cache.set("enrich", lead.place_id, cached)
        return _merge(lead, cached)

    return list(await asyncio.gather(*(_one(lead) for lead in leads)))
