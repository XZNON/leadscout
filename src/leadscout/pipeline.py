"""The pipeline: discover -> filter -> enrich -> score. Pure composition of the four stages.

No agent loop. The LLM earns its place at the scoring step only (idea.md §3). Stages 1–3 are
deterministic; this module just wires them together and carries the dropped-records audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cache import JsonCache
from .clients import HttpClient, LlmClient, PlacesClient
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
    http: HttpClient,
    llm: LlmClient,
) -> PipelineResult:
    cache = JsonCache(cfg.cache_dir)

    # Stage 1 — discover (deterministic, deduped)
    raw = s_discover.discover(geo, niche, places)

    # Stage 2 — filter (deterministic, free; the cost gate before any LLM token)
    candidates, dropped = s_filter.filter_leads(raw, icp, niche)

    # Stage 3 — enrich (deterministic, cached, robots-aware)
    enriched = s_enrich.enrich(candidates, http, cache)

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
