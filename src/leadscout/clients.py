"""External I/O behind small interfaces so stages stay pure-ish and tests inject fixtures.

Three surfaces touch the outside world:
  - PlacesClient  : Stage 1 discovery (Google Places API New + Geocoding)
  - HttpClient    : Stage 3 enrichment (scraping homepages/reviews)
  - LlmClient     : Stage 4 scoring (OpenAI)

Each has a live implementation (network) and a fixture implementation (offline, deterministic).
Tests and `--offline` use the fixture clients; nothing live is ever called in tests.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from openai import OpenAI

from .cache import JsonCache
from .models import BBox, ScoreResult

logger = logging.getLogger(__name__)

# =========================================================================== Places


class PlacesClient(Protocol):
    def geocode_bbox(self, query: str) -> BBox: ...
    def search(self, lat: float, lng: float, radius_km: float, keyword: str) -> list[dict]: ...


class FixturePlacesClient:
    """Reads recorded Places results from a fixture file. Zero network.

    Fixture shape (fixtures/places.json):
      { "bbox": {min_lat,min_lng,max_lat,max_lng},
        "results": [ {raw place dict with place_id...}, ... ] }
    The same results are returned for every (tile, keyword) so dedup logic is exercised.
    """

    def __init__(self, fixture_path: str | Path) -> None:
        self._data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))

    def geocode_bbox(self, query: str) -> BBox:
        return BBox.model_validate(self._data["bbox"])

    def search(self, lat: float, lng: float, radius_km: float, keyword: str) -> list[dict]:
        # Filter recorded results by keyword tag if present, else return all.
        results = self._data["results"]
        tagged = [r for r in results if keyword in r.get("_match_keywords", [keyword])]
        return tagged or results


class LivePlacesClient:
    """Live Google Places (New) Text Search + Geocoding. Network only on real runs.

    Caches every (tile,keyword) page-set under namespace "places_pages" and every normalized
    place under "places" keyed by place_id, so a second run of the same geo makes ~zero new API
    calls. The `client` param is an offline test seam: inject
    `httpx.Client(transport=httpx.MockTransport(handler))` so pytest never touches the network.
    The `PlacesClient` Protocol is unchanged — `cache`/`timeout_s`/`client` are impl detail.
    """

    GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
    SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
    FIELD_MASK = (
        "places.id,places.displayName,places.primaryType,places.rating,"
        "places.userRatingCount,places.websiteUri,places.internationalPhoneNumber,"
        "places.businessStatus,places.formattedAddress,nextPageToken"
    )
    MAX_PAGES = 3
    MAX_RESULTS = 60
    RADIUS_CAP_M = 50000.0

    def __init__(
        self,
        api_key: str,
        cache: JsonCache | None = None,
        timeout_s: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self._cache = cache
        self._http = client or httpx.Client(timeout=timeout_s)

    def geocode_bbox(self, query: str) -> BBox:
        if self._cache is not None:
            cached = self._cache.get("geocode", query)
            if cached is not None:
                return BBox.model_validate(cached)

        resp = self._http.get(self.GEOCODE_URL, params={"address": query, "key": self.api_key})
        self._raise_for_status(resp, "Geocoding")
        data = resp.json()
        status = data.get("status")
        if status != "OK":
            msg = data.get("error_message", "")
            raise RuntimeError(f"Geocoding API returned status={status!r} for {query!r}: {msg}")

        vp = data["results"][0]["geometry"]["viewport"]
        ne, sw = vp["northeast"], vp["southwest"]
        bbox = BBox(
            min_lat=sw["lat"], min_lng=sw["lng"], max_lat=ne["lat"], max_lng=ne["lng"]
        )
        if self._cache is not None:
            self._cache.set("geocode", query, bbox.model_dump())
        return bbox

    def search(self, lat: float, lng: float, radius_km: float, keyword: str) -> list[dict]:
        radius_m = min(radius_km, 50) * 1000
        key = f"{round(lat, 4)},{round(lng, 4)},r{int(radius_m)}|{keyword}"
        if self._cache is not None and self._cache.has("places_pages", key):
            cached = self._cache.get("places_pages", key)
            return list(cached) if cached is not None else []

        results: list[dict] = []
        page_token: str | None = None
        pages = 0
        while True:
            data = self._search_page(keyword, lat, lng, radius_m, page_token)
            for p in data.get("places", []):
                results.append(self._normalize(p))
            pages += 1
            page_token = data.get("nextPageToken")
            if not page_token or pages >= self.MAX_PAGES or len(results) >= self.MAX_RESULTS:
                if page_token:
                    # 60-cap / saturation: log, do NOT subdivide here. Subdivision/keyword
                    # narrowing hooks in at discover.resolve_tiles (see TODO there).
                    logger.warning(
                        "(tile,keyword) saturated: lat=%s lng=%s keyword=%r hit %d results / "
                        "%d pages with nextPageToken still present; consider tile subdivision.",
                        lat, lng, keyword, len(results), pages,
                    )
                break

        if self._cache is not None:
            self._cache.set("places_pages", key, results)
            for place in results:
                self._cache.set("places", place["place_id"], place)
        return results

    def _search_page(
        self, keyword: str, lat: float, lng: float, radius_m: float, page_token: str | None
    ) -> dict:
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "X-Goog-FieldMask": self.FIELD_MASK,
        }
        body: dict[str, Any] = {
            "textQuery": keyword,
            "pageSize": 20,
            # Places (New) Text Search: a circle goes under locationBias (locationRestriction
            # only accepts a rectangle). Bias centers results on the tile; the 50 km cap + tiling
            # + dedup still bound the search area. (Confirmed via a live 400 — see Session 03.)
            "locationBias": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": min(radius_m, self.RADIUS_CAP_M),
                }
            },
        }
        if page_token:
            body["pageToken"] = page_token

        # Pagination-token race (live only): a freshly issued pageToken may briefly return
        # INVALID_ARGUMENT. Retry a couple of times with a short backoff. Tests use MockTransport
        # returning valid pages immediately, so pytest never sleeps (token only set on page 2+).
        attempts = 3 if page_token else 1
        for attempt in range(attempts):
            resp = self._http.post(self.SEARCH_URL, headers=headers, json=body)
            if resp.status_code == 400 and attempt < attempts - 1:
                time.sleep(1.5)  # pragma: no cover - live-only backoff
                continue
            self._raise_for_status(resp, "Places Text Search")
            return resp.json()
        self._raise_for_status(resp, "Places Text Search")  # pragma: no cover - exhausted retries
        return resp.json()  # pragma: no cover

    @staticmethod
    def _raise_for_status(resp: httpx.Response, api: str) -> None:
        """Raise with Google's response body included — a 403/REQUEST_DENIED means API enablement
        or key restriction, not a code bug, and the body says exactly which. Don't swallow it."""
        if resp.is_success:
            return
        body = resp.text
        try:
            err = resp.json().get("error", {})
            body = err.get("message", body) or body
        except Exception:  # pragma: no cover - non-JSON error body
            pass
        raise RuntimeError(f"{api} API returned HTTP {resp.status_code}: {body}")

    @staticmethod
    def _normalize(p: dict) -> dict:
        """Shape a New-API place for `discover._raw_to_lead` (stable contract — do not edit it)."""
        return {**p, "place_id": p["id"], "name": (p.get("displayName") or {}).get("text", "")}


