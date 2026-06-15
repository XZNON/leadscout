# Step 06 — First real run & tuning — implementation plan

> Source of truth: `docs/sessions/session-06-real-run.md`. This is the worked-out *how* for that one
> step. **This is the MVP "done" gate (idea.md §13).** Unlike Steps 03–05, this session is
> **operator-driven tuning, not feature code**: run the live pipeline, *read the actual output*, then
> tune the **YAML data** (`examples/clinic.yaml`, `examples/dental.yaml`) and re-run until the top
> rows are call-ready. Touch the Stage-4 *prompt* only if openers stay weak after data tuning. Touch
> any other code only as a last resort, and never to add a Session-07 feature.
>
> **Do not pull work forward** from Session 07: no JustDial/IndiaMART adapters, no bbox tile
> subdivision/saturation handling, no LinkedIn owner enrichment, no SQLite. See the explicit
> reviews-gap decision below — the *default* is to defer live review-fetching to Session 07.

## Goal & scope
Run the whole live pipeline on the first target — **metro dental, Bengaluru** — and tune until the
top rows of `out/leads.csv` are genuinely call-ready: real, operational, in-niche, owner-operated
clinics, each with a non-generic `suggested_opener` that references a **real** `detected_signal`,
with obvious non-buyers (hospital chains, already-on-Practo) correctly capped low. The tuning happens
in **data** (ICP/niche YAML) wherever possible — that is the entire point of config-as-data. "Done"
means a committed, tuned `examples/clinic.yaml` + `examples/dental.yaml` whose live run yields a
ranked CSV meeting idea.md §13, with a sane funnel (raw → candidates → scored) and a run cost under
budget. Offline tests stay green; the roadmap is flipped to ✅.

## Prerequisites (confirmed)
- ✅ Sessions 03–05 done and **verified in code** (not just the roadmap): `LivePlacesClient`
  (`geocode_bbox` + `search`, `clients.py:61`), `LiveHttpClient` (robots-aware async scraper,
  `clients.py:251`), and `LiveLlmClient.score` (OpenAI structured output, `clients.py:399`) are all
  fully implemented — **no `NotImplementedError` remains in `src/`**.
- ✅ `uv run pytest -q` → **35 passed**, fully offline. `ruff`/`mypy` were the Step 03–05 gates.
- ✅ The CLI live branch (`cli.py:59-68`) already wires all three live clients with the disk cache
  (`JsonCache(cfg.cache_dir)`), so re-runs hit cache. `--max-score`, `--no-score`, `--out`,
  `--offline` flags exist.
- ✅ Stage-4 enforcement is real and frozen (`score.py`): `DISQUALIFIED_SCORE_CAP = 15`,
  `_ground_opener`, budget stop (`llm.spent_usd >= cfg.budget_usd`), `max_score` cap.
- ⚠️ **Live keys required for this session** (owner-managed in `.env`; do **not** touch `.env` /
  `.env.example`): `GOOGLE_MAPS_API_KEY` (Geocoding + Places Text Search New must be enabled on the
  key) and `OPENAI_API_KEY`. If a 403/REQUEST_DENIED appears, it's key enablement/restriction, not a
  code bug — `LivePlacesClient._raise_for_status` surfaces Google's exact message.

## Nature of this session (read before running anything)
- **Stages 1 & 3 are cached by `place_id` on disk** (`places_pages`/`places` and `enrich`
  namespaces). The **first** live run pays for Places + scraping; every re-run with the same geo is
  ~free for Stages 1–3. **Stage 4 is NOT cached** — every re-run re-scores survivors and re-spends
  LLM tokens.
- **Therefore the tuning loop is:** do the discovery+enrich once to warm the cache, then iterate on
  ICP/niche/prompt with `--max-score` kept **low** (start at 5, then 20) so each re-score is a few
  cents. Only widen `--max-score` for the final confirmation run.
- **`--max-score` caps the LLM, not Places.** Discovery cost is fixed by `tiles × keywords × pages`
  and is paid on the cold cache regardless of `--max-score`.

## The reviews gap — decision required (flag, don't silently fix)
`build_prompt` (`score.py:26`) feeds `lead.reviews[:5]` to the model, and the ICP's first pain signal
is *"reviews mention 'couldn't get through on phone' / 'hard to book'."* **But `lead.reviews` is
effectively always empty on live runs:** `LivePlacesClient.FIELD_MASK` (`clients.py:73`) does **not**
request `places.reviews`, and `enrich._extract` scrapes `site_text`/`email`/`owner`/`tech` but **no
reviews**. So the review-based pain signal can never be detected from real data today.

