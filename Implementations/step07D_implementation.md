# Step 07D — SQLite for cross-run dedup & state — implementation plan

> Source of truth: `docs/sessions/session-07-post-mvp.md`, **item D** (idea.md §12.4). This is the
> worked-out *how* for that one backlog item. Session 07 is a **menu** ("pick one per session, in
> roughly this order"); this plan implements **only item D** and explicitly does **not** pull forward
> B (state tiling), C (owner enrichment), or E (opener variants).
>
> **Core-principle check (CLAUDE.md):** cross-run persistence is *commodity plumbing*. This step must
> be **boring, correct, and cheap** — a local SQLite store that *reinforces* dedup-on-`place_id` and
> remembers lead state across runs, without touching the Stage-4 scoring/opener layer. **Zero LLM**
> (this is below all four stages). **CSV/JSONL export stays.** Do not gold-plate.

## Goal & scope
Move cross-run persistence from "nothing" (today every run is independent; only the flat-file
`JsonCache` survives, and it only caches raw HTTP/place-detail bodies — not leads) to a **lightweight
local SQLite DB** that persists two things across runs/sessions: (1) the set of businesses we have
already seen, keyed on `place_id` (so dedup survives across runs, not just within one `discover`
call), and (2) a small **lead state** per `place_id` (`new` / `seen` / `contacted`) that the operator
can advance by hand and that survives subsequent runs. "Done" means: a `LeadStore` backed by stdlib
`sqlite3` exists behind a tiny interface; the pipeline records every discovered lead's `place_id`
into it and marks leads it has seen before as `seen` (returning rows are flagged but **not dropped**
from the run — see step 5); lead `state` round-trips across two runs against the **same DB file**;
the existing `JsonCache` is **kept** for raw HTTP/place-detail bodies; **CSV/JSONL export via
`io_out.write_outputs` is unchanged**; the whole thing is covered by **offline** tests using a
**temp DB path** (no global state, no network) with `uv run pytest` green and `ruff`/`mypy` clean. No
new LLM calls, no Stage-contract churn.

## Prerequisites (confirmed against code, not just the roadmap)
- ✅ **Item A done; MVP solid.** `docs/sessions/README.md:22` marks 07A ✅; `discover.discover`
  (`discover.py:97`) already does within-run dedup via `by_id: dict[str, Lead]` (`discover.py:113`)
  plus cross-source phone dedup via `_norm_phone` (`discover.py:60`, `seen_phones` at `:114`). **This
  is within-RUN only** — nothing persists the lead set between runs. Item D adds the cross-RUN layer.
- ✅ **Flat-file cache is the current persistence.** `JsonCache` (`cache.py:15`) has `get`/`set`/`has`
  keyed by `namespace + key` → one JSON file per key (`cache.py:19` `_path`, with Windows-safe key
  sanitization at `:21`). It caches **raw bodies** (place details, scrapes), *not* `Lead` rows. The
  pipeline builds it once: `cache = JsonCache(cfg.cache_dir)` (`pipeline.py:44`); `cfg.cache_dir`
  defaults to `Path(".cache")` (`config.py:27`).
- ✅ **CSV/JSONL output is a stable seam to keep.** `io_out.write_outputs(leads, dropped, out_dir)`
  (`io_out.py:26`) writes `leads.csv`, `leads.jsonl`, `disqualified.jsonl`. `CSV_COLUMNS`
  (`io_out.py:11`) is the call-ready column order. **This file's behavior is preserved by item D.**
- ✅ **`Lead` shape is stable and has `place_id: str` required** (`models.py:103`). There is **no
  lead-state field today** — `Lead` ends at the Stage-4 fields (`models.py:125-130`) plus the
  `contactable` property (`:133`). Item D must *define* what "state" means; the recommendation below
  keeps it **out of the per-run Stage contracts** and in the store, with only an optional,
  default-`None` display field added to `Lead` (see Contracts).
- ✅ **Pipeline is a pure composition** (`pipeline.py:34` `run_pipeline`) returning `PipelineResult`
  (`pipeline.py:23`). It already takes `cfg: RunConfig` and builds the cache; a store slots in next to
  the cache with **no Stage signature change**.
- ✅ **CLI wires cache from `cfg.cache_dir`** in the live branch (`cli.py:69`) and uses
  `load_fixture_clients` offline (`cli.py:66`). A DB path derived from config slots in the same way.
- ✅ **Tests are offline + temp-path.** `tests/conftest.py:37` `cache` fixture uses `tmp_path`;
  `tests/test_pipeline.py:14` builds `RunConfig(... cache_dir=tmp_path/"cache", out_dir=tmp_path/"out")`.
  The new DB tests follow this exact temp-path pattern.
- ✅ **stdlib `sqlite3` is available** (CPython 3.11+, no new dependency). No need for SQLAlchemy or
  any ORM for a single small table — see Risks for the justification.

## Design decision required before coding — replace `JsonCache`, or sit alongside it?
**Decision (recommended, lower-risk): SQLite sits ALONGSIDE `JsonCache`. Do NOT replace it.**

- `JsonCache` owns **raw HTTP/place-detail/scrape bodies** keyed by namespace+`place_id`. That data is
  large, opaque, append-only blob-ish, and already cached correctly to make re-runs cheap
  (`cache.py`, `.claude/rules.md` "Cache every place-detail fetch … by `place_id`"). Migrating those
  blobs into SQLite is pure churn with no payoff and real risk (it's working).
- **SQLite owns a new `leads` table:** the durable, queryable, *structured* concern — the set of seen
  `place_id`s (cross-run dedup reinforcement) and the per-`place_id` lead **state**. That is exactly
  what flat files are bad at (no atomic upsert, no "have I seen this before across runs", no state
  column) and SQLite is good at.

So: **two stores, two responsibilities.** Cache = bytes we fetched. Store = leads we know about + their
state. Neither replaces dedup-on-`place_id`; the store *reinforces* it across runs (CLAUDE.md #2).
This is the smallest, most reversible change and keeps the proven cache path untouched.

**Lead-state representation (decision):** state is a small string enum `LeadState =
Literal["new", "seen", "contacted"]`, stored in the DB, **not** a required `Lead` field.
- `new` — first time this `place_id` has ever been recorded (this run discovered it).
- `seen` — recorded in a previous run; surfaced again this run (operator hasn't acted).
- `contacted` — operator manually advanced it (out-of-band, e.g. a tiny `leadscout mark` command —
  optional stretch, see step 7; the store API supports it regardless).
The pipeline only ever sets `new`/`seen` automatically; it **never** downgrades `contacted` → `seen`
(state is sticky once advanced). This keeps the LLM/openers untouched and the per-run Stage contracts
stable.

## Files to create / modify
| Path | Change |
|---|---|
| `src/leadscout/store.py` | **Create.** New `LeadStore` class over stdlib `sqlite3`: `__init__(db_path)` opens/creates the DB and runs `CREATE TABLE IF NOT EXISTS`; `upsert_seen(leads) -> dict[str, LeadState]` records/looks-up each `place_id`, returns its state, and bumps `new`→`seen` on re-encounter (never demoting `contacted`); `get_state(place_id)`, `set_state(place_id, state)`, `close()`. A `LeadState` literal usage + a small `_SCHEMA_VERSION` and `PRAGMA user_version` migration hook live here too. **Zero LLM, no network.** |
| `src/leadscout/pipeline.py` | **Modify.** After Stage 1 `discover`, build a `LeadStore` from a new `cfg.db_path` and call `store.upsert_seen(raw)`; attach the returned state to each lead via the new optional `Lead.state` field (display-only) and add `new_count`/`seen_count` to `PipelineResult`. **No Stage signature change**; Stages 2–4 untouched. Keep `JsonCache` exactly as-is. |
| `src/leadscout/config.py` | **Modify.** Add `db_path: Path = Path(".cache/leadscout.db")` to `RunConfig` (config-as-data; lives under the existing cache dir by default). No env-var needed; optional `--db` CLI override threads through `from_env`. |
| `src/leadscout/models.py` | **Modify (minimal).** Add `LeadState = Literal["new", "seen", "contacted"]` and one optional field `state: LeadState | None = None` to `Lead` (default `None` ⇒ existing rows/serialization unchanged; not required, contract additive). |
| `src/leadscout/io_out.py` | **Modify (1 line).** Append `"state"` to `CSV_COLUMNS` (`io_out.py:11`) so the call-ready CSV shows lead state. JSONL already dumps the full model, so it carries `state` automatically. **Export behavior otherwise unchanged.** |
| `src/leadscout/cli.py` | **Modify.** Pass `cfg.db_path` through (offline + live branches both use the same on-disk SQLite — it's local, no keys). Optionally add a tiny `mark` command (`leadscout mark <place_id> contacted`) that opens the store and calls `set_state` — **stretch, see step 7**. |
| `tests/test_store.py` | **Create** — offline unit tests for `LeadStore` against a **temp DB path** (`tmp_path`): table creation, `new`→`seen` across two `upsert_seen` calls on the same DB, `contacted` stickiness, `get/set_state`. No network. |
| `tests/test_pipeline.py` | **Extend** — assert the pipeline records leads, that a **second run on the same `db_path`** reports them as `seen`, that CSV/JSONL still get written, and that `state` appears in the CSV header. |
| `docs/sessions/session-07-post-mvp.md`, `docs/sessions/README.md` | Mark item D done with a one-line outcome (07 stays 🔨 overall until the menu is exhausted — record D as ✅ within the file). |

## Implementation steps (ordered, each independently verifiable)
1. **Define `LeadState` + the optional `Lead.state` field (`models.py`).** Add
   `LeadState = Literal["new", "seen", "contacted"]` next to `Source` (`models.py:14`), and the
   optional `Lead.state: LeadState | None = None` field. *Verify:* `mypy` clean; existing tests still
   pass (field defaults to `None`, no serialization change).
2. **Implement `LeadStore` (`store.py`).** stdlib `sqlite3` only. On `__init__(db_path: str | Path)`:
   `Path(db_path).parent.mkdir(parents=True, exist_ok=True)` (Windows-safe like `JsonCache.set`,
   `cache.py:33`), `sqlite3.connect(str(db_path))`, set `PRAGMA journal_mode=WAL` and
   `PRAGMA busy_timeout=5000` (concurrency safety — see Risks), then create the schema:
   ```sql
   CREATE TABLE IF NOT EXISTS leads (
     place_id   TEXT PRIMARY KEY,        -- dedup key, mandatory (CLAUDE.md #2)
     source     TEXT,
     name       TEXT,
     state      TEXT NOT NULL DEFAULT 'new',
     first_seen TEXT NOT NULL,           -- ISO8601 UTC
     last_seen  TEXT NOT NULL
   );
   ```
   Set `PRAGMA user_version` to `_SCHEMA_VERSION = 1`. *Verify:* opening a fresh temp path creates the
   file and table; opening it again is a no-op (`IF NOT EXISTS`).
3. **`upsert_seen(leads: list[Lead]) -> dict[str, LeadState]`.** For each lead, in one transaction:
   `INSERT ... ON CONFLICT(place_id) DO UPDATE SET last_seen=?, state=CASE WHEN state='new' THEN 'seen'
   ELSE state END`. Return `{place_id: resulting_state}`. The `CASE` is the crux: a brand-new row keeps
   `new` this run; a row that already existed flips `new`→`seen` but **leaves `contacted` sticky**
   (idea.md §12.4: state persists across runs). The `place_id` PRIMARY KEY is the **cross-run dedup
   reinforcement** — it can never hold two rows for one business. *Verify with step 9 tests.*
4. **`get_state` / `set_state` / `close` + context-manager support.** `set_state(place_id, state)` is a
   plain `UPDATE` (the operator-driven `contacted` path); `get_state` returns `LeadState | None`.
   `close()` closes the connection (tests call it or use `with LeadStore(db) as store:`). *Verify:*
   set→get round-trips; `get_state("unknown") is None`.
5. **Wire the store into `run_pipeline` (`pipeline.py`).** After `raw = s_discover.discover(...)`
   (`pipeline.py:48`), open `store = LeadStore(cfg.db_path)`, call `states = store.upsert_seen(raw)`,
   and set `lead.state = states[lead.place_id]` on each raw lead **before Stage 2**. **Do not drop
   `seen` leads** — surfacing a previously-seen business again is useful (its reviews/site may have
   changed; the operator decides). Add `new_count` / `seen_count` to `PipelineResult` (`pipeline.py:23`)
   for the run summary. Keep `cache = JsonCache(cfg.cache_dir)` (`pipeline.py:44`) exactly as-is — the
   cache and store coexist. `close()` the store in a `finally`. *Verify:* the existing
   `test_walking_skeleton` still passes (counts unchanged; `state` is additive).
6. **Add `db_path` to `RunConfig` + thread through CLI (`config.py`, `cli.py`).** Default
   `db_path: Path = Path(".cache/leadscout.db")`. In `cli.py`, both branches use `cfg.db_path` (it's a
   local file — no key, works offline and live). Add an optional `--db` `typer.Option` that maps into
   `RunConfig.from_env(db_path=...)`. *Verify:* `leadscout run ... --offline` writes a DB under the
   cache dir; a second run reuses it.
7. **(Stretch, optional) `leadscout mark <place_id> <state>` command (`cli.py`).** Opens
   `LeadStore(cfg.db_path)`, calls `set_state`, echoes the new state. This is the only CLI way to set
   `contacted`; keep it tiny and **non-LLM**. If time-boxed out, the store API still supports it and a
   later session can add it — note it, don't gold-plate.
8. **Add `"state"` to `CSV_COLUMNS` (`io_out.py:11`).** One-line append so the call-ready CSV shows
   `new`/`seen`/`contacted`. `_row` (`io_out.py:19`) already does `d.get(col, "")`, so a `None` state
   renders as empty — safe. JSONL is unaffected (full `model_dump`). *Verify:* CSV header contains
   `state`.
9. **Tests (offline, temp DB).** See the Tests section. All use `tmp_path` for the DB; **no network**.
10. **Docs.** Mark item D ✅ in `docs/sessions/session-07-post-mvp.md` with a one-line outcome; note in
    the README row.

## Contracts & types
- **`Lead`** — additive only: `state: LeadState | None = None` (display field, default `None`). The
  per-run Stage contracts (`discover`/`filter`/`enrich`/`score` signatures) are **unchanged**; the
  pipeline sets `state` between Stage 1 and Stage 2. JSONL serialization gains a `state` key; CSV gains
  a trailing `state` column. **No change** to `ScoreResult`, `DropRecord`, `NicheSpec`, `ICPSpec`, or
  Stage-4 scoring/opener logic.
- **`LeadState`** — new `Literal["new", "seen", "contacted"]` in `models.py`.
- **`LeadStore`** (new, `store.py`) — small concrete class (not a Protocol; there's one impl, and it's
  injected via `cfg.db_path` so tests use a temp path). Methods: `upsert_seen(list[Lead]) ->
  dict[str, LeadState]`, `get_state(str) -> LeadState | None`, `set_state(str, LeadState) -> None`,
  `close()`, context-manager support. The **`place_id` PRIMARY KEY** is the durable dedup key.
- **`RunConfig`** — add `db_path: Path = Path(".cache/leadscout.db")` (config-as-data, backward-compat
  default under the existing cache dir).
- **`PipelineResult`** — add `new_count: int = 0`, `seen_count: int = 0` (additive defaults).
- **Schema/migration** — `PRAGMA user_version` holds `_SCHEMA_VERSION` (start at `1`). The store reads
  `user_version` on open; if it's `0`/unset it creates v1 and stamps it. A `_migrate(from_version)`
  hook is stubbed for the future (no migrations needed yet — **don't build speculative ones**, just
  leave the seam). `CREATE TABLE IF NOT EXISTS` makes re-opening idempotent.

## Tests (offline; pytest stays fully green, zero network)
- **Keep green:** the existing suite (incl. `test_pipeline.py::test_walking_skeleton`). `state` is an
  additive field and the store records-but-doesn't-drop, so counts (`raw_count==8`,
  `candidate_count==2`, `scored_count==2`, `llm_calls==2`, `dropped==6`) are unchanged.
- **Add (`tests/test_store.py`)** — all with a **temp DB** `db = tmp_path / "leadscout.db"`:
  1. **Schema creation:** `LeadStore(db)` creates the file + `leads` table; `PRAGMA user_version == 1`.
  2. **`new` on first sight:** `upsert_seen([lead_a, lead_b])` returns `{a:"new", b:"new"}`.
  3. **Cross-run `seen`:** a **second** `LeadStore(db)` (new connection, same path) +
     `upsert_seen([lead_a])` returns `{a:"seen"}` — proves state persists across runs/sessions.
  4. **`contacted` is sticky:** `set_state(a, "contacted")`, then `upsert_seen([lead_a])` returns
     `{a:"contacted"}` (not downgraded to `seen`).
  5. **`get/set_state` round-trip;** `get_state("unknown") is None`.
  6. **`place_id` dedup reinforced:** `upsert_seen([lead_a, lead_a])` (same id twice) yields a single
     row (PRIMARY KEY collapses it).
- **Add (`tests/test_pipeline.py`)** — temp DB + temp out dir (mirrors `test_walking_skeleton:14`):
  7. **Run records leads:** after `run_pipeline(...)` with `cfg.db_path = tmp_path/"x.db"`, the store
     holds the discovered `place_id`s; `result.new_count == result.raw_count`, `seen_count == 0`.
  8. **Run twice ⇒ cross-run dedup/state:** run the pipeline **a second time on the same `db_path`**;
     `result.seen_count == raw_count`, `new_count == 0`. The lead set still flows through Stages 2–4
     identically (leads are flagged `seen`, **not dropped** — counts unchanged).
  9. **Export intact:** `write_outputs` still produces `leads.csv`/`leads.jsonl`/`disqualified.jsonl`;
     CSV header contains `state`; the JSONL row for the top lead has a `state` key.
- **No live calls anywhere.** SQLite is a local file; the only I/O is `tmp_path`. The `JsonCache` path
  is untouched, so cache hits stay cheap.

## Final checks (the gate — all must pass)
```
uv run pytest -q          # existing suite + test_store.py + extended test_pipeline.py, fully offline
uv run ruff check .
uv run mypy
# Step-specific: run TWICE on the same DB to prove cross-run dedup/state (use a scratch dir):
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline --out out_d --db out_d/leadscout.db
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline --out out_d --db out_d/leadscout.db
```
The **second** offline run must report the leads as `seen` (run summary `seen=...`), prove the same
SQLite file is reused, and still write `out_d/leads.csv` (+ `.jsonl` + `disqualified.jsonl`) with a
`state` column. Don't stage `out_d/`, `.cache/`, or any `*.db`. **No live API run is part of this
gate** — item D is local-disk plumbing only.

## Definition of done (adapted from session-07 item D)
A local SQLite `LeadStore` (stdlib `sqlite3`, `src/leadscout/store.py`) persists, across runs and
sessions, (a) the set of seen businesses keyed on `place_id` — **reinforcing**, never replacing,
dedup-on-`place_id` — and (b) a per-lead `state` (`new`/`seen`/`contacted`) that round-trips on a
second run against the same DB and never downgrades `contacted`. The store sits **alongside** the
kept `JsonCache` (raw bodies) and does **not** alter the four Stage contracts or the Stage-4
LLM/opener layer. **CSV/JSONL export via `io_out.write_outputs` is preserved**, now with a `state`
column. Offline tests (`tests/test_store.py` + extended `tests/test_pipeline.py`) cover schema,
cross-run `new`→`seen`, `contacted` stickiness, and export, all against a **temp DB path**;
`uv run pytest` is green; `ruff`/`mypy` clean; the run-twice offline smoke proves cross-run dedup.
Roadmap item D marked ✅.

**Commit message:**
```
Session 07D: SQLite LeadStore for cross-run place_id dedup + lead state (alongside JsonCache; CSV/JSONL kept, offline-tested)
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **Dedup on `place_id` (mandatory, CLAUDE.md #2):** the SQLite `leads.place_id` PRIMARY KEY makes the
  dedup *durable across runs*. It **reinforces, never replaces**, the within-run `by_id`/`_norm_phone`
  dedup in `discover` (`discover.py:113`/`:60`) — both stay. One business = one row, forever.
- **Cost / LLM only in Stage 4 (CLAUDE.md #1, rules.md):** this is below all four stages — **zero**
  LLM calls added. The store records `place_id`s after Stage 1; Stage 4 still touches only Stage-2
  survivors. No model is invoked anywhere in `store.py`.
- **Secrets (CLAUDE.md #7):** SQLite is a local file with **no key**. Nothing read from or written to
  `.env`/`.env.example`; the pre-commit secret check stays. The `.db` file lives under the gitignored
  cache dir — don't stage it.
- **Legal (TRAI/TCCCPR):** the store only remembers *which businesses we've seen and their manual
  state*. **No dialing / AI-voice / blasting / sequencing** — `contacted` is an operator-set label, not
  an automated action. Output stays a list for a human to contact manually.
- **Config is data:** `db_path` is a `RunConfig` field with a sane default (`--db` override optional),
  not a hardcoded path baked into logic.
- **Definition of done / testability:** new store has a typed contract + fixture-free offline tests on
  a temp path; re-runs stay cheap (SQLite hits + the kept `JsonCache`, no network).

## Risks / unknowns (research before coding — never guess)
- **Schema migration.** v1 is the first schema; `PRAGMA user_version` + a stubbed `_migrate` hook is
  enough now. **Do not build speculative migrations** — add real ones only when the schema actually
  changes (a later session). `CREATE TABLE IF NOT EXISTS` keeps re-open idempotent.
- **Concurrent runs / locking.** SQLite single-writer locking can throw `database is locked` if two
  runs hit the same DB at once. Mitigate with `PRAGMA journal_mode=WAL` + `PRAGMA busy_timeout=5000`
  and short transactions in `upsert_seen`. This is an *internal single-operator* tool (idea.md §2), so
  concurrent runs are unlikely — don't over-engineer a connection pool; note the limitation.
- **Windows file paths.** Mirror `JsonCache.set` (`cache.py:33`): `Path(...).parent.mkdir(parents=True,
  exist_ok=True)` and pass `str(Path(db_path))` to `sqlite3.connect`. The default
  `Path(".cache/leadscout.db")` and any `tmp_path` test DB resolve correctly on Win32 (the dev OS).
  Close connections (WAL leaves `-wal`/`-shm` sidecar files; closing flushes them).
- **`Lead.state` vs. the run.** State is computed *this run* and stamped onto the in-memory `Lead` for
  display/export; the **durable** state lives in SQLite. Don't conflate them — a fresh run always
  re-reads state from the DB via `upsert_seen`. Verify the JSONL/CSV reflect the DB value, not a stale
  default.
- **Don't migrate the cache.** Tempting to "unify storage" by moving `JsonCache` blobs into SQLite —
  **don't.** It's working, it's large opaque bodies, and migrating it is risk with no item-D payoff.
  Two stores, two jobs (see the design decision).

## What NOT to do (don't pull work forward)
No **state-level tiling** (item B / `resolve_tiles` TODO at `discover.py:27`). No **owner-name /
LinkedIn enrichment** (item C). No **opener-format variants** (item E) — Stage-4 scoring and opener
generation are untouched. No new LLM calls anywhere. **Do not replace `JsonCache`** or migrate cached
bodies into SQLite — the store sits alongside it. No CRM/sequencing/auto-dialing built on top of the
`contacted` state — it's a manual label only. No new heavy dependency (stdlib `sqlite3`, no ORM). Don't
touch `.env`/`.env.example` or the pre-commit secret check; don't stage `out/`/`.cache/`/`*.db`.