# =========================================================================== HTTP (scrape)


class HttpClient(Protocol):
    def robots_allows(self, url: str) -> bool: ...
    def fetch(self, url: str) -> str | None: ...


class AsyncHttpClient(Protocol):
    """Async twin of `HttpClient`, used only on live runs (see `enrich.enrich_async`).

    The sync `HttpClient` Protocol + `FixtureHttpClient` are what every offline test drives; this
    parallel async surface lets the live scraper own its concurrency/politeness cap internally
    without reshaping the deterministic fixture path.
    """

    async def robots_allows(self, url: str) -> bool: ...
    async def fetch(self, url: str) -> str | None: ...


class FixtureHttpClient:
    """Serves recorded HTML pages from fixtures/scrapes/<host>.html. Zero network.

    Tracks fetch count so tests can assert caching prevents re-fetching.
    """

    def __init__(self, scrapes_dir: str | Path) -> None:
        self.dir = Path(scrapes_dir)
        self.fetch_count = 0

    @staticmethod
    def _host(url: str) -> str:
        host = url.split("//", 1)[-1].split("/", 1)[0]
        return host.replace("www.", "")

    def robots_allows(self, url: str) -> bool:
        return True  # fixtures are all crawl-permitted

    def fetch(self, url: str) -> str | None:
        self.fetch_count += 1
        p = self.dir / f"{self._host(url)}.html"
        return p.read_text(encoding="utf-8") if p.exists() else None


