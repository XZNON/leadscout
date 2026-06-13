# Session 06 — First real run & tuning

**Status:** ⬜ not started
**Goal:** run the whole live pipeline on the first ICP target (metro dental, Bengaluru) and tune
until the top rows are genuinely call-ready. This is the MVP "done" check (idea.md §13).
**Prereq:** Sessions 03–05 done (all three live clients implemented). Keys set.

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
