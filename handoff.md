# Session Handoff
_Generated: 2026-06-13_

## Goal
LeadScout is an internal CLI: given an ICP + geography + niche keywords, it discovers local
businesses (Stage 1), filters/qualifies them deterministically (Stage 2), enriches survivors
(Stage 3), and runs a single LLM scoring step (Stage 4) that emits a ranked, call-ready lead list
with a grounded opener per lead. Work proceeds **one session per file** under `docs/sessions/`.
This handoff closes **Session 04 (live enrichment / scraping)** and sets up **Session 05 (live
scoring / OpenAI)**.

Process rules (from CLAUDE.md): Stages 1–3 are deterministic with **zero** LLM calls; the LLM
touches **only Stage 4**, only on Stage-2 survivors, under a per-run USD budget ceiling. Tests must
be green and fully offline (no live calls). Don't touch `.env`/`.env.example`. Don't stage
`.cache/` or `out/`. The user commits themselves — do **not** run `git commit`.

## Current State
**Session 04 is functionally ✅ done** (status flipped to ✅ in `docs/sessions/session-04-live-enrich.md`
and the README roadmap row):
- `LiveHttpClient` rewritten as a real async scraper over a shared `httpx.AsyncClient`: per-host
  `robots.txt` fetched/parsed/cached/honored; `asyncio.Semaphore(max_concurrency)` caps in-flight
  GETs; per-request timeout + bounded exponential backoff on 429/5xx/network.
- New `AsyncHttpClient` Protocol + `enrich.enrich_async` (concurrent `asyncio.gather` over leads),
  sharing a `_merge` helper with the unchanged sync `enrich_lead`. Pipeline branches on
  `cfg.offline` (sync `enrich` vs `asyncio.run(enrich_async(...))`).
- **Gate green:** `uv run pytest -q` → 27 passed (18 old + 9 new), `ruff` clean, `mypy` clean,
  offline smoke run unchanged.
- **Live spot-check passed:** real Bengaluru dental run scraped 27 candidates — emails/owners/tech
  extracted where present, robots-disallowed/dead hosts skipped (cached empty `{}`, no crash),
  second run made **0** new fetches (29→29 enrich cache files, ~5s).

**Stage 4 is still stubbed:** `LiveLlmClient.score` in `src/leadscout/clients.py` raises
`NotImplementedError`. So a **live** full run (without `--no-score`) crashes at scoring today. The
offline path (`--offline`, fixture scorer) produces full populated output (`top: Bright Smile
Dental fit=88`).

**Known non-issue:** with `--no-score`, `leads.csv` / `leads.jsonl` come out empty. That's correct
— `--no-score` sets `cfg.max_score=0`, so `score()` returns `[]`, and `write_outputs` writes the
*scored* list. Enriched-but-unscored candidates live in `.cache/enrich/*.json`, not the output
files. Not a bug.

**Likely uncommitted:** Session 04 changes may not be committed yet. Check `git status` first; if
uncommitted, remind the user to commit (don't do it yourself).

## Files Being Edited
- `src/leadscout/clients.py` — DONE. Added `AsyncHttpClient` Protocol; rewrote `LiveHttpClient`
  (async, robots cache, semaphore, retry/backoff). `LiveLlmClient.score` still a
  `NotImplementedError` stub — **this is the Session 05 target.**
- `src/leadscout/stages/enrich.py` — DONE. Added `enrich_async` + `_merge`; sync path unchanged.
- `src/leadscout/pipeline.py` — DONE. Stage-3 branches on `cfg.offline`; `http` param widened to
  `HttpClient | AsyncHttpClient`.
- `src/leadscout/cli.py` — DONE. Builds `LiveHttpClient(timeout_s=, max_concurrency=)`; widened
  annotation.
- `tests/test_live_enrich.py` — DONE. 9 offline tests via `httpx.MockTransport` + `AsyncClient`,
  driven by `asyncio.run` (no pytest-asyncio).
- `src/leadscout/stages/score.py` — UNCHANGED but central to Session 05. Already has budget/
  max_score gating and `_ground_opener` (enforces opener references a real detected_signal). Don't
  regress these.

## What We Tried That Failed
- Nothing dead-ended. One self-caught slip: initially called the sync `enrich` with swapped arg
  order in `pipeline.py` (`enrich(http, cache, candidates)`); fixed to `enrich(candidates, http,
  cache)`. No other false starts.

## Next Step
**Start Session 05 — live scoring.** Open `docs/sessions/session-05-live-score.md` and follow its
steps. The core task: replace the `LiveLlmClient.score` stub (`src/leadscout/clients.py`) with a
real OpenAI structured-output call that returns a `ScoreResult` (json_schema matching the model),
accumulates token cost into `spent_usd`, and respects `cfg.budget_usd` (ceiling) + `cfg.max_score`
(cap — already enforced in `score.py`). Keep `FixtureLlmClient` and the entire offline path
byte-for-byte unchanged; all 27 existing tests must stay green; exercise the live client **only via
an injected mock** (no live calls in pytest). Honor non-negotiable #6: `suggested_opener` must
reference a real `detected_signal` (`score.py:_ground_opener` already does this — don't break it).

Recommended: before coding, read `Implementations/step04_implementation.md` as the planning model,
then write an equivalent `step05` implementation plan and confirm it with the user before writing
code.

## Additional Context
- **Stack:** Python 3.11+, `uv`, `ruff`, `mypy` (pydantic plugin), `typer`, `httpx`, `pydantic`,
  `pandas` (CSV out). `openai` SDK will be needed for Session 05 — check it's installed (`uv add`
  if not).
- **Commands:**
  - Tests: `uv run pytest -q`
  - Lint/types: `uv run ruff check .` · `uv run mypy`
  - Offline run (full pipeline, fixture LLM, no keys): `uv run leadscout run --icp
    examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline`
- **Test seam pattern:** live clients take an injectable client param
  (`httpx.MockTransport` for Places/HTTP). Mirror this for OpenAI in Session 05 so pytest stays
  offline.
- **Key decision (Session 04):** robots.txt indeterminate (5xx / network error) → **disallow**
  (conservative). 4xx → allow-all. Confirmed acceptable.
- **Deferred (do NOT pull forward):** reviews-from-Places-Details (touches Stage-1 PlacesClient
  contract, slated for a later session); JustDial/IndiaMART; state tiling; owner enrichment;
  SQLite. Stage-1 and Stage-4 contracts stay frozen except the `LiveLlmClient.score` impl.
- **Prompt builder** already exists: `score.build_prompt(lead, icp)` embeds `[[PLACE_ID:..]]` /
  `[[FIRST_SIGNAL:..]]` tags for the fixture LLM; the live model ignores them and reads the NL
  body. Reuse it — don't rewrite the prompt for the live path.
