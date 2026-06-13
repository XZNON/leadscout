# Step 02 — Verify & green the skeleton (implementation plan)

> Source of truth: `docs/sessions/session-02-verify.md`. This file is the worked-out *how* for
> that one step. **Do not pull work forward** from Sessions 03–07 (no live Places/HTTP/LLM code).

## Goal & scope
Prove the Session-01 bootstrap actually runs, offline, end to end. "Done" means: a clean dev
install under `uv`, `uv run pytest -q` green (all 5 test files), `ruff` and `mypy` clean, and one
real offline CLI run that writes a correctly-ranked `out/leads.csv` (top row **Bright Smile
Dental** with `fit_score` + `detected_signals` + a `suggested_opener` that cites one of those
signals) plus `out/disqualified.jsonl` listing the 6 dropped businesses with reasons. No feature
code is written; only fixes needed to make the existing scaffold pass. Finish by flipping
Session 01 → ✅ and Session 02 → ✅ and committing any fixes.

## Prerequisites (confirmed)
- ✅ All Session-01 files exist and are committed (`git log` shows `first commit`; tree clean).
  Verified present: `src/leadscout/{models,config,cache,clients,pipeline,io_out,cli}.py`,
  `stages/{discover,filter,enrich,score}.py`; `tests/{conftest,test_discover,test_filter,test_enrich,test_score,test_pipeline}.py`;
  `examples/{clinic,dental,bengaluru}.yaml`; `fixtures/{places.json,llm_scores.json,scrapes/{brightsmile,cityhospital}.example.html}`;
  `scripts/{check_secrets,install_hooks}.py`; `pyproject.toml`.
- ✅ `uv` available (0.8.2). ❌ No `.venv` yet. ❌ Tests never run. ❌ No `out/` yet.
- ⚠️ Drift vs. session file: a commit **already exists** (`first commit`). Session 02 step 5's
  "make the first commit" is therefore mostly satisfied — treat it as "commit the verification
  fixes + status flips," not a fresh bootstrap commit. Do not rewrite/amend `first commit`.

## Files to create / modify
- *(create on run)* `.venv/` — dev environment via `uv venv` (gitignored; do not commit).
- *(create on run)* `out/leads.csv`, `out/leads.jsonl`, `out/disqualified.jsonl` — run artifacts
  (confirm `out/` is gitignored or do not stage it).
- *(create on run)* `.git/hooks/pre-commit` — installed by `scripts/install_hooks.py`.
- `docs/sessions/session-01-bootstrap.md` — status box 🔨 → ✅.
- `docs/sessions/session-02-verify.md` — status ⬜ → ✅.
- `docs/sessions/README.md` — table rows 01 and 02 → ✅.
- **Only if a check is red:** the specific `src/leadscout/**` or `tests/**` file at fault — minimal
  fix, no scope creep. Fix the code, not the test, unless the test asserts the wrong contract.

## Implementation steps (ordered, each verifiable)
1. **Create env + install dev deps.**
   `uv venv` then `uv pip install -e ".[dev]"`. Verify: install exits 0; `selectolax`, `pandas`,
   `openai`, `typer`, `pydantic`, `pyyaml`, `python-dotenv`, plus dev `pytest/ruff/mypy/types-PyYAML`
   resolve. (`selectolax` ships wheels for Windows/py3.11 — flag if it tries to build from source.)
2. **Run the suite offline.** `uv run pytest -q`. Expect 5 test files passing with **no network**.
   Likely first-run snags to look for (from the session file): fixture path resolution
   (`tests/conftest.py` builds `FIXTURES`/`EXAMPLES` off `parents[1]` — confirm), pydantic v2
   validator syntax in `models.py`, and the `pandas` import path in `io_out.py`. Diagnose each
   failure; fix root cause in code.
3. **Lint + types.** `uv run ruff check .` then `uv run mypy`. Ruff config selects `E,F,I,UP,B`;
   mypy runs with the pydantic plugin over the `leadscout` package. Fix real findings; do not
   silence with blanket ignores.
4. **Real offline run** (the DoD command):
   `uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline`
   This wires `load_fixture_clients(FIXTURES_DIR)` (no keys, no network) through `run_pipeline`
   (discover → filter → enrich → score) and `write_outputs`. Inspect:
   - `out/leads.csv` exists; **top row = Bright Smile Dental** with non-null `fit_score`,
     non-empty `detected_signals`, and a `suggested_opener` that shares a real word with one of
     those signals (the `_ground_opener`/`_overlaps` guard in `stages/score.py` enforces this).
   - `out/disqualified.jsonl` lists **6** dropped businesses, each with a reason
     (8 fixture businesses − 2 survivors = 6; confirm against `fixtures/places.json`).
   - CLI summary line prints `discovered=… candidates=… scored=… llm_calls=… spent=$…`.
