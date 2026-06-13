# Session 05 — Live scoring (OpenAI)

**Status:** ✅ done
**Goal:** make Stage 4 — *the product* — real. Replace `LiveLlmClient` stubs with a live OpenAI
structured-output call that returns a `ScoreResult`, accumulates real token cost into `spent_usd`,
and is enforced by the budget ceiling already in `score.py`.
**Prereq:** Session 04 done (enriched candidates with site text + reviews). `OPENAI_API_KEY` set.

## Spend the effort HERE (CLAUDE.md core principle)
This is the un-commoditized 95%. Stages 1–4 plumbing should be boring; the prompt and output
quality are the value.

## Research first
- Check current OpenAI model IDs + pricing. Default model: `gpt-4o-mini` (configurable via
  `LEADSCOUT_SCORING_MODEL`) — cheap, per-lead step. Confirm it supports Structured Outputs.
- Use **Structured Outputs** (`response_format={"type":"json_schema", ...}` with `strict: true`,
  schema derived from `ScoreResult.model_json_schema()`) so the response parses straight into
  `ScoreResult` — no prose, no regex.

## Steps
1. Implement `LiveLlmClient.score(model, prompt)` using the `openai` SDK:
   - `client.chat.completions.create(...)` (or the Responses API) with the prompt from
     `score.build_prompt` and a json_schema `response_format` matching `ScoreResult`.
   - Parse into `ScoreResult`; on parse/refusal failure, retry once then raise (don't ship garbage).
   - Accumulate cost from `response.usage` (prompt+completion tokens × model price) → `self._spent`.
2. Confirm the enforced rules still hold end-to-end (they live in `score.py`, not the prompt):
   - `disqualifiers_hit` non-empty ⇒ `fit_score` capped at `DISQUALIFIED_SCORE_CAP`.
   - Opener that doesn't reference a detected signal ⇒ `_ground_opener` rewrites it. **A generic
     opener is a failure, not a fallback.**
   - Budget ceiling stops scoring mid-run; `max_score` caps candidate count.
3. Tighten `build_prompt` if needed: emphasize *detect observable signals, don't vibe-check fit*.

## Verify
- Live score on ~5 real enriched candidates returns valid `ScoreResult`s; openers cite real
  signals; a known chain/Practo business gets capped low.
- `spent_usd` reflects real tokens; set `LEADSCOUT_BUDGET_USD` low and confirm it halts scoring.
- Offline tests (fixture LLM) still green.

## Definition of done
Live, grounded, budget-enforced scoring on real candidates; offline tests green. Commit. Update
roadmap. After this session the full live pipeline runs end-to-end.
