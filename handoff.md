# Session Handoff
_Generated: 2026-06-19_

## Goal
Incrementally build out LeadScout — an internal CLI lead-generation tool — one session at a time, following the `docs/sessions/` roadmap. The current work completed **item E: Opener format variants (call/email/WhatsApp)** from the Session 07+ post-MVP backlog.

## Current State
The full pipeline is working end-to-end (offline smoke run passes, 84 tests green, ruff/mypy clean). All gates pass:
```
uv run pytest -q          # 84 passed
uv run ruff check .       # All checks passed
uv run mypy               # Success: no issues found in 14 source files
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml \
  --offline --opener-format call --opener-format email --opener-format whatsapp
# top: Bright Smile Dental  fit=88  opener="Noticed a couple of your Google reviews..."
# leads.csv has opener_call / opener_email / opener_whatsapp columns
```

Session 07+ backlog status:
- **A — JustDial/IndiaMART sources** ✅ done
- **B — State-level tiling** ✅ done
- **C — Owner-name enrichment** ✅ done
- **D — SQLite cross-run store** ✅ done
- **E — Opener format variants** ✅ done (this session)

All items in Session 07+ are now done. The roadmap has no further planned sessions.

## Files Being Edited
- `src/leadscout/models.py` — Added `OpenerFormat = Literal["call", "email", "whatsapp"]`. `ScoreResult` gains `opener_call`, `opener_email`, `opener_whatsapp` (all `str = ""`). `Lead` Stage-4 block gains the same three fields.
- `src/leadscout/config.py` — `RunConfig` gains `opener_formats: list[OpenerFormat]` (default `["call"]`); `from_env` reads `LEADSCOUT_OPENER_FORMATS` (comma-list).
- `src/leadscout/stages/score.py` — `build_prompt(lead, icp, formats)` now takes formats and builds only the requested opener instructions. `_ground_opener(result, formats)` loops over requested fields and rewrites ungrounded variants. `score_lead` threads `formats`, sets `suggested_opener` from primary format, copies only requested format fields onto `Lead`. `score` passes `cfg.opener_formats`.
- `src/leadscout/cli.py` — Added `--opener-format` option (repeatable/comma-list, default `["call"]`). Normalizes and deduplicates before passing to `RunConfig.from_env`.
- `src/leadscout/io_out.py` — Added `opener_call`, `opener_email`, `opener_whatsapp` to `CSV_COLUMNS` after `suggested_opener`.
- `fixtures/llm_scores.json` — Added `opener_call`/`opener_email`/`opener_whatsapp` to `p_bright` and `p_cityhosp` (all grounded). Added `p_ungrounded` fixture with a deliberately generic `opener_email` to exercise the rewrite path.
- `tests/test_score.py` — Added 8 new offline tests covering: prompt content per format, all variants grounded, ungrounded rewrite, back-compat, primary mirror, budget, env parsing, bad-value reject.
- `docs/sessions/session-07-post-mvp.md` — Item E marked ✅ with outcome note.
- `docs/sessions/README.md` — Row updated: E now ✅.

## What We Tried That Failed
- Initially `score_lead` copied ALL format fields from the fixture result onto `Lead`, even for non-requested formats (e.g., default `["call"]` run would populate `opener_email` from the fixture). Fixed by only copying fields for the requested formats in a loop over `formats`.
- `typer.Option(["call"], ...)` with `list[str]` annotation triggers ruff B008 because lists are mutable. Fixed by using `None` default and applying the `["call"]` fallback in the function body, with `# noqa: B008` for the remaining `list[str] | None` annotation.

## Next Step
The Session 07+ backlog is exhausted (A–E all ✅). The next step is to check `docs/sessions/` for any remaining planned sessions beyond 07, or start a new backlog item based on `idea.md` or operator feedback. Open `docs/sessions/README.md` first and pick the lowest-numbered not-started item.

## Additional Context
- **Workflow:** always open `docs/sessions/README.md` first, pick the lowest-numbered not-started item, do its steps, mark it done, commit. Don't pull work forward.
- **User commits themselves** — never run `git commit`; leave it to the user.
- **Secrets:** user self-manages `.env`; don't touch `.env.example` or gitignored harness files.
- **Test discipline:** all tests must be fully offline (no live API calls). `FixtureLlmClient` maps `place_id` tags in prompts to canned `ScoreResult` from `fixtures/llm_scores.json`.
- **Grounding is CODE, not a prompt hope.** `_ground_opener` enforces it by rewriting any non-overlapping opener to cite `detected_signals[0]`. Prompt is just the first request; the code is the backstop.
- **Single LLM call per lead regardless of format count.** `build_prompt` includes only the requested format instructions; the model returns them in one call. Multi-format does not multiply calls or cost.
- **`suggested_opener` back-compat:** always mirrors the first requested format's field. Default `["call"]` run is byte-identical to before.
- **`lead_state` vs `state`:** `Lead.state` is address state. `Lead.lead_state` is cross-run store state. Don't confuse.
- **Run command:** `uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml`
- **Package manager:** `uv`. Everything runs via `uv run`.
- **Don't stage** `out/`, `.cache/`, `*.db` files.
