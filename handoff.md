# Session Handoff
_Generated: 2026-06-13_

## Goal
LeadScout is an internal CLI: given an ICP + geography + niche keywords, it discovers local
businesses (Stage 1), filters/qualifies them deterministically (Stage 2), enriches survivors
(Stage 3), and runs a single LLM scoring step (Stage 4) that emits a ranked, call-ready lead list
with a grounded opener per lead. Work proceeds **one session per file** under `docs/sessions/`.
This handoff closes **Session 05 (live scoring / OpenAI)** and sets up **Session 06 (first real run
& ICP/filter tuning)**.

Process rules (from CLAUDE.md): Stages 1–3 are deterministic with **zero** LLM calls; the LLM
touches **only Stage 4**, only on Stage-2 survivors, under a per-run USD budget ceiling. Tests must
be green and fully offline (no live calls). Don't touch `.env`/`.env.example`. Don't stage
`.cache/` or `out/`. The user commits themselves — do **not** run `git commit`.

## Current State
**Session 05 is ✅ done** (status flipped in `docs/sessions/session-05-live-score.md` and the README
roadmap row). The full live pipeline now runs end-to-end:

- `LiveLlmClient` (`src/leadscout/clients.py`) is real. `score()` calls
  `client.beta.chat.completions.parse(response_format=ScoreResult, temperature=0)` (OpenAI
  Structured Outputs → parses straight into `ScoreResult`, no regex). On refusal/no-parse/transient
  error it retries **once**, then raises (never ships a default score). Cost + call count accrue
  **only on success**.
- Added module-level `MODEL_PRICES` (`gpt-4o-mini` = `(0.00015, 0.00060)` per 1K in/out),
  `_DEFAULT_PRICE` fallback (warn-logged for unpriced models so the budget ceiling never becomes a
  $0 no-op), and `_cost_usd(model, prompt_tokens, completion_tokens)`.
- `LiveLlmClient.__init__` now takes an injectable `client: OpenAI | None` **test seam** (mirrors
  Places/HTTP clients). `from openai import OpenAI` added at module top (already a hard dep).
- **Gate green:** `uv run pytest -q` → **35 passed** (8 new in `tests/test_live_score.py`, all
  offline via an injected fake — zero network, zero key), `ruff` clean, `mypy` clean, offline smoke
  run unchanged (`scored=2 spent=$0.0040`).
- **Live spot-check passed** (real keys present in `.env`):
  - `--max-score 5`: `scored=5 spent=$0.0009`; all 5 openers grounded in the detected "couldn't get
    through on phone / hard to book" signal.
  - Practo-listed "Smile Care Orthodontic Center" hit a disqualifier → capped at **fit=15**
    (`DISQUALIFIED_SCORE_CAP`); lands in `leads.jsonl`, not `disqualified.jsonl`.
  - `LEADSCOUT_BUDGET_USD=0.0001` → halted after **1 call** (`scored=1`), proving the real-money
    ceiling stops mid-run.

**Also fixed this session (doc drift):** `idea.md:214` §8 said "LLM: Anthropic API"; corrected to
"OpenAI API (Structured Outputs / structured JSON); model configurable (default `gpt-4o-mini`)" to
match `pyproject` (`openai>=1.40`, no `anthropic`), `config.DEFAULT_SCORING_MODEL`, and `cli.py`.

