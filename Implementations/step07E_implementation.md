# Step 07E — Opener format variants (call-script / email / WhatsApp) — implementation plan

> Source of truth: `docs/sessions/session-07-post-mvp.md`, **item E** ("Call-script vs email vs
> WhatsApp opener templates, selectable per run. Still grounded in detected signals — no generic
> templates."), and `idea.md` §12.5 (open decision: "Opener tone/format defaults — call script vs
> email vs WhatsApp"). Session 07 is a **menu** ("pick one per session, in roughly this order"); this
> plan implements **only item E** and explicitly does **not** pull forward B (state tiling),
> C (owner enrichment), or D (SQLite).
>
> **Core-principle check (CLAUDE.md):** Stage 4 is *the product* — the ICP-driven qualification +
> grounded-opener layer. This item lives squarely in that value layer, so the effort belongs in the
> **prompt and the grounding enforcement**, not in plumbing. The bar is unchanged: **every** opener,
> in **every** format, must reference a real `detected_signal` (non-negotiable #6). A format variant
> that drifts into a generic template is a **failure**, not a fallback.

## Goal & scope
Make the per-lead opener **format selectable per run** — `call`, `email`, or `whatsapp` — so the
operator gets a draft phrased for the channel they actually intend to use, while keeping the
**single** Stage-4 LLM call and the **grounding** guarantee intact. "Done" means: a run-level toggle
(default `call`, preserving today's behavior) selects one or more opener formats; the Stage-4 prompt
(`score.build_prompt`) asks the model for each requested variant in **one** structured-output call;
each produced variant is run through the existing `_ground_opener`/`_overlaps` enforcement so an
ungrounded variant is rewritten to cite a real `detected_signal` (never shipped generic); the
additive fields land on `ScoreResult`/`Lead` and flow to CSV/JSONL output; the budget ceiling and
"LLM only in Stage 4 on Stage-2 survivors" rules are untouched; and it is all covered by **offline**
fixture-LLM tests with `uv run pytest` green and `ruff`/`mypy` clean. **No** sending/dialing/blasting
capability is added — not even a stub. The output stays a list of text drafts for a human to send
manually.

## Prerequisites (confirmed against code, not just the roadmap)
- ✅ **Stage 4 is the only LLM stage and it is real.** `score.score` (`score.py:125`) is the single
  scoring entry; it calls `score_lead` (`score.py:109`) → `llm.score(model, build_prompt(lead, icp))`.
  The pipeline calls `s_score.score(enriched, icp, llm, cfg)` once (`pipeline.py:63`), only on
  Stage-3 enriched Stage-2 survivors. Items A–D do not touch this path.
- ✅ **Exactly one opener exists today.** `ScoreResult.suggested_opener` (`models.py:144`) and
  `Lead.suggested_opener` (`models.py:130`) are single `str` fields; `build_prompt` (`score.py:21`)
  asks for one `suggested_opener` (`score.py:84-85`).
- ✅ **Grounding is ENFORCED in code, not just requested.** `_ground_opener` (`score.py:89`) checks
  the opener against `result.detected_signals` via `_overlaps` (`score.py:102`, shared-word check on
  words > 3 chars) and, if no overlap, **rewrites** the opener to cite `detected_signals[0]`. This is
  the mechanism item E must apply to **each** variant.
- ✅ **Budget + cost guards live in `score.score`.** `cfg.max_score` caps how many candidates reach
  the LLM (`score.py:127`); `if llm.spent_usd >= cfg.budget_usd: break` (`score.py:130`) stops mid-run.
  `RunConfig` (`config.py:19`) owns `scoring_model`, `budget_usd`, `max_score`, `offline` — the
  natural home for a per-run opener-format toggle.
- ✅ **Offline test seam is the fixture LLM.** `FixtureLlmClient.score` (`clients.py:547`) reads
  canned `ScoreResult`s from `fixtures/llm_scores.json` keyed by `place_id` (the prompt carries
  `[[PLACE_ID:..]]`/`[[FIRST_SIGNAL:..]]` tags via `_extract_tag`, `clients.py:649`), with a
  **grounded** heuristic fallback (`clients.py:556-562`). `tests/conftest.py` wires
  `load_fixture_clients(FIXTURES)`; `tests/test_score.py` drives `score(...)` with `RunConfig(offline=True)`.
- ✅ **Output already serializes `ScoreResult` fields onto the row.** `score_lead` copies the result
  fields onto the `Lead` (`score.py:116-122`); `io_out.CSV_COLUMNS` (`io_out.py:11`) lists
  `suggested_opener`; `_row`/JSONL dump the model. New fields are additive here.
- ⚠️ **Live OpenAI structured-output shape is fixed but the wording is a design choice.**
  `LiveLlmClient.score` uses `beta.chat.completions.parse(response_format=ScoreResult)`
  (`clients.py:614`) — so any new field must be a **typed field on `ScoreResult`**, not a free-form
  blob. The exact field names/format-enum values are ours to choose (see Contracts); confirm against
  the `claude-api`/OpenAI structured-output docs that the chosen shape parses (don't guess — see Risks).

## Design decisions required before coding

### D1 — Where does the toggle live? → `RunConfig` (not `NicheSpec`/`ICPSpec`)
"Selectable per run" is the literal requirement. The model and budget — the other per-run scoring
dials — already live on `RunConfig` (`config.py:19`), and the CLI already builds `RunConfig` per
invocation (`cli.py:54`). Channel choice is an **operator/outreach** decision, not a property of the
product (ICP) or the vertical/geo (niche): the same clinic ICP might be worked by phone today and
WhatsApp tomorrow. Therefore: **add `opener_formats` to `RunConfig`** and expose it as a CLI option
(`--opener-format`, repeatable / comma-list). Config-as-data still holds — it's a run parameter, and
it also reads from env (`RunConfig.from_env`) like `scoring_model`/`budget_usd`.
*(Rejected: `NicheSpec.sources`-style niche toggle — wrong altitude; channel isn't a niche trait.)*

### D2 — One LLM call returning multiple fields, or N calls? → **ONE call, multiple fields**
**Cost discipline (#1) decides this.** N calls = N× the per-lead token spend against the same
`budget_usd` ceiling — directly hostile to the cost mandate. Instead, the **single** existing
Stage-4 call returns the requested variant(s) as **separate typed fields** on `ScoreResult`. The
prompt asks for only the requested formats, so a `call`-only run produces one opener exactly as
today; an `all`-formats run produces three, still in one call. Marginal cost is a modest output-token
increase on the **same** call (a few short strings), not a new call — and the budget guard in
`score.score` is unchanged. **This plan assumes one call.**

### D3 — Default format → `call` (zero behavior change)
Today's single `suggested_opener` reads as a call/spoken opener. Default `opener_formats=["call"]`
and **keep `suggested_opener` populated** (mirroring the chosen call variant) so existing
output/tests/CSV stay byte-compatible until an operator opts into more. New per-format fields are
populated only for requested formats.

### D4 — Multiple formats at once? → **Yes, allowed** (list, deduped, order-stable)
"Selectable per run" reads naturally as "pick one," but a list costs little (D2) and is convenient
(draft call + WhatsApp from one run). Model it as `list[OpenerFormat]`; validate against the enum;
dedup; default `["call"]`. `--opener-format` is repeatable and also accepts a comma-list.

## Files to create / modify
| Path | Change |
|---|---|
| `src/leadscout/models.py` | **Add** `OpenerFormat = Literal["call", "email", "whatsapp"]`. **Add** to `ScoreResult` (additive, defaulted): `opener_call: str = ""`, `opener_email: str = ""`, `opener_whatsapp: str = ""`. **Add** the same three optional fields to `Lead` (Stage-4 block, ~`models.py:125`). Keep `suggested_opener` on both as-is (back-compat / the "primary" opener). |
| `src/leadscout/config.py` | **Add** `opener_formats: list[OpenerFormat] = ["call"]` to `RunConfig` (`config.py:19`); read `LEADSCOUT_OPENER_FORMATS` (comma-list) in `RunConfig.from_env` (`config.py:33`). Default keeps runs identical. |
| `src/leadscout/stages/score.py` | **Modify** `build_prompt` to take the requested formats and ask for **only** those variants (one structured field each) under the existing GROUNDING RULES. **Generalize** `_ground_opener` to ground **every** requested variant field (loop, reuse `_overlaps`). **Thread** `cfg.opener_formats` from `score`→`score_lead`→`build_prompt`/`_ground_opener`. Set `suggested_opener` from the primary (first requested) format for back-compat. |
| `src/leadscout/cli.py` | **Add** `--opener-format` option (repeatable, comma-split, default `["call"]`); parse/validate → pass into `RunConfig.from_env(..., opener_formats=...)` (`cli.py:54`). No other CLI change. |
| `src/leadscout/io_out.py` | **Add** `opener_call`/`opener_email`/`opener_whatsapp` to `CSV_COLUMNS` (`io_out.py:11`) after `suggested_opener`; `_row`/JSONL already dump model fields, so JSONL is automatic. |
| `fixtures/llm_scores.json` | **Edit (data)** — add `opener_call`/`opener_email`/`opener_whatsapp` to `p_bright`/`p_cityhosp`, each grounded in that entry's `detected_signals`, **plus one entry whose `opener_email` is deliberately generic/ungrounded** to exercise the rewrite path. (See Tests.) |
| `tests/test_score.py` | **Extend** — variants produced per requested format, each grounded; format toggle (call-only == today; multi-format populates the right fields); ungrounded variant gets rewritten to cite a real signal; budget/max_score still honored. All offline. |
| `examples/dental.yaml` *(optional)* | No change required (toggle is per-run, not niche). Leave as-is. |
| `docs/sessions/session-07-post-mvp.md`, `docs/sessions/README.md` | Mark item E ✅ with a one-line outcome (07 stays ⬜ overall until the menu is exhausted; record E as ✅ within the file). |

## Implementation steps (ordered, each independently verifiable)

1. **Add the enum + additive `ScoreResult`/`Lead` fields (`models.py`).** Define
   `OpenerFormat = Literal["call", "email", "whatsapp"]` near `Source` (`models.py:14`). Add to
   `ScoreResult` (`models.py:137`): `opener_call: str = ""`, `opener_email: str = ""`,
   `opener_whatsapp: str = ""` (all defaulted ⇒ existing canned fixtures still validate). Add the
   same three optional fields to `Lead`'s Stage-4 block (~`models.py:125`). **Leave
   `suggested_opener` untouched** on both. *Verify:* `uv run mypy` clean; existing
   `ScoreResult.model_validate(canned)` in `FixtureLlmClient` still parses old fixtures (defaults fill).

2. **Add the per-run toggle to `RunConfig` (`config.py`).** Add
   `opener_formats: list[OpenerFormat] = Field(default_factory=lambda: ["call"])`. In
   `RunConfig.from_env` (`config.py:33`), if `LEADSCOUT_OPENER_FORMATS` is set, split on commas,
   strip, lower-case, and pass through; pydantic validates each against the `OpenerFormat` literal
   (a bad value raises at load). Dedup while preserving order. *Verify:* `RunConfig()` default is
   `["call"]`; `RunConfig(opener_formats=["call","email"])` round-trips; a bogus value raises.

3. **Generalize `build_prompt` to request only the chosen formats (`score.py:21`).** Change the
   signature to `build_prompt(lead, icp, formats: list[OpenerFormat])`. Keep the entire existing body
   (FIT DIRECTION, PAIN SIGNALS, DISQUALIFIERS, GROUNDING RULES) — those are the product. Replace the
   final `Return JSON: ... suggested_opener.` line (`score.py:84-85`) with an instruction that names
   **exactly** the requested fields and, for each, restates the grounding+channel rule, e.g.:
   - `opener_call`: "1–2 spoken lines for a phone call";
   - `opener_email`: "2–3 sentence email body, no subject line";
   - `opener_whatsapp`: "one short, informal WhatsApp message".
   Each instruction repeats: **MUST reference one specific entry from `detected_signals` in plain
   words, framed as an opportunity** (reuse the existing grounding language at `score.py:80-82`).
   Only emit the lines for `formats` requested — so a `call`-only run's prompt is materially the same
   as today. Keep the `[[PLACE_ID:..]]`/`[[FIRST_SIGNAL:..]]` tags exactly (the fixture LLM depends
   on them, `clients.py:549-555`). *Verify:* a unit assertion that `build_prompt(lead, icp, ["email"])`
   contains `opener_email` and **not** `opener_call`/`opener_whatsapp`.

4. **Generalize grounding to every variant (`_ground_opener`, `score.py:89`).** Replace the
   single-field check with a loop over the requested format fields: for each non-empty variant, if no
   `_overlaps(variant, sig)` for any `sig in result.detected_signals`, rewrite that field to
   `f"Noticed {detected_signals[0]} — wanted to reach out about that."` (same rewrite as today,
   `score.py:97-99`). Keep the early return when `detected_signals` is empty (`score.py:91`). **Reuse
   `_overlaps` unchanged** (`score.py:102`). The function now takes the requested `formats` so it only
   inspects/grounds fields that were asked for. *Verify:* a fixture entry whose `opener_email` shares
   no word with its `detected_signals` comes back rewritten to cite a real signal; a grounded one is
   left as-is.

5. **Thread `opener_formats` through the stage (`score.py`).** `score_lead` (`score.py:109`) gains a
   `formats` param: it calls `build_prompt(lead, icp, formats)`, applies the disqualifier cap
   (unchanged, `score.py:111-113`), then `_ground_opener(result, formats)`, then sets the **primary**
   opener: `suggested_opener = <first requested format's field>` (back-compat — for default `call`,
   `suggested_opener == opener_call`). Copy all variant fields onto the `Lead` in the existing
   `model_copy` (`score.py:116-122`). `score` (`score.py:125`) passes `cfg.opener_formats` into
   `score_lead`. **Budget/max_score logic is byte-identical** — still one `llm.score` call per lead.
   *Verify:* default-config run output equals today's (`suggested_opener` populated, grounded).

6. **Wire the CLI (`cli.py:40`).** Add
   `opener_format: list[str] = typer.Option(["call"], "--opener-format", help="Opener channel(s): call|email|whatsapp (repeatable or comma-list).")`.
   Normalize: flatten comma-lists, strip/lower, dedup. Pass into
   `RunConfig.from_env(..., opener_formats=parsed)` (`cli.py:54`). Pydantic validates the values. No
   change to client wiring, pipeline, or sources. *Verify:* `--offline` smoke run with
   `--opener-format email --opener-format whatsapp` populates both fields on the top lead.

7. **Output columns (`io_out.py:11`).** Insert `opener_call`, `opener_email`, `opener_whatsapp` into
   `CSV_COLUMNS` right after `suggested_opener`. `_row` (`io_out.py:19`) and the JSONL dump already
   serialize all `Lead` fields, so JSONL needs nothing. *Verify:* the offline run's `leads.csv` has
   the new columns; populated only for requested formats.

8. **Author fixture data (`fixtures/llm_scores.json`).** For `p_bright` and `p_cityhosp`, add
   `opener_call`/`opener_email`/`opener_whatsapp`, each grounded in that entry's existing
   `detected_signals` (e.g. for `p_bright`, all three reference the phone-booking-friction / no-online-
   booking signals). Add **one new entry** (e.g. `p_ungrounded`) with real `detected_signals` but an
   `opener_email` that is deliberately generic ("Hi, hope you're well — wanted to introduce our
   product.") so step-4 grounding has something to rewrite. Keep `suggested_opener` present on all
   (back-compat). *Verify:* `FixtureLlmClient.score` returns these canned variants for the tagged
   place_id; the heuristic fallback (`clients.py:556-562`) is unaffected.

9. **Tests (offline — see next section).** Extend `tests/test_score.py`. Confirm every requested
   variant is produced **and** grounded, the toggle works (call-only == today), the ungrounded variant
   is rewritten, and budget/max_score still hold. All via the fixture LLM, **no network**.

10. **Docs.** Mark item E ✅ in `docs/sessions/session-07-post-mvp.md` with a one-line outcome and note
    it in the README row. Write/update a handoff if used.

## Contracts & types
- **`OpenerFormat`** — new `Literal["call", "email", "whatsapp"]` in `models.py` (sibling of `Source`).
- **`ScoreResult`** — **add** `opener_call: str = ""`, `opener_email: str = ""`,
  `opener_whatsapp: str = ""` (all defaulted ⇒ backward-compatible; old canned fixtures validate).
  `suggested_opener` **unchanged** — remains the "primary" opener (mirrors the first requested format).
- **`Lead`** — **add** the same three optional Stage-4 fields (`opener_call`/`opener_email`/
  `opener_whatsapp`, default `""`). `suggested_opener` unchanged. Stage 1–3 fields untouched.
- **`RunConfig`** — **add** `opener_formats: list[OpenerFormat] = ["call"]` (the one intentional run
  toggle; backward-compatible default). `from_env` reads `LEADSCOUT_OPENER_FORMATS`.
- **`score.build_prompt`** — signature gains `formats: list[OpenerFormat]`. **`_ground_opener`** gains
  `formats` and now grounds each requested variant. **`_overlaps` unchanged.** `score`/`score_lead`
  thread `cfg.opener_formats`. The `llm.score(model, prompt) -> ScoreResult` interface
  (`clients.py:526`) is **unchanged** — still one call per lead.
- **No change** to `GeographyInput`, `NicheSpec`, `ICPSpec`, `DropRecord`, or the discover/filter/
  enrich stage contracts. **No new LLM call** anywhere.

## Tests (offline; pytest stays fully green, zero network)
All drive `FixtureLlmClient` via `fixture_clients`/`RunConfig(offline=True)` (the `tests/test_score.py`
pattern). **No live calls.**
- **Keep green:** every existing `tests/test_score.py` test — `test_opener_references_a_detected_signal`,
  `test_disqualifier_caps_fit_score`, `test_budget_ceiling_stops_scoring`, `test_max_score_caps_calls`,
  `test_results_ranked_desc` — pass unchanged (default `opener_formats=["call"]` keeps the path
  identical; `suggested_opener` still populated and grounded).
- **Add:**
  1. **`build_prompt` requests only chosen formats:** `build_prompt(lead, icp, ["email"])` contains
     `opener_email` and not `opener_call`/`opener_whatsapp`; `["call","whatsapp"]` contains both and
     not `opener_email`. (Pure function, no LLM.)
  2. **Each requested variant is produced and grounded:** run `score([_lead("p_bright")], icp, llm,
     RunConfig(offline=True, opener_formats=["call","email","whatsapp"]))`; assert all three
     `opener_*` are non-empty and each shares a >3-char word with some `detected_signals` entry
     (reuse the `_overlaps`-style assertion already in `test_opener_references_a_detected_signal`).
  3. **Ungrounded variant is rewritten (non-negotiable #6):** score the `p_ungrounded` fixture with
     `opener_formats=["email"]`; assert the returned `opener_email` now references a real
     `detected_signal` (i.e. is **not** the canned generic string and overlaps a signal).
  4. **Toggle / back-compat:** default `RunConfig(offline=True)` produces `suggested_opener` ==
     `opener_call`, both grounded, and leaves `opener_email`/`opener_whatsapp` empty.
  5. **Primary mirror:** `opener_formats=["whatsapp"]` ⇒ `suggested_opener == opener_whatsapp`.
  6. **Budget still honored:** `RunConfig(offline=True, budget_usd=0.0, opener_formats=["call","email","whatsapp"])`
     ⇒ `out == []`, `llm.call_count == 0` (one call per lead regardless of variant count; multi-format
     does **not** multiply calls).
  7. **`RunConfig.from_env`** parses `LEADSCOUT_OPENER_FORMATS="email, whatsapp"` →
     `["email","whatsapp"]` (strip/lower/dedup); a bogus value raises a validation error.
- **No live LLM in pytest.** `LiveLlmClient` is never instantiated; the fixture LLM is the only scorer.

## Final checks (the gate — all must pass)
```
uv run pytest -q          # existing + new opener-variant tests, fully offline
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline --opener-format call --opener-format email --opener-format whatsapp
```
The offline smoke run must succeed and the top-lead line plus `out/leads.csv` must now show grounded
`opener_call`/`opener_email`/`opener_whatsapp`. A **live** run (real OpenAI) is operator-driven and
**never** in CI/pytest — confirm the structured-output field shape parses before relying on it (Risks).

## Definition of done (adapted from session-07 item E)
Opener format is **selectable per run** via `RunConfig.opener_formats` (`--opener-format`, default
`call` so existing runs are unchanged); the single Stage-4 LLM call returns `call`/`email`/`whatsapp`
variants as typed `ScoreResult` fields for **only** the requested formats; **every** produced variant
is run through `_ground_opener`/`_overlaps` and references a real `detected_signal` — an ungrounded
variant is rewritten, never shipped generic (no generic templates); `suggested_opener` stays
populated from the primary format for back-compat; the variants flow to `Lead`, CSV, and JSONL;
budget ceiling and "LLM only in Stage 4 on Stage-2 survivors" are untouched (still one call per lead);
offline fixture-LLM tests cover production + per-variant grounding + toggle + budget and
`uv run pytest` is green; `ruff`/`mypy` clean; the offline smoke run passes. **No sending/dialing/
blasting capability added — not even a stub.** Roadmap item E marked ✅.

**Commit message:**
```
Session 07E: per-run opener format variants (call/email/whatsapp) in one Stage-4 call, each grounded in a detected signal (offline-tested)
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **#6 Openers MUST be grounded (the headline here).** The grounding mechanism is *code*
  (`_ground_opener`/`_overlaps`), not a prompt hope. This step extends that enforcement to run over
  **each** requested variant: any variant that fails `_overlaps` against `detected_signals` is
  rewritten to cite `detected_signals[0]`. An ungrounded `email`/`whatsapp` opener is a **failure**
  the code fixes — no generic per-channel templates. The prompt repeats the grounding instruction per
  field; the code is the backstop.
- **#4 Legal — output is for a human to contact manually; NO auto-dialing / AI-voice / email or
  WhatsApp blasting, not even a stub.** This item produces **text drafts** the operator copies and
  sends by hand. The plan adds **zero** sending, dialing, messaging-API, or queueing code — no
  Twilio/WhatsApp Business/SMTP client, no `send()` stub, no scheduler. A WhatsApp/email *opener
  string* in a CSV is just text; it never leaves the file. Out-of-scope automation stays entirely out
  of the codebase (idea.md §10/§11).
- **#1 LLM only in Stage 4, on Stage-2 survivors, under the budget ceiling.** All work is inside
  Stage 4. Variants come from **one** call per lead (D2), so cost rises only by a few output tokens on
  the existing call — `score.score`'s `budget_usd`/`max_score` guards (`score.py:127-133`) are
  unchanged and still gate spend. Stages 1–3 stay LLM-free.
- **Config is data.** The toggle is a run parameter on `RunConfig` (CLI flag + env var), not a
  hardcoded format. Adding a channel later = extending `OpenerFormat` + one prompt clause, not a
  pipeline rewrite.
- **Secrets / definition of done.** No `.env`/`.env.example` touched; pre-commit secret check intact.
  Nothing is done until it runs end-to-end on the fixture and is tested (offline, cache-only).

## Risks / unknowns (research before relying on live — never guess)
- **Structured-output field shape (verify, don't guess).** `LiveLlmClient.score` parses straight into
  `ScoreResult` via `beta.chat.completions.parse(response_format=ScoreResult)` (`clients.py:614`).
  Adding three defaulted string fields should "just work," but **confirm** against the OpenAI
  structured-output / `claude-api` reference that (a) optional/defaulted fields are allowed and (b)
  the model reliably returns the requested ones. Do **not** assume model behavior — flag for a live
  spot-check separate from CI. The offline tests prove our parsing/grounding regardless.
- **Per-variant grounding precision.** `_overlaps` is a loose shared-word heuristic (words > 3 chars).
  A short, channel-styled WhatsApp line is more likely to dodge it and get force-rewritten to the
  blunt `"Noticed {signal} — ..."`. That is the *correct* failure mode (grounded > stylish), but note
  it: if rewrites fire too often live, tighten the **prompt** (ask the model to quote a signal phrase),
  not the enforcement. Keep enforcement strict.
- **Output-token cost of multi-format.** Three variants ≈ three short strings of extra output on the
  same call — small, but real. It accrues via `LiveLlmClient` `response.usage` and counts against
  `budget_usd` (`clients.py:628`). The budget guard already handles it; just be aware multi-format runs
  spend marginally more per lead. (Single-call design keeps this minimal — N-call was rejected for this
  reason, D2.)
- **CSV width / readability.** Three more columns widen `leads.csv`. Acceptable for an internal tool;
  populated only for requested formats. If it bloats, a future refinement could gate columns by
  requested formats — not this step.
- **Model wording drift across channels.** The model may bleed a subject line into `opener_email` or
  over-format the WhatsApp line. Mitigation is prompt wording ("no subject line", "one short message");
  it is a quality knob, not a correctness gate, and the grounding backstop still applies.

## What NOT to do (don't pull work forward)
No state-level tiling (item B / `discover.resolve_tiles` TODO). No owner-name/LinkedIn enrichment
(C). No SQLite cross-run store (D). **Above all: no sending/dialing/messaging capability of any kind —
no auto-dialer, AI-voice, SMTP/email blast, WhatsApp Business API, queue, or scheduler — not even a
stub** (#4 / idea.md §10–11). No second LLM call per lead and no LLM outside Stage 4 (#1). No change
to the discover/filter/enrich contracts or to Stage-4 budget/disqualifier enforcement beyond the
additive opener fields. No touching `.env`/`.env.example` or the pre-commit secret check.
