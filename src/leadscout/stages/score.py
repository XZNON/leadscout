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
from ..models import ICPSpec, Lead, OpenerFormat, ScoreResult

DISQUALIFIED_SCORE_CAP = 15

_FORMAT_FIELD: dict[str, str] = {
    "call": "opener_call",
    "email": "opener_email",
    "whatsapp": "opener_whatsapp",
}


def build_prompt(lead: Lead, icp: ICPSpec, formats: list[OpenerFormat]) -> str:
    """Construct the scoring prompt. Tagged markers ([[PLACE_ID:..]]) let the fixture LLM map
    deterministically; the live model ignores them and reads the natural-language body."""
    signals = "\n".join(f"  - {s}" for s in icp.pain_signals) or "  (none specified)"
    disq = "\n".join(f"  - {d}" for d in icp.disqualifiers) or "  (none specified)"
    reviews = "\n".join(f"  - {r}" for r in lead.reviews[:5]) or "  (none captured)"
    first_signal = icp.pain_signals[0] if icp.pain_signals else "their online presence"
    site_text = (lead.site_text or "").strip()
    site_block = (
        site_text[:1500]
        if site_text
        else "(NOT AVAILABLE — the website could not be read; you have NOT seen this site.)"
    )
    tech_block = ", ".join(lead.detected_tech) or "none"
    return f"""You qualify a local business as a SALES PROSPECT for a product. Detect only signals
you can OBSERVE in the evidence below; do not vibe-check fit and do not assume. Return JSON only.

[[PLACE_ID:{lead.place_id}]]
[[FIRST_SIGNAL:{first_signal}]]

PRODUCT (this is what we SELL them): {icp.product}
BUYER: {icp.buyer}

FIT DIRECTION (critical — get this right):
  - HIGH fit = a business that clearly HAS the pain the product solves and does NOT already have a
    solution. Here that means a readable website that LACKS online booking (only a phone number or
    contact form). They need what we sell.
  - LOW fit = a business that already has the solution. If the site already has online booking,
    they are NOT a prospect — score low. Do NOT congratulate them on having it; we are selling,
    not auditing.
PAIN SIGNALS TO LOOK FOR (about the WEBSITE — judge only from site_text and detected_tech below,
never from the name or category):
{signals}
DISQUALIFIERS (if any present, set fit_score low and list it in disqualifiers_hit):
{disq}

BUSINESS:
  name: {lead.name}
  category: {lead.category}
  website: {lead.website}
  detected_tech: {tech_block}
  site_text: {site_block}
  reviews:
{reviews}

GROUNDING RULES (enforced — violating them is a failure):
  - A website pain signal may be listed in detected_signals ONLY if site_text supports it. If
    site_text is NOT AVAILABLE, you did not see the website: do NOT claim any website signal,
    leave detected_signals empty, set fit_score <= 40, and say evidence was insufficient.
  - detected_tech naming a booking tool (online-booking-link, online-booking-widget, Practo,
    Zocdoc, Calendly, NexHealth) means they ALREADY have online booking: do NOT list a
    "no online booking" signal, score LOW, and treat an external booking platform (Practo/Zocdoc)
    as a disqualifier hit.
  - Chain/franchise disqualifier: fire it only on clear evidence — the business name literally
    contains a brand spelled out in a disqualifier (Apollo, Partha, Clove, ...), OR site_text
    plainly states multi-location/franchise membership. A doctor-named or independent clinic
    ("Dr. X Dental Care", "Smile Studio") is NOT a chain — NEVER invent "part of a larger group"
    or any disqualifier from a missing or unremarkable site_text. When unsure, leave it empty:
    wrongly disqualifying a real single clinic loses a good lead and is worse than missing one.
  - detected_signals must list the OBSERVED pain (e.g. "no online booking link on the website"),
    never a positive ("has booking"). Each requested opener field MUST reference one specific entry
    from detected_signals in plain words, framed as an opportunity we can help with.

Return JSON: fit_score (0-100), detected_signals[], disqualifiers_hit[], reasoning, and these
opener field(s) — produce ONLY the ones listed here:
{_build_format_block(formats)}
"""


def _build_format_block(formats: list[OpenerFormat]) -> str:
    lines = []
    for fmt in formats:
        if fmt == "call":
            lines.append(
                "  opener_call: 1-2 spoken lines for a phone call opening. "
                "MUST reference one specific entry from detected_signals in plain words, "
                "framed as an opportunity we can help with."
            )
        elif fmt == "email":
            lines.append(
                "  opener_email: 2-3 sentence email body, no subject line. "
                "MUST reference one specific entry from detected_signals in plain words, "
                "framed as an opportunity we can help with."
            )
        elif fmt == "whatsapp":
            lines.append(
                "  opener_whatsapp: one short, informal WhatsApp message. "
                "MUST reference one specific entry from detected_signals in plain words, "
                "framed as an opportunity we can help with."
            )
    return "\n".join(lines)


def _ground_opener(result: ScoreResult, formats: list[OpenerFormat]) -> ScoreResult:
    """Guarantee every requested opener variant references a real detected signal (#6)."""
    if not result.detected_signals:
        return result
    sig0 = result.detected_signals[0]
    updates: dict[str, str] = {}
    for fmt in formats:
        field = _FORMAT_FIELD[fmt]
        val = getattr(result, field) or ""
        if val and not any(_overlaps(val, sig) for sig in result.detected_signals):
            updates[field] = f"Noticed {sig0} — wanted to reach out about that."
    if updates:
        return result.model_copy(update=updates)
    return result


def _overlaps(opener: str, signal: str) -> bool:
    """Loose check: does the opener share a meaningful word with the signal?"""
    o = opener.lower()
    words = [w for w in signal.lower().replace("'", " ").split() if len(w) > 3]
    return any(w in o for w in words)


def score_lead(
    lead: Lead, icp: ICPSpec, llm: LlmClient, model: str, formats: list[OpenerFormat]
) -> Lead:
    result = llm.score(model, build_prompt(lead, icp, formats))
    if result.disqualifiers_hit:
        result = result.model_copy(
            update={"fit_score": min(result.fit_score, DISQUALIFIED_SCORE_CAP)}
        )
    result = _ground_opener(result, formats)
    primary_opener = getattr(result, _FORMAT_FIELD[formats[0]])
    updates: dict[str, object] = {
        "fit_score": result.fit_score,
        "detected_signals": result.detected_signals,
        "disqualifiers_hit": result.disqualifiers_hit,
        "reasoning": result.reasoning,
        "suggested_opener": primary_opener,
    }
    for fmt in formats:
        field = _FORMAT_FIELD[fmt]
        updates[field] = getattr(result, field)
    return lead.model_copy(update=updates)


def score(leads: list[Lead], icp: ICPSpec, llm: LlmClient, cfg: RunConfig) -> list[Lead]:
    """Score survivors, ranked by fit_score desc. Honors max_score and the USD budget ceiling."""
    candidates = leads[: cfg.max_score] if cfg.max_score is not None else leads
    scored: list[Lead] = []
    for lead in candidates:
        if llm.spent_usd >= cfg.budget_usd:
            # Budget hit mid-run is expected behavior, not a crash. Stop scoring.
            break
        scored.append(score_lead(lead, icp, llm, cfg.scoring_model, cfg.opener_formats))
    scored.sort(key=lambda x: x.fit_score or 0, reverse=True)
    return scored