class LiveHttpClient:
    """Live scraper: robots.txt aware, concurrency-capped, real User-Agent. Real runs only.

    Async over a shared `httpx.AsyncClient`. Politeness lives here, not in the stage:
      - per-host `robots.txt` fetched once, parsed, cached, and honored (disallow → skip);
      - an `asyncio.Semaphore(max_concurrency)` bounds in-flight page GETs;
      - a per-request timeout (on the client) plus bounded exponential backoff on 429/5xx/network.

    The `client` param is the offline test seam: inject
    `httpx.AsyncClient(transport=httpx.MockTransport(handler))` so pytest never touches the
    network. It is impl detail, not part of the `AsyncHttpClient` Protocol.
    """

    USER_AGENT = "LeadScoutBot/0.1 (+internal lead research; respects robots.txt)"

    def __init__(
        self,
        timeout_s: float = 10.0,
        max_concurrency: int = 5,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.timeout_s = timeout_s
        self._max_retries = max_retries
        self._client = client or httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": self.USER_AGENT},
        )
        self._sem = asyncio.Semaphore(max_concurrency)
        # host -> parsed robots (None = indeterminate, treat as disallow)
        self._robots: dict[str, RobotFileParser | None] = {}

    async def robots_allows(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            self._robots[host] = await self._load_robots(parts.scheme, host)
        rp = self._robots[host]
        if rp is None:
            return False  # indeterminate robots → be polite, skip
        return rp.can_fetch(self.USER_AGENT, url)

    async def _load_robots(self, scheme: str, host: str) -> RobotFileParser | None:
        rp = RobotFileParser()
        robots_url = f"{scheme}://{host}/robots.txt"
        try:
            resp = await self._client.get(robots_url)
        except httpx.HTTPError:
            return None  # network error → indeterminate → disallow
        if resp.is_success:
            rp.parse(resp.text.splitlines())
            return rp
        if 400 <= resp.status_code < 500:
            rp.parse([])  # no robots / client error → allow-all
            return rp
        return None  # 5xx → indeterminate → disallow

    async def fetch(self, url: str) -> str | None:
        async with self._sem:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await self._client.get(url)
                except httpx.HTTPError:
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.5 * 2**attempt)
                        continue
                    return None
                if resp.is_success:
                    return resp.text
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < self._max_retries:
                        await asyncio.sleep(0.5 * 2**attempt)
                        continue
                return None  # other 4xx (or retries exhausted) → give up, no retry
        return None  # pragma: no cover - unreachable


# =========================================================================== LLM (score)


class LlmClient(Protocol):
    def score(self, model: str, prompt: str) -> ScoreResult: ...
    @property
    def call_count(self) -> int: ...
    @property
    def spent_usd(self) -> float: ...


class FixtureLlmClient:
    """Deterministic offline scorer. Reads canned ScoreResults keyed by place_id.

    fixtures/llm_scores.json: { "<place_id>": {fit_score, detected_signals, ...}, ... }
    Falls back to a grounded heuristic if a place_id is absent, so the pipeline always produces
    an opener that references a real detected signal (never a generic fallback).
    """

    PRICE_PER_CALL_USD = 0.002  # rough fixed estimate for budget accounting in offline mode

    def __init__(self, scores_path: str | Path) -> None:
        self._scores = json.loads(Path(scores_path).read_text(encoding="utf-8"))
        self._calls = 0

    def score(self, model: str, prompt: str) -> ScoreResult:
        self._calls += 1
        # The pipeline embeds the place_id in the prompt as a tagged line for fixture lookup.
        place_id = _extract_tag(prompt, "PLACE_ID")
        canned = self._scores.get(place_id)
        if canned is not None:
            return ScoreResult.model_validate(canned)
        # Grounded fallback: pull a signal token out of the prompt so the opener is never generic.
        signal = _extract_tag(prompt, "FIRST_SIGNAL") or "your online presence"
        return ScoreResult(
            fit_score=50,
            detected_signals=[signal],
            disqualifiers_hit=[],
            reasoning="Heuristic fixture score (no canned entry).",
            suggested_opener=f"Noticed {signal} — wanted to reach out about it.",
        )

    @property
    def call_count(self) -> int:
        return self._calls

    @property
    def spent_usd(self) -> float:
        return self._calls * self.PRICE_PER_CALL_USD


