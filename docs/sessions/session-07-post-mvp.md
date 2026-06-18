# Session 07+ — Post-MVP backlog

**Status:** ⬜ not started
**Goal:** parking lot for work explicitly deferred past MVP (idea.md §11, §13). Pull one item into
its own session when MVP (Session 06) is solid. Don't start these early — MVP first.

## Candidate sessions (pick one per session, in roughly this order)

### A. JustDial / IndiaMART adapters (idea.md §7 India coverage) — ✅ done
New source clients feeding the **same** `discover` dedup step; normalize into the `Lead` shape
with the right `source` tag. Places thins out for tier-2/3 shops — these fill the gap. Mind ToS
and scraping etiquette.

**Outcome:** `SourceClient` Protocol with fixture + live (`JustDialClient`/`IndiaMartClient`,
JSON-LD parse, robots/rate-limit/cache) impls; raws normalize via `discover._raw_to_lead` into the
`Lead` shape with `source` tag + synthetic `place_id` (`justdial:<id>`). They merge into the same
`discover` dedup plus best-effort cross-source phone dedup (last-10 digits, Google Places
canonical). Toggled as data via `NicheSpec.sources` (default Places-only; `dental.yaml` enables
JustDial, IndiaMART off). Offline tests in `tests/test_sources.py`; `pytest` (49) green, `ruff`/
`mypy` clean. **Live multi-source fetch is operator-gated on confirming robots.txt/ToS** (the live
URL shapes are starting points, not verified endpoints). Items B–E remain ⬜.

### B. State-level tiling (idea.md §7) — ✅ done
Today city→bbox→tiles works; extend to `state` with smarter tile subdivision when a `(tile,
keyword)` exceeds the 60-result cap (the hook is noted in `discover.resolve_tiles`).

**Outcome:** `SearchPage(results, saturated)` return from `PlacesClient.search`; `_subdivide`
splits a saturated tile into 4 half-radius sub-tiles; `discover.discover` drives subdivision via a
work queue, bounded by `MAX_SUBDIVIDE_DEPTH=2` and `MAX_TILES=2000`. `Tile.depth` tracks recursion.
Fixture client reads `saturated_keywords` flag. `examples/karnataka.yaml` added. 12 new tests
(subdivision geometry, saturation signal, depth cap, dedup-under-overlap, state-YAML end-to-end,
regression guard); 61 total pytest green; ruff/mypy clean; offline state smoke run passes.

### C. Owner-name enrichment (idea.md §12.3) — ✅ done
Best-effort decision-maker name beyond what the homepage gives. LinkedIn is fragile/ToS-sensitive
— decide how hard to try vs. accept business-level contact. Don't build anything that violates ToS.

**Outcome:** Stage 3 now extracts `owner_name` from homepage + on-site candidate pages (`/about`,
`/about-us`, `/team`, `/contact`) using two patterns: `_OWNER_LABEL_RE` ("Owner/Founder/Proprietor:
Name") and the existing `_OWNER_RE` ("Dr. Name"). `_best_owner` tries label form first, returns
`None` on no match — never guesses. Extra page fetches obey the same robots/rate-limit/cache path
as the homepage and fold into the single per-`place_id` cache entry (warm runs = zero fetches).
Off-site/LinkedIn lookup explicitly declined on ToS + fragility grounds; reasoning recorded in code
and `Implementations/step07C.md`. Zero LLM added. 9 enrich tests green; ruff/mypy clean; offline
smoke run passes. Items D–E remain ⬜.

### D. SQLite for cross-run dedup & state (idea.md §12.4) — ✅ done
Move from flat-file cache + CSV to a lightweight local SQLite DB so dedup and lead state persist
across sessions/runs. Keep CSV/JSONL export.

**Outcome:** `LeadStore` (`src/leadscout/store.py`, stdlib `sqlite3`) persists a `leads` table
keyed on `place_id` with state (`new`/`seen`/`contacted`). Sits **alongside** the kept `JsonCache`
(raw HTTP bodies) — two stores, two responsibilities. `upsert_seen` bumps `new`→`seen` on
re-encounter; `contacted` is sticky. `Lead.lead_state` carries the per-run DB state (additive field,
default `None`). `PipelineResult` gains `new_count`/`seen_count`. `RunConfig.db_path` (default
`.cache/leadscout.db`) threads through CLI as `--db`. `leadscout mark <place_id> <state>` added for
operator-driven state advancement. `lead_state` column added to CSV. 9 new tests (`test_store.py`
+ extended `test_pipeline.py`; all temp-path, zero network); 76 pytest green; ruff/mypy clean.
Run-twice offline smoke proves cross-run state: run 1 `new=10 seen=0`, run 2 `new=0 seen=10`.
Item E remains ⬜.

### E. Opener format variants (idea.md §12.5)
Call-script vs email vs WhatsApp opener templates, selectable per run. Still grounded in detected
signals — no generic templates.

## Hard out-of-scope (do NOT build — idea.md §10/§11)
- Auto-dialing, AI-voice calling, bulk email/WhatsApp blasting — not even a stub.
- CRM integration / sequencing, multi-user SaaS, auth, billing, web UI (unless it earns its place).