Two ways forward — **pick one before tuning:**
- **(Recommended) Defer live review-fetch to Session 07; lean openers on website signals.** The other
  pain signals — *no online booking link*, *DIY/outdated website* — are derivable from `site_text` +
  `detected_tech`, which **are** populated live. Tune `pain_signals` so the openers ground on those.
  Reorder/soften the review signal so the model isn't pushed to cite reviews it never saw. This keeps
  Session 06 pure data/prompt tuning, honoring the session's "tune data, not code" rule and CLAUDE.md
  "don't gold-plate discovery."
- **(Only if openers are unacceptably thin without reviews) Minimal scoped FIELD_MASK add.** Append
  `places.reviews` to `LivePlacesClient.FIELD_MASK` and map a few review texts in `_normalize` →
  `_raw_to_lead(reviews=...)`. **Caveat to verify first (never guess API behavior):** in Places API
  (New), `reviews` is an **Enterprise-tier (Atmosphere) field** and bumps the Text Search SKU to a
  materially higher price per call. Confirm the current SKU/price before enabling it, and weigh it
  against the per-run Places cost below. If chosen, it is a *small, additive* change — still no
  Session-07 scope.

Default this plan assumes **option 1**. If the executing session takes option 2, add a one-line note
to the commit and keep it minimal.

## Tuning knobs (all data; reference)
| Knob | File / field | When to change |
|---|---|---|
| Niche keywords | `dental.yaml: keywords` | Too few raw results, or too much adjacent junk |
| Category gate | `dental.yaml: place_type_allowlist` | Good clinics dropped as "place_type not in allowlist" — see note below |
| Size band | `clinic.yaml: size_proxy.review_count {min,max}` | Funnel too tight/loose; too-big chains leaking through |
| Website rule | `clinic.yaml: require_website` | Flip only if the product changes (sells-websites vs needs-online) |
| Contactability | `clinic.yaml: contactability` (`phone_or_named_email`/`phone`/`any`) | Too many good leads dropped as uncontactable, or junk passing |
| Pain signals | `clinic.yaml: pain_signals` | Openers weak/ungrounded; align to *observable* (website) signals |
| Disqualifiers | `clinic.yaml: disqualifiers` | Chains / Practo-listed not getting capped |
| LLM spend per iter | `--max-score` flag | Keep low (5→20) while iterating |
| Budget ceiling | `LEADSCOUT_BUDGET_USD` env | Hard stop; also used to prove the budget halt |
| Scoring model | `LEADSCOUT_SCORING_MODEL` env | Leave at `gpt-4o-mini` default unless cost/quality forces it |

**Likely first finding (`place_type_allowlist`):** Places API (New) `primaryType` for clinics is
often `dental_clinic` / `doctor`, not the legacy `dentist`. If many candidates are dropped with
reason `place_type '<x>' not in allowlist` in `out/disqualified.jsonl`, widen the allowlist to the
actual `primaryType` values observed — a textbook data-tuning fix, no code change.

## Implementation steps (ordered)
1. **Cold discovery run, no scoring** — warm the Stages 1–3 cache and inspect the funnel cheaply:
   ```
   uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --no-score
   ```
   Read the printed `discovered=… candidates=…` line and `out/disqualified.jsonl`. Watch the logs for
   `(tile,keyword) saturated…` warnings (the 60-result cap from `LivePlacesClient.search`) — if many
   tiles saturate, the geo is denser than one tile-set captures; **note it, do not implement
   subdivision** (that's Session 07's `resolve_tiles` TODO).
2. **Diagnose the funnel from `disqualified.jsonl`.** Group drop `reason`s. idea.md §7 expects roughly
   ~800 raw → ~100–140 candidates for a full city (proportionally fewer for a tighter geo). If
   candidates are near-zero, the dominant drop reason tells you which knob to turn (allowlist, size
   band, contactability, website). Tune **data**, re-run step 1 (Stages 1–3 now hit cache → fast/free)
   until the candidate set is sane.
3. **First scored run, tiny cap** — spend a few cents to read real openers:
   ```
   uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --max-score 5
   ```
   Read `out/leads.csv` rows (not just the count): are the top rows real, operational, owner-operated
   clinics? Does each `suggested_opener` reference a real `detected_signals` entry? Is `spent=$…`
   plausible and non-zero?