# USD per 1K tokens (input, output). Confirmed June 2026; update if OpenAI reprices.
MODEL_PRICES: dict[str, tuple[float, float]] = {"gpt-4o-mini": (0.00015, 0.00060)}
_DEFAULT_PRICE = (0.00015, 0.00060)  # conservative fallback; logged on use


def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Real token cost so the budget ceiling stops on real money, not a $0 no-op."""
    rate = MODEL_PRICES.get(model)
    if rate is None:
        logger.warning(
            "No price for model %r; using default rate %s/1K (input,output). "
            "Add it to MODEL_PRICES for accurate budget accounting.",
            model, _DEFAULT_PRICE,
        )
        rate = _DEFAULT_PRICE
    in_rate, out_rate = rate
    return prompt_tokens / 1000 * in_rate + completion_tokens / 1000 * out_rate


class LiveLlmClient:
    """Live OpenAI structured-output scorer. Real runs only.

    Uses Structured Outputs (`beta.chat.completions.parse(response_format=ScoreResult)`) so the
    response parses straight into a `ScoreResult` — no prose, no regex. A safety refusal or a
    missing parse is a failure: retry once, then raise (never ship a default/garbage score).
    Cost and call count accrue only on success, from `response.usage`.

    The `client` param is the offline test seam: inject a fake exposing
    `.beta.chat.completions.parse(...)` so pytest never touches the network or needs a key. It is
    impl detail, not part of the `LlmClient` Protocol.
    """

    def __init__(self, api_key: str, client: OpenAI | None = None) -> None:
        self.api_key = api_key
        self._calls = 0
        self._spent = 0.0
        self._client = client or OpenAI(api_key=api_key)

    def score(self, model: str, prompt: str) -> ScoreResult:
        for attempt in range(2):  # one retry, then raise
            try:
                resp = self._client.beta.chat.completions.parse(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format=ScoreResult,
                    temperature=0,
                )
                msg = resp.choices[0].message
                if msg.refusal or msg.parsed is None:
                    raise ValueError(f"model refused or returned no parse: {msg.refusal!r}")
                result = msg.parsed
                usage = resp.usage
                if usage is None:
                    raise ValueError("response missing usage; cannot account cost")
                # Accrue only on success so a failed-then-retried call isn't double-charged.
                self._spent += _cost_usd(model, usage.prompt_tokens, usage.completion_tokens)
                self._calls += 1
                return result
            except Exception:
                if attempt == 0:
                    continue
                raise
        raise AssertionError("unreachable")  # pragma: no cover

    @property
    def call_count(self) -> int:
        return self._calls

    @property
    def spent_usd(self) -> float:
        return self._spent


# --------------------------------------------------------------------------- helpers


def _extract_tag(text: str, tag: str) -> str:
    """Pull a `[[TAG: value]]` marker out of a prompt. Returns '' if absent."""
    marker = f"[[{tag}:"
    start = text.find(marker)
    if start == -1:
        return ""
    start += len(marker)
    end = text.find("]]", start)
    return text[start:end].strip() if end != -1 else ""


def load_fixture_clients(
    fixtures_dir: str | Path,
) -> tuple[FixturePlacesClient, FixtureHttpClient, FixtureLlmClient]:
    d = Path(fixtures_dir)
    return (
        FixturePlacesClient(d / "places.json"),
        FixtureHttpClient(d / "scrapes"),
        FixtureLlmClient(d / "llm_scores.json"),
    )


def to_serializable(obj: Any) -> Any:
    return obj
