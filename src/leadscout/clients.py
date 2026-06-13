"""External I/O behind small interfaces so stages stay pure-ish and tests inject fixtures.

Three surfaces touch the outside world:
  - PlacesClient  : Stage 1 discovery (Google Places API New + Geocoding)
  - HttpClient    : Stage 3 enrichment (scraping homepages/reviews)
  - LlmClient     : Stage 4 scoring (OpenAI)

Each has a live implementation (network) and a fixture implementation (offline, deterministic).
Tests and `--offline` use the fixture clients; nothing live is ever called in tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from .models import BBox, ScoreResult

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
    """Live Google Places (New) + Geocoding. Network calls happen only on real runs."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def geocode_bbox(self, query: str) -> BBox:  # pragma: no cover - live path
        raise NotImplementedError(
            "TODO(live): call Geocoding API for `query`, return the viewport bbox. "
            "Needs GOOGLE_MAPS_API_KEY. Mocked in tests."
        )

    def search(  # pragma: no cover - live path
        self, lat: float, lng: float, radius_km: float, keyword: str
    ) -> list[dict]:
        raise NotImplementedError(
            "TODO(live): Places Nearby/Text Search at (lat,lng,radius); paginate all ~3 pages "
            "(60 cap); return raw place dicts. Needs GOOGLE_MAPS_API_KEY. Mocked in tests."
        )


# =========================================================================== HTTP (scrape)


class HttpClient(Protocol):
    def robots_allows(self, url: str) -> bool: ...
    def fetch(self, url: str) -> str | None: ...


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
    """Live scraper: robots.txt aware, rate-limited, real User-Agent. Real runs only."""

    USER_AGENT = "LeadScoutBot/0.1 (+internal lead research; respects robots.txt)"

    def __init__(self, timeout_s: float = 10.0) -> None:
        self.timeout_s = timeout_s

    def robots_allows(self, url: str) -> bool:  # pragma: no cover - live path
        raise NotImplementedError(
            "TODO(live): fetch & parse robots.txt for the host; honor it. Mocked in tests."
        )

    def fetch(self, url: str) -> str | None:  # pragma: no cover - live path
        raise NotImplementedError(
            "TODO(live): httpx GET with User-Agent + timeout + backoff; return HTML. "
            "Mocked in tests."
        )


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


class LiveLlmClient:
    """Live OpenAI structured-output scorer. Real runs only."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._calls = 0
        self._spent = 0.0

    def score(self, model: str, prompt: str) -> ScoreResult:  # pragma: no cover - live path
        raise NotImplementedError(
            "TODO(live): call OpenAI `model` with Structured Outputs (response_format json_schema "
            "matching ScoreResult); accumulate token cost into spent_usd. Needs OPENAI_API_KEY. "
            "Mocked in tests."
        )

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
