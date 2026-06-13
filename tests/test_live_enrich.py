"""Offline tests for the live async scraper (LiveHttpClient) and enrich_async.

Everything here drives the live async code paths through an injected
`httpx.AsyncClient(transport=httpx.MockTransport(handler))` — zero network, zero real sleeps.
Coroutines run via `asyncio.run(...)` inside ordinary sync test functions (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio

import httpx

from leadscout.cache import JsonCache
from leadscout.clients import LiveHttpClient
from leadscout.models import Lead
from leadscout.stages.enrich import enrich_async

HOMEPAGE = (
    "<html><body>"
    "<p>Welcome to Bright Smile. Contact us at anita@brightsmile.example.</p>"
    "<p>Led by Dr. Anita Rao.</p>"
    "<a href='https://www.practo.com/x'>Book on Practo</a>"
    "</body></html>"
)


def _client(handler) -> LiveHttpClient:
    transport = httpx.MockTransport(handler)
    return LiveHttpClient(client=httpx.AsyncClient(transport=transport))


def _lead(website: str = "https://h/") -> Lead:
    return Lead(
        place_id="p_h", name="Bright Smile Dental", place_type="dentist",
        website=website, phone="+91 80 1234 5678", review_count=42, has_website=True,
    )


def test_robots_allows_parses_and_caches() -> None:
    counts = {"robots": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            counts["robots"] += 1
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(200, text="ok")

    http = _client(handler)

    async def go() -> tuple[bool, bool]:
        a = await http.robots_allows("https://h/")
        b = await http.robots_allows("https://h/private")
        return a, b

    allowed, private = asyncio.run(go())
    assert allowed is True
    assert private is False
    assert counts["robots"] == 1, "robots.txt must be fetched once per host, then cached"


def test_robots_5xx_or_error_disallows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    assert asyncio.run(_client(handler).robots_allows("https://h/")) is False


def test_robots_404_allows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    assert asyncio.run(_client(handler).robots_allows("https://h/")) is True


def test_fetch_returns_html_and_extracts(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=HOMEPAGE)

    http = _client(handler)
    out = asyncio.run(enrich_async([_lead()], http, JsonCache(tmp_path)))
    lead = out[0]
    assert lead.email == "anita@brightsmile.example"
    assert lead.owner_name == "Anita Rao"
    assert "bright smile" in (lead.site_text or "").lower()
    assert "Practo" in lead.detected_tech


def test_robots_disallow_skips_fetch(tmp_path) -> None:
    counts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        counts["page"] += 1
        return httpx.Response(200, text=HOMEPAGE)

    http = _client(handler)
    out = asyncio.run(enrich_async([_lead()], http, JsonCache(tmp_path)))
    assert counts["page"] == 0, "robots disallow must skip the page GET entirely"
    assert out[0].email is None
    assert out[0].owner_name is None


def test_fetch_retries_then_gives_up(monkeypatch, tmp_path) -> None:
    sleeps = {"n": 0}

    async def _no_sleep(_seconds: float) -> None:
        sleeps["n"] += 1

    monkeypatch.setattr("leadscout.clients.asyncio.sleep", _no_sleep)

    counts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counts["page"] += 1
        return httpx.Response(503, text="down")

    http = LiveHttpClient(
        max_retries=2, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    assert asyncio.run(http.fetch("https://h/")) is None
    assert counts["page"] == 3, "1 try + 2 retries = max_retries + 1 attempts"
    assert sleeps["n"] == 2


def test_fetch_404_no_retry() -> None:
    counts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counts["page"] += 1
        return httpx.Response(404, text="nope")

    http = _client(handler)
    assert asyncio.run(http.fetch("https://h/")) is None
    assert counts["page"] == 1, "a 404 is terminal — no retry"


def test_enrich_async_cached_no_refetch(tmp_path) -> None:
    counts = {"page": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        counts["page"] += 1
        return httpx.Response(200, text=HOMEPAGE)

    cache = JsonCache(tmp_path)
    http = _client(handler)
    asyncio.run(enrich_async([_lead()], http, cache))
    assert counts["page"] == 1
    asyncio.run(enrich_async([_lead()], http, cache))  # warm cache
    assert counts["page"] == 1, "second run must hit cache, not the network"


def test_semaphore_wired() -> None:
    assert LiveHttpClient(max_concurrency=3)._sem._value == 3