4. **Tune for grounded openers (data first).** Per the reviews-gap decision, align `pain_signals` to
   observable website signals so openers ground on `site_text`/`detected_tech`. Re-run step 3 (small
   `--max-score`) and re-read. `_ground_opener` will rewrite any opener that fails to cite a detected
   signal — but a rewrite firing often is a *smell* that the signals/prompt are off; fix the inputs,
   don't rely on the rewrite.
5. **Verify the disqualifier cap on real data.** Confirm a known chain / Practo-listed clinic appears
   with `disqualifiers_hit` non-empty and `fit_score <= 15`. If a known chain is *not* capped, tune
   `disqualifiers` wording (data) so the model recognizes it. Spot-check `detected_tech` contains
   `Practo` when a site links it (the marker is already in `enrich._TECH_MARKERS`).
6. **(Only if step 4 fails after data tuning) minimal prompt tightening.** Edit only `build_prompt`
   wording in `score.py` — emphasize *detect observable signals, don't vibe-check fit*, and that the
   opener must cite a specific detected signal. **Keep the `[[PLACE_ID:…]]` / `[[FIRST_SIGNAL:…]]`
   markers intact** (the fixture LLM depends on them) and keep the overall structure. Re-run
   `uv run pytest -q` — `tests/test_score.py` asserts on grounding/structure and must stay green.
7. **Final confirmation run** at a realistic cap, sanity-check cost vs. budget:
   ```
   uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --max-score 20
   ```
   Confirm `spent=$…` is well under `LEADSCOUT_BUDGET_USD` (default $2.00). Optionally prove the budget
   halt once: `LEADSCOUT_BUDGET_USD=0.0001 uv run leadscout run … --max-score 20` → `scored` <
   candidates, small `llm_calls`. (Bash-style env prefix; on PowerShell use
   `$env:LEADSCOUT_BUDGET_USD=0.0001; uv run …`.)
8. **Lock it in.** Commit the tuned `examples/clinic.yaml` + `examples/dental.yaml` (and the minimal
   `score.py` prompt tweak *iff* step 6 was needed). Flip `docs/sessions/session-06-real-run.md` status
   box and the `README.md` row to ✅. **Do not commit `out/` or `.cache/`** (gitignored; verify).

## Contracts & types (all stable — none change)
This is a tuning session. **No pydantic model, Protocol, or stage signature changes.** `ICPSpec`,
`NicheSpec`, `Lead`, `ScoreResult`, `RunConfig`, all `*Client` Protocols stay frozen. The only code
that may change is `score.build_prompt`'s **wording** (step 6, optional) and — only under reviews-gap
option 2 — an additive `FIELD_MASK` string + `_normalize`/`_raw_to_lead` review mapping. The YAML
edits stay within the existing schema (no new fields).

## Tests (offline; stay green — no live calls ever in pytest)
- **Keep green, unchanged:** the full suite (`uv run pytest -q` → 35) drives the **fixture** clients;
  it never touches Google/OpenAI and is unaffected by live tuning.
- **If `build_prompt` wording changes (step 6):** re-run `pytest`; `tests/test_score.py`
  (opener-grounding, disqualifier cap, budget stop, max-score, ranking via `FixtureLlmClient`) must
  stay green. If a literal-string assertion breaks on the new wording, update the *assertion* to match
  intent — do not weaken what it checks. Keep the tagged markers so the fixture lookup still works.
- **If YAML changes:** the offline run uses `fixtures/`, not `examples/`, so tuning `examples/*.yaml`
  doesn't affect tests. Still run the offline smoke (below) to confirm the YAML stays schema-valid:
  `load_icp`/`load_niche` will raise on a malformed file.
- **No new test file is required** for a data-tuning session. (Option 2's FIELD_MASK change would want
  a small offline `MockTransport` assertion that `reviews` flows into `lead.reviews` — add it only if
  option 2 is taken.)

## Final checks (the gate — all must pass)
```
uv run pytest -q          # 35+ green, fully offline
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline   # offline smoke: tuned YAML still schema-valid, pipeline intact
```
Plus the **live acceptance run** (step 7) by hand with real keys: top `out/leads.csv` rows are
call-ready with grounded openers, a known chain is capped low, and `spent_usd` is under budget.
**Never** add a live run to pytest.

