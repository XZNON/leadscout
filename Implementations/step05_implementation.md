# Step 05 — Live scoring (OpenAI structured output) — implementation plan

> Source of truth: `docs/sessions/session-05-live-score.md`. This file is the worked-out *how* for
> that one step. **Do not pull work forward** from Session 06 (no real end-to-end ICP/filter tuning)
> or Session 07 (no JustDial/IndiaMART, state tiling, owner enrichment, SQLite). This step makes
> **Stage 4 only** real: replace the single `LiveLlmClient.score` `NotImplementedError` stub with a
> live OpenAI Structured-Outputs call that returns a `ScoreResult` and accumulates real token cost
> into `spent_usd`. **The rules that make the product trustworthy already live in `score.py`
> (`score`, `score_lead`, `_ground_opener`, `DISQUALIFIED_SCORE_CAP`) and do not change** — this
> session is about *getting a real, parse-safe `ScoreResult` from the model*, nothing more.

## Goal & scope
Make Stage 4 — *the product* — real. Implement `LiveLlmClient.score(model, prompt)` in
`src/leadscout/clients.py` using the `openai` SDK with **Structured Outputs** so the response parses
straight into `ScoreResult` (no prose, no regex). On parse/refusal failure, retry once, then raise
(never ship garbage). Accumulate real cost from `response.usage` (prompt+completion tokens × the
model's price) into `self._spent`, and bump `self._calls`. "Done" means: a live score on ~5 real
enriched Bengaluru-dental candidates returns valid `ScoreResult`s whose openers cite a real detected
signal; a known chain / Practo-listed business gets `fit_score` capped low (via the existing
`DISQUALIFIED_SCORE_CAP` path); `spent_usd` reflects real tokens; setting `LEADSCOUT_BUDGET_USD` low
halts scoring mid-run; and **all offline tests stay green with zero live calls** — the live client is
exercised only through a mocked OpenAI client / monkeypatch. The enforcement code in `score.py` and
the `LlmClient` Protocol stay **frozen**.

## Prerequisites (confirmed)
- ✅ Sessions 01–04 done (roadmap + code agree): `LivePlacesClient` and `LiveHttpClient` are real;
  there are real enriched candidates (`site_text`, `reviews`, `detected_tech`, `email`) to score.
  `LiveLlmClient.score` is the **only** remaining live stub raising `NotImplementedError`
  (`clients.py:387`).
- ✅ `score.py` already enforces every Stage-4 non-negotiable independently of the model output:
  budget ceiling (`llm.spent_usd >= cfg.budget_usd` → stop), `max_score` cap, disqualifier →
  `min(fit_score, DISQUALIFIED_SCORE_CAP)`, and `_ground_opener` rewriting a non-grounded opener.
  **These are tested and must not change.**
- ✅ `ScoreResult` (`models.py:133`) is the structured contract: `fit_score: int (0–100)`,
  `detected_signals: list[str]`, `disqualifiers_hit: list[str]`, `reasoning: str`,
  `suggested_opener: str`. This is the schema the live call must satisfy.
- ✅ `build_prompt(lead, icp)` (`score.py:21`) already produces a strong natural-language prompt and
  embeds `[[PLACE_ID:..]]` / `[[FIRST_SIGNAL:..]]` markers — those are **only** for the *fixture*
  client's deterministic lookup; the live model simply ignores them. No change required to call it.
- ✅ `RunConfig` carries `scoring_model` (default `gpt-4o-mini`, `config.py:15`) and `budget_usd`
  (default `2.00`), both overridable via `LEADSCOUT_SCORING_MODEL` / `LEADSCOUT_BUDGET_USD`
  (`config.from_env`). The live model id is passed into `score(model, prompt)` from
  `cfg.scoring_model`.
- ✅ `openai>=1.40` is already a dependency (`pyproject.toml:12`) — has the structured-output Pydantic
  parse helper. **No new dependency.** The CLI already wires
  `LiveLlmClient(require_key("OPENAI_API_KEY"))` in the live branch (`cli.py:68`).
- ⚠️ Live spot-check needs `OPENAI_API_KEY` (and `GOOGLE_MAPS_API_KEY` to produce candidates) in
  `.env`. Owner-managed — do **not** touch `.env` / `.env.example`. Tests never need either key.

## Research (done — do not guess; re-confirm at build time if SDK errors)
- **Model + Structured Outputs:** `gpt-4o-mini` (the configured default) **supports** Structured
  Outputs with `strict: true` (constrained decoding → schema conformance is a hard guarantee, not
  best-effort). Use it; keep the model id read from `cfg.scoring_model` so it stays configurable.
- **SDK call (recommended):** `openai>=1.40` exposes `client.beta.chat.completions.parse(...)`, which
  accepts `response_format=<PydanticModel>` directly, derives the strict JSON schema, parses the
  response, and exposes `message.parsed` (a `ScoreResult`) and `message.refusal`. This is cleaner and
  safer than hand-writing `response_format={"type":"json_schema", ...}` from
  `ScoreResult.model_json_schema()` (which needs manual `additionalProperties:false` + all-required
  patching). **Plan uses `.parse()`**; the raw-`json_schema` form is the documented fallback if the
  installed SDK lacks `.parse`.
- **Refusals:** with `.parse()`, a safety refusal surfaces as `message.refusal` (non-null) and
  `message.parsed is None` — treat as a failure (retry once, then raise), do **not** coerce to a
  default `ScoreResult`.
- **Pricing (for `spent_usd`):** `gpt-4o-mini` = **$0.15 / 1M input tokens**, **$0.60 / 1M output
  tokens** (confirmed June 2026). Token counts come from `response.usage.prompt_tokens` /
  `completion_tokens`. Unknown models → fall back to a conservative default rate **and log a warning**
  (don't silently price at $0, or the budget ceiling becomes a no-op).

## Files to create / modify
- `src/leadscout/clients.py` — **modify.** (1) Add a tiny price table + helper near the LLM section:
  `MODEL_PRICES: dict[str, tuple[float, float]]` mapping model id → `(usd_per_1k_input,
  usd_per_1k_output)` with a `gpt-4o-mini` entry and a documented `_DEFAULT_PRICE` fallback; a
  `_cost_usd(model, prompt_tokens, completion_tokens) -> float` helper. (2) Rewrite
  `LiveLlmClient.__init__` to lazily build an `openai.OpenAI` client (or accept an injected `client`
  **test seam**, mirroring how `LivePlacesClient`/`LiveHttpClient` take an injectable client).
  (3) Implement `LiveLlmClient.score(model, prompt)`: call `.parse()`, retry once on
  parse/refusal/transient error, raise on second failure, accumulate `_spent` and `_calls`. Keep the
  `call_count` / `spent_usd` properties and the `LlmClient` Protocol **unchanged**.
- `tests/test_live_score.py` — **create.** Offline-only tests that inject a fake/mocked OpenAI client
  into `LiveLlmClient` (no network, no key). See **Tests**.
- `docs/sessions/session-05-live-score.md` & `docs/sessions/README.md` — flipped to ✅ **only after**
  the live spot-check + gate pass (done by the *implementing* session, not this planning one).
- *(no change)* `score.py`, `models.py`, `config.py`, `cli.py`, `pipeline.py` — already wired; do not
  edit. (`cli.py:68` already constructs `LiveLlmClient(require_key("OPENAI_API_KEY"))`.)

## Implementation steps (ordered, each independently verifiable)
1. **Price table + cost helper.** In `clients.py`, near the LLM section, add:
   ```python
   # USD per 1K tokens (input, output). Confirmed June 2026; update if OpenAI repricing.
   MODEL_PRICES: dict[str, tuple[float, float]] = {"gpt-4o-mini": (0.00015, 0.00060)}
   _DEFAULT_PRICE = (0.00015, 0.00060)  # conservative fallback; logged on use
   def _cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float: ...
   ```
   `_cost_usd` looks up `MODEL_PRICES.get(model, _DEFAULT_PRICE)` (warn-log on fallback) and returns
   `in_tok/1000*in_rate + out_tok/1000*out_rate`. *Verify:* unit-tested directly (known tokens →
   known cost).
2. **`LiveLlmClient.__init__`.** Signature
   `(self, api_key: str, client: "OpenAI | None" = None)`. Store `self._calls = 0`, `self._spent =
   0.0`, and `self._client = client or OpenAI(api_key=api_key)`. Import the SDK **lazily/at module
   top guarded** so importing `clients.py` never requires the package at runtime for the fixture path
   (it's already a hard dep, so a top-level `from openai import OpenAI` is acceptable; prefer it for
   clean typing). The `client` param is the **offline test seam** — inject a fake exposing
   `.beta.chat.completions.parse(...)`; it is impl detail, not part of the `LlmClient` Protocol.
   *Verify:* constructs with a fake client, no network.
3. **`LiveLlmClient.score(model, prompt)`.** Replace the `NotImplementedError` body:
   ```python
   for attempt in range(2):  # one retry, then raise
       try:
           resp = self._client.beta.chat.completions.parse(
               model=model,
               messages=[{"role": "user", "content": prompt}],
               response_format=ScoreResult,
               temperature=0,
           )
           msg = resp.choices[0].message
           if msg.refusal or msg.parsed is None:
               raise ValueError(f"model refused or returned no parse: {msg.refusal!r}")
           result = msg.parsed
           usage = resp.usage
           self._spent += _cost_usd(model, usage.prompt_tokens, usage.completion_tokens)
           self._calls += 1
           return result
       except Exception:
           if attempt == 0:
               continue
           raise
   ```
   Notes: `temperature=0` for determinism/repeatability; cost + call count accrue **only on success**
   (so a failed-then-retried call isn't double-charged); on the second failure the exception
   propagates (don't ship garbage). *Verify:* tests below.
4. **Confirm enforcement is untouched.** Re-read `score.score` / `score_lead` — they already cap
   disqualified `fit_score`, ground the opener, honor `max_score`, and stop on budget. **Do not
   reimplement any of this in the client.** The client's only jobs are: return a valid `ScoreResult`
   and report real `spent_usd`. *Verify:* existing `tests/test_score.py` stays green unchanged.
5. **(Optional, only if needed) tighten `build_prompt`.** The current prompt already says *"Detect
   OBSERVABLE pain signals; do not vibe-check fit"* and *"suggested_opener MUST reference one specific
   detected_signal."* Leave it unless the live spot-check (step 6) shows weak/ungrounded openers; if
   so, make the *minimal* wording change and keep the `[[PLACE_ID]]`/`[[FIRST_SIGNAL]]` markers intact
   (the fixture client depends on them). Do not restructure the prompt.
6. **Live spot-check (manual, not in CI).** With real keys in `.env`, run a tight Bengaluru geo on
   ~5 candidates:
   `uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --max-score 5`.
   Confirm: each top lead's `suggested_opener` references a real `detected_signal`; a chain / Practo
   business lands `fit_score <= 15`; `spent=$…` is non-zero and plausible. Then re-run with
   `LEADSCOUT_BUDGET_USD=0.0001` and confirm scoring halts early (`scored` < candidates,
   `llm_calls` small). **Never** add either command to pytest.

## Contracts & types (touched vs. stable)
- **Stable (do not change):** `LlmClient` Protocol (`score`/`call_count`/`spent_usd`), `ScoreResult`
  and every other model, `score.py` in full (`score`, `score_lead`, `build_prompt` body sans optional
  step 5, `_ground_opener`, `_overlaps`, `DISQUALIFIED_SCORE_CAP`), `FixtureLlmClient`, `RunConfig`,
  `pipeline.run_pipeline`, `cli.run`. The fixture path that all current tests drive is byte-for-byte
  unchanged.
- **Touched (implementation detail / additive only):** `LiveLlmClient.__init__` (adds injectable
  `client` seam) and `.score` body (was an unimplemented stub — no caller depends on its internals);
  new module-level `MODEL_PRICES` / `_DEFAULT_PRICE` / `_cost_usd` in `clients.py`. Anything beyond
  this touching a shared contract is out of scope — stop and reassess.

## Tests (existing stay green; one new file, all offline)
- **Keep green, unchanged:** `tests/test_score.py` (opener-grounding, disqualifier cap, budget-stops,
  max-score cap, ranking — all via `FixtureLlmClient`), `tests/test_pipeline.py` (offline pipeline),
  and the rest. They never touch OpenAI.
- **New `tests/test_live_score.py` (offline; inject a fake OpenAI client via the `client= ` seam — no
  key, no network):**
  - A small `_FakeParse` helper builds a fake response object mimicking the SDK shape:
    `resp.choices[0].message.parsed` (a `ScoreResult`) / `.refusal`, and
    `resp.usage.prompt_tokens` / `.completion_tokens`. The fake `client.beta.chat.completions.parse`
    records call args and returns a queued response.
  - `test_score_parses_and_accrues_cost`: parse returns a valid `ScoreResult` with usage
    `(1000 in, 500 out)`; assert the returned object equals it, `call_count == 1`, and
    `spent_usd == 1000/1000*0.00015 + 500/1000*0.00060` (i.e. `0.00045`) within float tolerance.
  - `test_passes_model_and_response_format`: assert the fake received `model=<cfg model>`,
    `response_format=ScoreResult`, and the prompt string as the user message (proves wiring).
  - `test_refusal_retries_then_raises`: first call returns `refusal="cannot help"` / `parsed=None`,
    second call also refuses → assert `score(...)` raises and `call_count == 0`, `spent_usd == 0.0`
    (nothing charged on failure). A variant where the **second** call succeeds → assert it returns the
    parsed result and `call_count == 1` (one retry recovers).
  - `test_parse_exception_retries_once`: first `parse` raises `RuntimeError`, second returns valid →
    assert success and `call_count == 1`; first raises twice → assert it propagates.
  - `test_cost_usd_table_and_fallback`: `_cost_usd("gpt-4o-mini", 1_000_000, 0) == 0.15`;
    `_cost_usd("unknown-model", 1000, 1000)` uses `_DEFAULT_PRICE` (and, if feasible, assert a warning
    was logged via `caplog`).
  - *(integration, still offline)* `test_live_client_obeys_budget_in_score_loop`: build a
    `LiveLlmClient` with a fake whose every response reports usage that costs ~$1; run
    `score([leadA, leadB, leadC], icp, live_llm, RunConfig(budget_usd=1.5))` and assert it stops after
    the ceiling is crossed (fewer than 3 calls) — proving the real client plugs into the existing
    `score.py` budget loop. (No new behavior; just confirms the seam composes.)
  - All construct `LiveLlmClient(api_key="test", client=<fake>)` — **zero network, zero key needed.**

## Final checks (the gate — all must pass)
```
uv run pytest -q            # existing suite + new test_live_score.py, all offline/green
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline   # smoke: offline path unchanged
```
Plus the **manual live spot-check** (step 6: ~5 candidates score with grounded openers; a low
`LEADSCOUT_BUDGET_USD` halts scoring) — by hand with real keys, **never** added to pytest.

## Definition of done
Live, grounded, budget-enforced scoring on real candidates: `LiveLlmClient.score` returns a valid
`ScoreResult` via OpenAI Structured Outputs, `spent_usd` reflects real tokens, the budget ceiling
halts scoring mid-run, disqualified/known-chain businesses are capped low, and openers cite a real
detected signal; offline tests green; `ruff`/`mypy` clean. After this, the full live pipeline runs
end-to-end. Then flip Session 05 → ✅ (status box + README row) and commit.

**Commit message:**
```
Live scoring (Stage 4): OpenAI structured-output ScoreResult + real token-cost budget accounting
```

## Non-negotiables touched & how honored
- **Cost discipline / LLM only in Stage 4:** the live call is added **only** to `LiveLlmClient`,
  invoked **only** by `score.score`, which runs **only** on Stage-2 survivors (and at most
  `max_score` of them). `spent_usd` now reflects *real* `response.usage` tokens, so the existing
  `budget_usd` ceiling in `score.py` becomes a real-money stop. Stages 1–3 keep **zero** LLM calls.
- **Openers grounded (#6):** unchanged and still enforced in `_ground_opener` — the prompt asks the
  model to ground the opener, and `score_lead` rewrites it to cite the first detected signal if it
  doesn't. A generic opener remains a *failure*, repaired, never shipped.
- **Disqualifier cap:** unchanged — `disqualifiers_hit` non-empty ⇒ `fit_score` capped at
  `DISQUALIFIED_SCORE_CAP` regardless of model output.
- **Secrets never committed:** `OPENAI_API_KEY` read via `require_key` from `.env` only on live runs;
  tests inject a fake client and need no key. Do not touch `.env` / `.env.example`; pre-commit secret
  hook stays; don't stage `out/` or `.cache/`.
- **Legal / scraping:** untouched — Stage 4 adds no dialing/outreach and no network beyond the single
  OpenAI scoring call.

## Risks / unknowns (verify at build time; don't assume)
- **SDK surface drift:** the plan uses `client.beta.chat.completions.parse(response_format=ScoreResult)`.
  If the *installed* `openai` version moved this out of `.beta` (or renamed it), confirm the exact
  path with `uv run python -c "import openai, inspect; ..."` before coding; fallback is the raw
  `response_format={"type":"json_schema","json_schema":{"name":"ScoreResult","strict":true,"schema":
  <patched ScoreResult.model_json_schema()>}}` form + `json.loads` → `ScoreResult.model_validate`.
  **Don't guess the method path — check the installed SDK.**
- **Strict-schema requirements:** OpenAI strict mode needs `additionalProperties:false` and *all*
  properties in `required`. `.parse()` handles this; the raw-schema fallback must patch it manually.
  `ScoreResult`'s list/str fields all have defaults, which strict mode will still mark required — fine
  (the model always emits them).
- **Pricing freshness:** rates ($0.15 / $0.60 per 1M) confirmed June 2026 — if OpenAI reprices or the
  owner switches `LEADSCOUT_SCORING_MODEL`, the unknown-model branch logs and uses `_DEFAULT_PRICE`;
  add the new model to `MODEL_PRICES` rather than guessing silently.
- **Reviews quality (deferred from Session 04):** `build_prompt` already reads `lead.reviews`, but the
  Stage-1 Places mask still omits `places.reviews`, so reviews are scrape-derived only. Signal quality
  tuning belongs to **Session 06**, not here — note it, don't fix it.
- **idea.md ⇄ code drift (flag, don't resolve here):** `idea.md §8` says "LLM: Anthropic API", but the
  code, `pyproject` (`openai>=1.40`, no `anthropic`), `config.DEFAULT_SCORING_MODEL = gpt-4o-mini`,
  `cli.py` (`OPENAI_API_KEY`), and the session-05 title all commit to **OpenAI**. Per CLAUDE.md
  process + the kickoff rule, code wins; this plan implements OpenAI. Worth a one-line `idea.md` fix
  in a later doc-tidy session, but **out of scope for this build step.**

## What NOT to do (don't pull work forward)
- No ICP/filter tuning or full real-run analysis (Session 06). No JustDial/IndiaMART, state tiling,
  owner enrichment, or SQLite (Session 07). No live review-fetch from Places Details (deferred). Do
  not touch `score.py`'s enforcement, the `LlmClient` Protocol, or any other stage's contract.
