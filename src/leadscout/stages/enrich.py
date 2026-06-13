"""Stage 3 — ENRICH. Scrape homepage/about + reviews; extract email, owner, tech signals.

Deterministic, zero LLM, I/O-bound. Caches by place_id so re-runs are nearly free and tests make
no network calls on a warm cache. Respects robots.txt via the HttpClient.

Reviews are not scraped here in the MVP fixture path — they ride along on the raw place record
(Places provides a few) and are attached if present. The live client would fetch low-star/recent
reviews where complaints (and thus pain signals) live.
"""

from __future__ import annotations

import re

from ..cache import JsonCache
from ..clients import HttpClient
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
_OWNER_RE = re.compile(r"\b(?:Dr\.?|Doctor)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})")


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


def enrich_lead(lead: Lead, http: HttpClient, cache: JsonCache) -> Lead:
    cached = cache.get("enrich", lead.place_id)
    if cached is None:
        cached = {}
        if lead.website and http.robots_allows(lead.website):
            html = http.fetch(lead.website)
            if html:
                cached = _extract(html)
        cache.set("enrich", lead.place_id, cached)

    update = {k: v for k, v in cached.items() if v not in (None, [], "")}
    return lead.model_copy(update=update)


def enrich(leads: list[Lead], http: HttpClient, cache: JsonCache) -> list[Lead]:
    """Enrich each candidate. Concurrency/politeness cap lives in the live HttpClient; the
    fixture path is synchronous and cache-backed."""
    return [enrich_lead(lead, http, cache) for lead in leads]
