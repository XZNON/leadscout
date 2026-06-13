"""Stage 2 — FILTER. Deterministic, free, zero LLM. Drops obvious rejects before scoring.

Drops (idea.md §7 + Step 4 reachability bar):
  - not operational
  - website requirement per ICP (require_website)
  - review_count outside the ICP size_proxy range
  - place_type not in the niche allowlist (kills adjacent junk from broad keywords)
  - fails the contactability bar (the reachability filter — a perfect opener to a generic inbox
    is dead, so we filter on reachability *before* spending LLM tokens)

Every drop is recorded with a reason for the audit file.
"""

from __future__ import annotations

from ..models import DropRecord, ICPSpec, Lead, NicheSpec


def _named_email(lead: Lead) -> bool:
    """A named-owner email = we have an owner_name AND a non-generic mailbox."""
    if not lead.email:
        return False
    local = lead.email.split("@", 1)[0].lower()
    generic = {"info", "contact", "hello", "admin", "office", "support", "enquiry", "enquiries"}
    return bool(lead.owner_name) and local not in generic


def _meets_contactability(lead: Lead, bar: str) -> bool:
    if bar == "phone":
        return bool(lead.phone)
    if bar == "any":
        return bool(lead.phone or lead.email)
    # default: direct phone OR named-owner email
    return bool(lead.phone) or _named_email(lead)


def filter_leads(
    leads: list[Lead], icp: ICPSpec, niche: NicheSpec
) -> tuple[list[Lead], list[DropRecord]]:
    kept: list[Lead] = []
    dropped: list[DropRecord] = []
    allow = {t.lower() for t in niche.place_type_allowlist}
    lo, hi = icp.size_proxy.min, icp.size_proxy.max

    for lead in leads:
        reason: str | None = None

        if not lead.is_operational:
            reason = "not operational"
        elif icp.require_website and not lead.has_website:
            reason = "no website (ICP requires one)"
        elif lead.review_count is not None and not (lo <= lead.review_count <= hi):
            reason = f"review_count {lead.review_count} outside size_proxy [{lo},{hi}]"
        elif allow and (lead.place_type or "").lower() not in allow:
            reason = f"place_type '{lead.place_type}' not in allowlist"
        elif not _meets_contactability(lead, icp.contactability):
            reason = f"fails contactability bar ({icp.contactability})"

        if reason is None:
            kept.append(lead)
        else:
            dropped.append(DropRecord(place_id=lead.place_id, name=lead.name, reason=reason))

    return kept, dropped