5. **Install secret hook + commit fixes.** `python scripts/install_hooks.py`, then stage only
   intended files and commit. **Before commit, confirm `.env` and any real key are NOT staged**
   (run `git status` and eyeball; the pre-commit hook from `scripts/check_secrets.py` must pass).
   Do not stage `.venv/`, `out/`, `.cache/`. Do not stage gitignored harness files
   (`.claude/`, `examples/`, `CLAUDE.md`, `idea.md`).
6. **Flip statuses.** Update the three docs files in "Files to modify" to ✅ and include them in
   the commit.

## Contracts & types (touched, not changed)
- Read-only reliance on existing pydantic contracts: `GeographyInput`, `NicheSpec`, `ICPSpec`,
  `Lead`, `ScoreResult`, `DropRecord`, `BBox`, and `RunConfig`. **Keep all stage contracts stable**
  — this step verifies them; it does not redesign them. Client `Protocol`s
  (`PlacesClient`/`HttpClient`/`LlmClient`) and `PipelineResult` stay as-is. Any change here beyond
  a typo/validator-syntax fix is out of scope and a signal to stop and reassess.

## Tests (keep green, offline-only)
No new tests are required for this step — the goal is to green the *existing* five. They must stay
fully offline (fixture clients only; no live API). Confirm each still asserts its intended contract:
- `test_discover.py` — tiling + **dedup on `place_id`** over overlapping tiles/keywords.
- `test_filter.py` — deterministic qualify + contactability bar; correct survivors vs. drops.
- `test_enrich.py` — scrape via `FixtureHttpClient` and **cache prevents re-fetch**
  (asserts on `fetch_count`).
- `test_score.py` — budget/`max_score` honored, disqualifier caps `fit_score`, opener references a
  detected signal.
- `test_pipeline.py` — e2e offline: Bright Smile Dental ranks top; 6 dropped with reasons.
If a test is red because the *code* is wrong, fix the code. Only touch a test if it asserts the
wrong contract (justify in the commit message).

## Final checks (the gate — all must pass)
```
uv run pytest -q
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
```
Plus: `out/leads.csv` top row is Bright Smile Dental (grounded opener) and `out/disqualified.jsonl`
has 6 reasoned drops.

## Definition of done
Green `pytest`, clean `ruff` + `mypy`, an offline run that writes a correctly-ranked `leads.csv`
and a 6-row `disqualified.jsonl`, secret hook installed, and a commit with **no secrets staged**.
Session 01 → ✅ and Session 02 → ✅ (file status boxes + README table).

**Commit message:** since `first commit` already exists, use a verification-scoped message:
```
Verify & green LeadScout skeleton (offline run + tests passing)
```
(Session file's suggested "Bootstrap LeadScout walking skeleton (offline)" was for the now-existing
first commit; don't reuse it.)

## Non-negotiables touched & how honored
- **Cost discipline / LLM only in Stage 4:** offline run uses `FixtureLlmClient`; no live LLM, and
  scoring runs only on Stage-2 survivors via `run_pipeline`. Verify `llm_calls` ≈ survivor count,
  not raw count.
- **Dedup on `place_id`:** asserted by `test_discover.py` — must stay green.
- **Secrets never committed:** install the pre-commit hook; confirm `.env`/keys unstaged; keep
  `scripts/check_secrets.py` intact. Do **not** touch `.env.example` (owner-managed, may hold a key)
  and do **not** re-add gitignored harness files.
- **Legal / scraping etiquette:** untouched this step (no live scraping/dialing). Offline only.

## Risks / unknowns (research before assuming)
- **`selectolax` install on Windows/py3.11** — confirm a prebuilt wheel installs; if it builds from
  source, note the toolchain need. Do not guess.
- **First-run test snags** the session file predicts: fixture path resolution, pydantic v2
  validator syntax, `pandas` import in `io_out.py`. Treat any failure as a real fix target.
- **`out/` and `.gitignore`** — verify `out/`, `.cache/`, `.venv/` are ignored before `git add -A`;
  if not, stage selectively rather than committing run artifacts.
- No API behavior is exercised this step, so no model-ID/pricing lookups are needed yet (those land
  in Sessions 03/05).
