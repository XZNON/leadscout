# Session 06 — First real run & tuning

**Status:** ✅ done
**Goal:** run the whole live pipeline on the first ICP target (metro dental, Bengaluru) and tune
until the top rows are genuinely call-ready. This is the MVP "done" check (idea.md §13).
**Prereq:** Sessions 03–05 done (all three live clients implemented). Keys set.

## Outcome (2026-06-15)
Live Bengaluru-dental run: **462 raw → 251 candidates** (geocoded bbox, no tile subdivision yet).
Top rows are call-ready single clinics (Cosmo Family Dental, The Smile Company, Imperial, Nagu) at
`fit=60–80`, each with a non-generic opener grounded in the real `no online booking link` website
signal. Cost is trivial (~$0.0002/lead on `gpt-4o-mini`); a full 251-scored run is ~$0.06, far
under the $2.00 budget. Budget hard-stop verified (`LEADSCOUT_BUDGET_USD=0.0001` → `scored=1`).

**Data tuning applied (the fixes):**
- `dental.yaml`: added `dental_clinic` to `place_type_allowlist` — Places API (New) returns
  `primaryType: dental_clinic`, not legacy `dentist`; this alone was dropping ~66 real clinics.
- `clinic.yaml size_proxy.review_count.max`: `150 → 800` — Bengaluru owner-operated clinics
  routinely carry 200–600 reviews; the old cap dropped ~196 real leads.
- `clinic.yaml pain_signals`: removed the review-based signal (reviews are never fetched live, so
  it made the model **hallucinate** a review pain and ground every opener on it — a #6 failure);
  signals now ground on observable website state (`site_text`/`detected_tech`). This is the
  reviews-gap **option 1**; live review-fetch stays deferred to Session 07.
- `clinic.yaml disqualifiers`: named the dental franchises (Apollo, Partha, Clove, …) so the model
  caps them, not just "hospital chains".

**Prompt tuning applied (step 6, minimal — `score.build_prompt` wording only):**
- Added an explicit FIT-DIRECTION block (we *sell* booking → a clinic that already has it is a
  *low*-fit non-buyer, not a win).
- Hardened grounding: an unreadable site is rendered as `NOT AVAILABLE`; the model must then leave
  signals empty and cap `fit ≤ 40` rather than fabricate a website observation.
- Chain disqualifier fires only on a brand-name match or explicit `site_text` evidence — never
  inferred from a missing site (inventing a chain disq on a real `Dr. X` clinic loses a good lead).
- Tagged markers `[[PLACE_ID]]`/`[[FIRST_SIGNAL]]` kept intact; offline suite stays green (35).

**Known residuals (not blocking; Session-07 candidates):**
- ~35% of candidates have empty `site_text` (JS-only sites / robots-blocked) → they score 40 with a
  hedged, ungrounded opener and sort below the real prospects. Better scraping would lift them.
- Chain capping is LLM-stochastic: a by-name chain (e.g. "Partha Dental") can occasionally leak
  into the mid-ranks. A *deterministic* brand-list filter is the correct fix and belongs in code.
- A full 251-call run once errored mid-stream (likely a transient OpenAI error); bounded
  `--max-score` runs are stable. Worth a retry/robustness pass when scaling.

One fixture nudge was needed: the offline `icp`/`niche` fixtures load from `examples/`, so raising
the size cap meant `fixtures/places.json` `p_mega` had to move 500 → 1500 to keep testing the upper
bound (the plan's assumption that examples-tuning can't affect tests was wrong for this repo).

## Steps
1. Full live run:
   ```
   uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --max-score 20
   ```
   Start with `--max-score` low to cap LLM spend while iterating.
2. **Read the actual output**, not just the row count:
   - Are the top rows real, operational, in-niche, owner-operated clinics?
   - Does each opener reference a *real* detected signal (not a vibe)?
   - Are obvious non-buyers (chains, already-on-Practo) correctly capped low?
3. Tune **data, not code** where possible (the whole point of YAML config):
   - Adjust `size_proxy`, `disqualifiers`, `pain_signals`, `place_type_allowlist`.
   - Adjust `contactability` if too many good leads are filtered (or too much junk passes).
4. Tune the Stage-4 prompt only if openers are weak after data tuning.
5. Check the funnel numbers: raw → candidates → scored. idea.md §7 expects ~800 raw → ~100–140
   candidates for a full city; on a tighter geo expect proportionally fewer.
6. Sanity-check cost: `spent_usd` for the run is reasonable and under budget.

## Definition of done (= MVP, idea.md §13)
A `leads.csv` ranked by `fit_score` where the top rows are real, operational, in-niche Bengaluru
clinics that plausibly have the ICP pain, each with a non-generic opener referencing a detected
signal — for a single tiled city. Commit the tuned ICP/niche YAML. Update roadmap.

## Reminder
Output is for a **human to contact manually**. Do not add dialing/email automation (idea.md §10).
