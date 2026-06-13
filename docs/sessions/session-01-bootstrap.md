# Session 01 — Bootstrap & walking skeleton

**Status:** 🔨 in progress (code written, not yet verified)
**Goal:** stand up the harness, scaffold, and an offline four-stage pipeline with tests — the
boilerplate every future session builds on.

## What got built
- **Harness:** `CLAUDE.md`, `.claude/rules.md`, `.claude/skills/{run-pipeline,add-icp,verify-stage}.md`,
  `scripts/check_secrets.py` + `scripts/install_hooks.py`.
- **Scaffold:** `pyproject.toml` (uv/ruff/mypy/pytest), `.gitignore`, `.env.example`.
- **Core:** `models.py` (typed contracts), `config.py`, `cache.py`, `clients.py` (Places/HTTP/LLM
  interfaces, each with a Fixture + Live impl; Live impls are `NotImplementedError` stubs).
- **Stages:** `discover` (tile + dedup), `filter` (deterministic + contactability bar),
  `enrich` (scrape + cache), `score` (LLM, budget-capped, grounded openers).
- **Glue:** `pipeline.py`, `io_out.py`, `cli.py` (`leadscout run ... --offline`).
- **Data:** `examples/{clinic,dental,bengaluru}.yaml`; `fixtures/` (8 fake businesses, 2 scraped
  pages, canned LLM scores).
- **Tests:** one per stage + `test_pipeline.py` e2e (all offline).

## Definition of done
Hand off to Session 02 once the files above exist. **Verification (install + green tests + a real
offline run) is deliberately Session 02** so this session stays "scaffold only."

## Open item carried forward
- A live Google Maps API key was placed in `.env.example` (a tracked file). Owner is handling it.
  **Do not commit `.env.example` with a real key.** (Owner also gitignored `.claude/`, `examples/`,
  `CLAUDE.md`, `idea.md` — respect that; don't re-add them.)
