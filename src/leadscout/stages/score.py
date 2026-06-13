"""Stage 4 — SCORE. The product. The ONLY stage that touches an LLM, only on Stage-2 survivors.

For each enriched candidate we send {name, category, site text, reviews} + the ICP spec and
require structured JSON back (ScoreResult). Rules enforced here, not just hoped for in the prompt:
  - budget ceiling: stop scoring when spent_usd would exceed the run budget.
  - max_score: optional hard cap on how many candidates reach the LLM (cost guard).
  - disqualifiers_hit non-empty  =>  fit_score capped low regardless of model output.
  - suggested_opener MUST reference a detected_signal; if it doesn't, that's a failure — we
    rewrite it to cite the first detected signal rather than ship a generic opener.
"""

from __future__ import annotations

from ..clients import LlmClient
from ..config import RunConfig
from ..models import ICPSpec, Lead, ScoreResult

DISQUALIFIED_SCORE_CAP = 15


def build_prompt(lead: Lead, icp: ICPSpec) -> str:
    """Construct the scoring prompt. Tagged markers ([[PLACE_ID:..]]) let the fixture LLM map
    deterministically; the live model ignores them and reads the natural-language body."""
    signals = "\n".join(f"  - {s}" for s in icp.pain_signals) or "  (none specified)"
    disq = "\n".join(f"  - {d}" for d in icp.disqualifiers) or "  (none specified)"
    reviews = "\n".join(f"  - {r}" for r in lead.reviews[:5]) or "  (none captured)"
    first_signal = icp.pain_signals[0] if icp.pain_signals else "their online presence"
    return f"""You qualify a local business against a product ICP. Detect OBSERVABLE pain
signals; do not vibe-check fit. Return structured JSON only.

[[PLACE_ID:{lead.place_id}]]
[[FIRST_SIGNAL:{first_signal}]]

PRODUCT: {icp.product}
BUYER: {icp.buyer}
PAIN SIGNALS TO LOOK FOR:
{signals}
DISQUALIFIERS (if any present, set fit_score low and list it in disqualifiers_hit):
{disq}

BUSINESS:
  name: {lead.name}
  category: {lead.category}
  website: {lead.website}
  detected_tech: {", ".join(lead.detected_tech) or "none"}
  site_text: {(lead.site_text or "")[:1500]}
  reviews:
{reviews}

Return JSON: fit_score (0-100), detected_signals[], disqualifiers_hit[], reasoning,
suggested_opener. The suggested_opener MUST reference one specific detected_signal.
"""


def _ground_opener(result: ScoreResult) -> ScoreResult:
    """Guarantee the opener references a real detected signal (non-negotiable #6)."""
    if not result.detected_signals:
        return result
    opener = result.suggested_opener or ""
    if any(_overlaps(opener, sig) for sig in result.detected_signals):
        return result
    sig = result.detected_signals[0]
    return result.model_copy(
        update={"suggested_opener": f"Noticed {sig} — wanted to reach out about that."}
    )


def _overlaps(opener: str, signal: str) -> bool:
    """Loose check: does the opener share a meaningful word with the signal?"""
    o = opener.lower()
    words = [w for w in signal.lower().replace("'", " ").split() if len(w) > 3]
    return any(w in o for w in words)


def score_lead(lead: Lead, icp: ICPSpec, llm: LlmClient, model: str) -> Lead:
    result = llm.score(model, build_prompt(lead, icp))
    if result.disqualifiers_hit:
        result = result.model_copy(
            update={"fit_score": min(result.fit_score, DISQUALIFIED_SCORE_CAP)}
        )
    result = _ground_opener(result)
    return lead.model_copy(update={
        "fit_score": result.fit_score,
        "detected_signals": result.detected_signals,
        "disqualifiers_hit": result.disqualifiers_hit,
        "reasoning": result.reasoning,
        "suggested_opener": result.suggested_opener,
    })


def score(leads: list[Lead], icp: ICPSpec, llm: LlmClient, cfg: RunConfig) -> list[Lead]:
    """Score survivors, ranked by fit_score desc. Honors max_score and the USD budget ceiling."""
    candidates = leads[: cfg.max_score] if cfg.max_score is not None else leads
    scored: list[Lead] = []
    for lead in candidates:
        if llm.spent_usd >= cfg.budget_usd:
            # Budget hit mid-run is expected behavior, not a crash. Stop scoring.
            break
        scored.append(score_lead(lead, icp, llm, cfg.scoring_model))
    scored.sort(key=lambda x: x.fit_score or 0, reverse=True)
    return scored
