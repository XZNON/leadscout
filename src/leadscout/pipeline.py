"""The pipeline: discover -> filter -> enrich -> score. Pure composition of the four stages.

No agent loop. The LLM earns its place at the scoring step only (idea.md §3). Stages 1–3 are
deterministic; this module just wires them together and carries the dropped-records audit trail.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import cast

from .cache import JsonCache
from .clients import AsyncHttpClient, HttpClient, LlmClient, PlacesClient, SourceClient
from .config import RunConfig
from .models import DropRecord, GeographyInput, ICPSpec, Lead, NicheSpec
from .stages import discover as s_discover
from .stages import enrich as s_enrich
from .stages import filter as s_filter
from .stages import score as s_score


@dataclass
class PipelineResult:
    leads: list[Lead]  # scored, ranked
    dropped: list[DropRecord] = field(default_factory=list)
    raw_count: int = 0
    candidate_count: int = 0
    scored_count: int = 0
    llm_calls: int = 0
    spent_usd: float = 0.0


def run_pipeline(
    geo: GeographyInput,
    niche: NicheSpec,
    icp: ICPSpec,
    cfg: RunConfig,
    places: PlacesClient,
    http: HttpClient | AsyncHttpClient,
    llm: LlmClient,
    extra_sources: list[SourceClient] | None = None,
) -> PipelineResult:
    cache = JsonCache(cfg.cache_dir)

    # Stage 1 — discover (deterministic, deduped). Extra sources (if any) merge into the same
    # place_id + phone dedup; default-empty keeps the Places-only path identical.
    raw = s_discover.discover(geo, niche, places, extra_sources=extra_sources)

    # Stage 2 — filter (deterministic, free; the cost gate before any LLM token)
    candidates, dropped = s_filter.filter_leads(raw, icp, niche)

    # Stage 3 — enrich (deterministic, cached, robots-aware). Offline drives the sync fixture
    # path; live runs use the concurrent async scraper (politeness cap lives in the client).
    if cfg.offline:
        enriched = s_enrich.enrich(candidates, cast("HttpClient", http), cache)
    else:
        enriched = asyncio.run(
            s_enrich.enrich_async(candidates, cast("AsyncHttpClient", http), cache)
        )

    # Stage 4 — score (LLM, ONLY on survivors, budget-capped)
    scored = s_score.score(enriched, icp, llm, cfg)

    return PipelineResult(
        leads=scored,
        dropped=dropped,
        raw_count=len(raw),
        candidate_count=len(candidates),
        scored_count=len(scored),
        llm_calls=llm.call_count,
        spent_usd=llm.spent_usd,
    )