## Definition of done (= MVP, idea.md §13)
A `leads.csv` ranked by `fit_score` whose top rows are real, operational, in-niche Bengaluru clinics
that plausibly have the ICP pain, each with a non-generic opener referencing a detected signal — for
a single tiled city, within budget. Tuned `examples/clinic.yaml` + `examples/dental.yaml` committed;
offline tests green; `ruff`/`mypy` clean; roadmap flipped to ✅.

**Commit message:**
```
Session 06: first live Bengaluru-dental run; tune ICP/niche for call-ready, grounded leads
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **Cost discipline / LLM only in Stage 4:** tuning changes no stage boundaries — Stages 1–3 stay
  zero-LLM. `--max-score` + `LEADSCOUT_BUDGET_USD` keep iteration spend bounded; the budget ceiling in
  `score.py` is the hard stop and is exercised in step 7.
- **Dedup on `place_id`:** unchanged — `discover.discover` dedups in `by_id`. Tiling overlap is why;
  do not remove it while tuning.
- **Scraping etiquette:** unchanged — `LiveHttpClient` honors robots.txt, caps concurrency, caches by
  `place_id`, backs off. Warm cache first; don't hammer sites across re-runs.
- **Legal (TRAI/TCCCPR):** output stays a list for a **human to contact manually**. Add **no**
  dialing / AI-voice / email-blast — not even a stub (idea.md §10).
- **Secrets never committed:** keys read via `require_key` from `.env` only. Don't touch `.env` /
  `.env.example`; keep the pre-commit secret check; don't stage `out/` or `.cache/`.
- **Openers grounded (#6):** the whole tuning target. Ground on **observable** signals; a generic
  opener is a failure repaired by `_ground_opener`, never shipped — but the goal is openers that don't
  need the rewrite.

## Risks / unknowns (verify at build time; don't assume)
- **Reviews are empty live** (see decision above) — the single biggest opener-quality risk. Default:
  defer to Session 07, ground on website signals. Option 2's `places.reviews` add changes the Places
  **pricing tier** — confirm the current Text Search (New) SKU/price for Enterprise/Atmosphere fields
  before enabling. **Don't guess Places pricing.**
- **Per-run Places cost (cold cache):** `tiles × keywords × pages` Text Search calls. Bengaluru's
  geocoded bbox tiled at 40 km (`_tile_bbox`) is on the order of a handful of tiles × 3 keywords × up
  to 3 pages → on the order of tens of calls. At current Text Search (New) Pro pricing that's a few
  dollars once, then ~free on cache. Confirm the live price before the first run; keep one geo while
  tuning so you don't re-pay discovery.
- **Tile saturation:** dense keywords may hit the 60-result/3-page cap (logged by
  `LivePlacesClient.search`); `resolve_tiles` does **not** subdivide yet (Session 07 TODO). Expect to
  under-count in dense cells — note it in the run summary, don't fix it here.
- **`primaryType` vs allowlist mismatch:** the most likely funnel killer (see tuning note). Diagnose
  from `disqualified.jsonl` before assuming low results mean "no clinics."
- **Pricing freshness (LLM):** `gpt-4o-mini` priced in `MODEL_PRICES` ($0.15/$0.60 per 1M, confirmed
  June 2026). If the owner switches `LEADSCOUT_SCORING_MODEL`, the unknown-model branch logs and uses
  `_DEFAULT_PRICE` — add the real model to `MODEL_PRICES` rather than trusting the fallback for budget
  accounting.
- **idea.md ⇄ code drift (flag, don't fix here):** idea.md §8 still says "LLM: OpenAI … gpt-4o-mini"
  in one place and "Anthropic" was discussed elsewhere; the code is committed to **OpenAI**
  (`pyproject` `openai>=1.40`, `cli.py` `OPENAI_API_KEY`, `config.DEFAULT_SCORING_MODEL`). Code wins;
  worth a one-line idea.md tidy in a later doc session, **out of scope here.**

## What NOT to do (don't pull work forward)
No JustDial/IndiaMART adapters, no bbox tile subdivision/saturation handling, no LinkedIn owner
enrichment, no SQLite/cross-run dedup (all Session 07). No new pydantic fields or stage-contract
changes. No live calls in pytest. Don't touch `.env`/`.env.example` or `score.py`'s enforcement
(`score`, `score_lead`, `_ground_opener`, `DISQUALIFIED_SCORE_CAP`). Prefer data tuning; treat any
code edit as a last resort and keep it minimal.