**Likely uncommitted:** Session 05 changes + the `idea.md` fix are probably not committed yet, and
`Implementations/step05_implementation.md` is untracked. Check `git status`; if uncommitted, remind
the user to commit (don't do it yourself). Suggested message:
`Live scoring (Stage 4): OpenAI structured-output ScoreResult + real token-cost budget accounting`

## Files Being Edited
- `src/leadscout/clients.py` — DONE. Added `MODEL_PRICES`/`_DEFAULT_PRICE`/`_cost_usd`; rewrote
  `LiveLlmClient.__init__` (injectable `client` seam) and `.score` (real `.parse()` call, retry,
  cost accrual). `import OpenAI` at top. `LlmClient` Protocol + `FixtureLlmClient` unchanged.
- `tests/test_live_score.py` — DONE (new). 8 offline tests with a `_FakeParse` fake exposing
  `.beta.chat.completions.parse`: cost accrual, wiring (model/response_format/messages),
  refusal-retry-then-raise, refusal-then-recover, parse-exception retry/propagate, cost table +
  fallback warning, and an integration test proving it plugs into `score.py`'s budget loop.
- `idea.md` — DONE. §8 LLM line switched Anthropic → OpenAI.
- `docs/sessions/session-05-live-score.md`, `docs/sessions/README.md` — DONE. Status → ✅.
- `src/leadscout/stages/score.py` — UNCHANGED (frozen enforcement: budget/max_score gating,
  disqualifier cap, `_ground_opener`). Central to Session 06 — **do not regress.**

## What We Tried That Failed
- Nothing dead-ended. Minor self-caught items during the build: (1) confirmed the installed
  `openai==2.41.1` exposes `.parse` on **both** `chat.completions` and `beta.chat.completions` —
  used the `beta` path per the plan. (2) `ruff` flagged a long docstring line + a blind
  `pytest.raises(Exception)` → tightened to `pytest.raises(ValueError)`. (3) `mypy` flagged
  `resp.usage` as `CompletionUsage | None` → added an explicit `if usage is None: raise` guard
  before reading token counts. All resolved; gate fully green.

## Next Step
**Start Session 06 — first real run & ICP/filter tuning.** Open
`docs/sessions/session-06-real-run.md` and follow its steps. This is the first session where the
*full* live pipeline (discover → filter → enrich → score) runs end-to-end on real Bengaluru-dental
data and the output quality gets judged and tuned. Expect work on: ICP `pain_signals`/`disqualifiers`
wording, the Stage-2 filter bands (`size_proxy.review_count` 5–150, `contactability`,
`require_website`), and possibly `score.build_prompt` wording if openers/signals come back weak.
Tuning is **config-first** (edit `examples/clinic.yaml` / `examples/dental.yaml`), code changes only
if a filter/contract genuinely needs it. Read the session file before touching anything — don't pull
Session 07 work forward.

Recommended: write an `Implementations/step06_implementation.md` plan (same style as step05) and
confirm it with the user before editing, since Session 06 is judgment-heavy.

## Additional Context
- **Stack:** Python 3.11+, `uv`, `ruff`, `mypy` (pydantic plugin), `typer`, `httpx`, `pydantic`,
  `openai==2.41.1`, `pandas` (CSV out). All deps installed; no `uv add` needed.
- **Commands:**
  - Tests: `uv run pytest -q`
  - Lint/types: `uv run ruff check .` · `uv run mypy`
  - Offline run (no keys): `uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru"
    --niche examples/dental.yaml --offline`
  - Live run (needs keys in `.env`): same without `--offline`; add `--max-score N` to cap LLM calls
    and `LEADSCOUT_BUDGET_USD=…` to test the ceiling. **Never** add live commands to pytest.
- **Pricing note:** `MODEL_PRICES` is hardcoded (confirmed June 2026). If the owner switches
  `LEADSCOUT_SCORING_MODEL` to an unlisted model, `_cost_usd` logs a warning and uses
  `_DEFAULT_PRICE` — add the new model to the table rather than guessing silently.
- **Output behavior:** every run writes `out/leads.csv`, `out/leads.jsonl`, `out/disqualified.jsonl`
  — all overwritten each run (`"w"` mode). `disqualified.jsonl` is always created (empty if nothing
  dropped); it holds **Stage-2 filter drops** (audit), NOT Stage-4 disqualifier-capped leads (those
  stay in `leads.jsonl` at `fit≈15`).
- **Test seam pattern (reusable):** every live client takes an injectable client param
  (`httpx.MockTransport` for Places/HTTP, a fake `OpenAI` for LLM) so pytest stays fully offline.
- **Deferred (do NOT pull forward — Session 07+):** JustDial/IndiaMART adapters, state tiling, owner
  enrichment, SQLite, and live reviews-from-Places-Details (still scrape-derived; Stage-1 mask omits
  `places.reviews`). Review-signal quality may surface during Session 06 tuning — note it, don't
  rebuild Stage 1.
