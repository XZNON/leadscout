# Session 02 — Verify & green the skeleton

**Status:** ✅ done
**Goal:** prove the bootstrap actually runs. Install, get tests green, do one offline run, commit.
**Prereq:** Session 01 files exist.

## Steps
1. **Env + install** (uv is the package manager):
   ```
   uv venv
   uv pip install -e ".[dev]"
   ```
2. **Run the tests** — must be green and fully offline (no network):
   ```
   uv run pytest -q
   ```
   Expect 5 test files passing. If red, fix the code, not the test, unless the test asserts the
   wrong contract. Likely first-run snags: fixture paths, pydantic v2 validator syntax, pandas
   import. Fix and re-run until green.
3. **Lint + types:**
   ```
   uv run ruff check . && uv run mypy
   ```
4. **Real offline run** (the definition-of-done command from the bootstrap prompt):
   ```
   uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
   ```
   Confirm `out/leads.csv` exists, top row is **Bright Smile Dental** with a `fit_score`,
   `detected_signals`, and a `suggested_opener` that references one of those signals. Confirm
   `out/disqualified.jsonl` lists the 6 dropped businesses with reasons.
5. **Install the secret hook, then commit:**
   ```
   python scripts/install_hooks.py
   git add -A && git commit -m "Bootstrap LeadScout walking skeleton (offline)"
   ```
   The pre-commit hook must pass. **Confirm `.env` and any real key are NOT staged** before commit.

## Definition of done
Green `pytest`, clean `ruff`/`mypy`, an offline run that writes a correctly-ranked `leads.csv`,
and a first commit with no secrets. Update Session 01 → ✅ and this file → ✅.
