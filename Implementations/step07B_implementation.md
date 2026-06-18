# Step 07B — State-level tiling & saturation-driven subdivision — implementation plan

> Source of truth: `docs/sessions/session-07-post-mvp.md`, **item B**. This is the worked-out *how*
> for that one backlog item. Session 07 is a **menu** ("pick one per session, in roughly this
> order"); item A (JustDial/IndiaMART) is ✅ done. This plan implements **only item B** (state
> tiling + smarter subdivision) and explicitly does **not** pull forward C (owner enrichment), D
> (SQLite), or E (opener variants).
>
> **Core-principle check (CLAUDE.md):** discovery is *commodity plumbing*. This step must be
> **boring, correct, and cheap** — better tile coverage feeding the **same** `place_id` dedup. **Zero
> LLM** (Stage 1 only). Do not gold-plate: subdivide only when a `(tile, keyword)` actually saturates,
> stop at a bounded depth, and keep the new code small.

## Goal & scope
Extend discovery so a `state`-level (or any large-bbox) `GeographyInput` reliably covers its area
without losing businesses to the Places ~60-result/3-page cap (idea.md §7/§10). Today
`resolve_tiles` already geocodes `geo.city or geo.state` to a bbox and tiles it (`discover.py:31-34`),
so a state input *runs* — but for a dense `(tile, keyword)` it silently drops everything past the
60th result. The `LivePlacesClient.search` loop only **logs** that saturation (`clients.py:133-141`);
it is **not observable** to `discover`, which is the gap this step closes. "Done" means: (1)
saturation becomes observable to the discovery loop; (2) when a `(tile, keyword)` saturates, that
tile is **subdivided** into four smaller circular sub-tiles and the keyword re-searched there, down
to a **bounded depth**; (3) all of this still funnels through the existing `by_id` `place_id` dedup
(now stressed harder by overlapping sub-tiles) and the cross-source phone dedup from item A; (4) the
much larger tile count a state implies is handled deterministically and cheaply (cache-backed,
keep re-runs free); and the whole thing is covered by **offline** fixture-backed tests with
`uv run pytest` green and `ruff`/`mypy` clean. The `TODO(saturation)` in `resolve_tiles`
(`discover.py:26-28`) is resolved by this step. No new LLM calls; no Stage 2–4 contract churn.

## Prerequisites (confirmed against code, not just the roadmap)
- ✅ **`GeographyInput.state` already exists** (`models.py:38`) and the `_exactly_one` validator
  (`models.py:41-46`) accepts it. `resolve_tiles` already does `query = geo.city or geo.state or ""`
  then `client.geocode_bbox(query)` → `_tile_bbox(bbox)` (`discover.py:31-34`). **State support is
  partly there** — the missing piece is subdivision, not a new geography branch.
- ✅ **The subdivision hook is real and identified.** `resolve_tiles` has the `TODO(saturation)`
  comment in the `bbox` branch (`discover.py:26-28`) pointing at `LivePlacesClient.search`. But
  saturation is detected **inside the search loop** (`clients.py:133-141`), per `(tile, keyword)` —
  **not** at tile-resolution time. So the comment's *placement* is misleading: `resolve_tiles` runs
  once, up front, with no knowledge of which tiles will saturate. **Subdivision must be driven from
  the `discover.discover` search loop** (`discover.py:121-130`), where the per-`(tile, keyword)`
  result list is actually seen — not statically in `resolve_tiles`.
- ⚠️ **Saturation is currently NOT observable to the caller.** `PlacesClient.search`
  (`clients.py:37`) returns `list[dict]`; `LivePlacesClient.search` only `logger.warning(...)`s on
  saturation (`clients.py:133-141`) and `FixturePlacesClient.search` (`clients.py:55-59`) has no
  saturation concept at all. `discover.discover` therefore cannot tell a saturated tile from a sparse
  one. **Making saturation observable is the central design task of this step** (see step 1).
- ✅ **`_tile_bbox` is the existing tiler** (`discover.py:37-57`): overlapping circles, spacing =
  radius, radius defaults to `_DEFAULT_TILE_RADIUS_KM = 40.0` under the `PLACES_RADIUS_CAP_KM = 50.0`
  cap. Subdivision will reuse the same overlap discipline at a smaller radius.
- ✅ **Dedup already survives overlap.** `discover.discover` keys `by_id: dict[str, Lead]` on
  `place_id` (`discover.py:113`, gate at `:127`) and adds cross-source phone dedup
  (`seen_phones`, `:114-119`, `:137-138`) from item A. Overlapping sub-tiles produce *more* overlap;
  the existing dedup absorbs it. **No dedup redesign needed — but tests must prove it holds under
  subdivision.**
- ✅ **Cache makes re-runs cheap.** `LivePlacesClient.search` caches each `(tile, keyword)` page-set
  under `places_pages` keyed by `f"{round(lat,4)},{round(lng,4)},r{int(radius_m)}|{keyword}"`
  (`clients.py:119`, `:144-148`). Sub-tiles have distinct lat/lng/radius, so they get distinct cache
  keys for free — a state re-run hits cache, no live calls.
- ✅ **Offline test seam is established.** `FixturePlacesClient` (`clients.py:40-59`) drives every
  discovery test; `tests/conftest.py` wires `load_fixture_clients(FIXTURES)`; `tests/test_discover.py`
  already exercises `resolve_tiles` and `discover`. New tests extend this exact pattern — **no
  network**.
- ✅ **MVP + item A done and green** (roadmap; `tests/test_discover.py`, `tests/test_sources.py`).

## Design decision required before coding — how saturation flows back
Saturation is observed per `(tile, keyword)` *inside* the search loop, but `search` currently hides
it. Two viable shapes; **pick #1**:

1. **Recommended — explicit saturation signal on the client + recursive subdivide in `discover`.**
   Add a small, typed way for `search` to report "this query saturated." Sub-options considered:
   - A stateful `last_query_saturated() -> bool` predicate is **rejected** (stateful, race-prone
     across calls).
   - **Chosen:** change `PlacesClient.search` to return a tiny pydantic `SearchPage`
     (`results: list[dict]`, `saturated: bool`) — explicit, stateless, testable. (See Contracts.)
   - `discover.discover` then, per `(tile, keyword)`, if `page.saturated` **and** `tile.depth <
     MAX_SUBDIVIDE_DEPTH`, subdivides the tile into 4 quadrant sub-tiles (half-radius, overlapping)
     and re-runs the **same keyword** on each. Recurse until not saturated or depth cap hit. All
     results flow into the same `by_id`/`seen_phones` dedup.
2. **Alternative — subdivide eagerly in `resolve_tiles` by density heuristic.** Rejected:
   `resolve_tiles` cannot know density without searching; eager fine-tiling explodes query count for
   sparse areas (violates "cheap"), and the cap is the only ground-truth saturation signal.

**Chosen: #1 with `SearchPage`.** It is deterministic, observable, offline-testable (the fixture
client can mark a `(tile, keyword)` saturated), and keeps subdivision logic in Stage 1 where it
belongs. **Subdivision is bounded by `MAX_SUBDIVIDE_DEPTH` (recommend 2 → at most 4²=16 sub-tiles per
saturated top tile) and a hard total-tile ceiling** so a pathological dense state can't run away.

## Files to create / modify
| Path | Change |
|---|---|
| `src/leadscout/models.py` | **Add** `SearchPage` (`results: list[dict]`, `saturated: bool`) — the new `search` return type. **Add** an optional `depth: int = 0` field to `Tile` so subdivision can track recursion depth (default keeps existing `Tile(...)` construction valid). No other model change; `GeographyInput.state` already exists. |
| `src/leadscout/clients.py` | **Modify** `PlacesClient.search` Protocol + both impls to return `SearchPage`. `LivePlacesClient.search` sets `saturated=True` exactly where it currently logs the warning (`clients.py:133-141`) — keep the log. `FixturePlacesClient.search` reports `saturated` from a fixture flag (per-keyword tag). |
| `src/leadscout/stages/discover.py` | **Modify** `discover.discover` search loop (`:121-130`) to consume `SearchPage`, and **add** `_subdivide(tile)` + a recursive/queue-based search-with-subdivision helper. **Add** module constants `MAX_SUBDIVIDE_DEPTH`, `MAX_TILES` (safety ceiling). **Replace** the `TODO(saturation)` comment in `resolve_tiles` (`:26-28`) with a one-line note that subdivision is driven from the search loop. Keep `resolve_tiles`/`_tile_bbox` behavior for the initial grid intact. |
| `fixtures/places.json` | **Edit (data)** — add a way to mark a `(tile,keyword)` as saturated for one keyword (e.g. a top-level `"saturated_keywords": ["dentist"]` flag the fixture client reads) **without** breaking the existing 3 discover tests. |
| `examples/karnataka.yaml` | **Create (data)** — a `state: "Karnataka"` geography YAML to demonstrate/run state-level tiling (`load_geography` already accepts a YAML path, `config.py:59-64`). Mirrors `examples/bengaluru.yaml` shape. |
| `tests/test_discover.py` | **Extend** — saturation→subdivision, depth cap, dedup-survives-subdivision, state-YAML resolves to multi-tile, `SearchPage` consumed correctly. |
| `tests/conftest.py` | **Possibly extend** — a `state_geo` fixture (`load_geography(EXAMPLES / "karnataka.yaml")`) if tests need it; otherwise construct inline. |
| `docs/sessions/session-07-post-mvp.md`, `docs/sessions/README.md` | Mark item B ✅ with a one-line outcome (07 stays 🔨 overall until C–E are done; record B as ✅ within the file/row note). |

## Implementation steps (ordered, each independently verifiable)
1. **Make saturation observable — add `SearchPage` and rethread `search`.**
   In `models.py` add:
   ```python
   class SearchPage(BaseModel):
       results: list[dict] = Field(default_factory=list)
       saturated: bool = False  # hit the ~60-result/3-page cap with more available
   ```
   Change the `PlacesClient.search` Protocol (`clients.py:37`) to return `SearchPage`. Update
   `LivePlacesClient.search` (`clients.py:117-148`): keep the loop, set a local `saturated` flag
   `True` in the branch that currently logs (`:133-141`, i.e. `page_token` still present at break),
   and return `SearchPage(results=results, saturated=saturated)`. **For cached re-runs, recompute
   `saturated` on cache read** as `len(results) >= MAX_RESULTS` (no cache-format migration; see
   Risks) so cached re-runs still subdivide identically. Update `FixturePlacesClient.search`
   (`clients.py:55-59`) to read a saturation flag from the fixture and return `SearchPage`.
   *Verify:* `mypy` clean; existing 3 discover tests updated to read `page.results`.
2. **Add subdivision geometry in `discover.py`.** Add constants near the top
   (`PLACES_RADIUS_CAP_KM` etc., `:14-16`):
   ```python
   MAX_SUBDIVIDE_DEPTH = 2      # at most 4**2 = 16 sub-tiles per saturated top tile
   MAX_TILES = 2000             # hard safety ceiling on total tiles searched per run
   ```
   Add `Tile.depth` handling and `_subdivide(tile: Tile) -> list[Tile]`: split a tile into 4
   quadrant centers, each at **half the parent radius** (so they fit under the 50 km cap and overlap
   — spacing = radius, same discipline as `_tile_bbox`), `depth = tile.depth + 1`. Offsets in degrees
   use the same lat/lng-per-km math already in `_tile_bbox` (`:43-47`). *Verify:* unit test that
   `_subdivide` returns 4 tiles, each `radius_km` ≈ half parent, each `depth` = parent+1, centers
   inside the parent circle's footprint.
3. **Drive subdivision from the search loop.** Refactor the Places loop in `discover.discover`
   (`:121-130`). Replace the flat `for tile in tiles:` over `client.search(...)` with a small
   work-queue / recursion: for each top tile and each keyword, call `client.search(...)`, ingest
   `page.results` into `by_id`/`seen_phones` (unchanged dedup gates at `:127`, `_claim_phone`), and
   **if `page.saturated and tile.depth < MAX_SUBDIVIDE_DEPTH`**, push `_subdivide(tile)` onto the
   queue for that same keyword. Stop enqueuing when total tiles searched ≥ `MAX_TILES` (log a
   warning, same spirit as `clients.py:137`). Keep the keyword loop semantics. *Verify:* with a
   fixture marking `"dentist"` saturated at depth 0, the loop searches the 4 sub-tiles; with depth cap
   1, it stops one level down.
4. **Resolve the `TODO(saturation)`.** In `resolve_tiles` (`discover.py:26-28`) replace the
   `TODO(saturation)` comment with a one-liner: subdivision is now handled in `discover.discover`'s
   search loop (saturation is only observable there), `resolve_tiles` just produces the initial grid.
   Leave `_tile_bbox` and the city/state/point/bbox branches functionally unchanged. *Verify:*
   `test_bbox_tiling_overlaps_and_caps_radius` and `test_point_geography_is_single_tile` still pass.
5. **State coverage path.** Confirm `state` flows through unchanged: `GeographyInput(state="Karnataka")`
   → `resolve_tiles` → `geocode_bbox("Karnataka")` → `_tile_bbox(bbox)` produces many tiles; each can
   independently subdivide on saturation. Add `examples/karnataka.yaml` (`state: "Karnataka"`).
   For **offline** testing, the `FixturePlacesClient.geocode_bbox` returns the fixture bbox
   (`clients.py:52-53`) regardless of query, so a state YAML resolves to the same tiled grid as the
   city fixture — enough to assert "state input resolves to ≥N tiles and runs end-to-end offline."
   *Verify:* a test loads `karnataka.yaml`, runs `discover`, gets a deduped lead list with no error.
6. **Bound the blast radius (cheapness guard).** Ensure `MAX_TILES` actually caps work and that the
   default (non-saturated) path is **identical to today** — a sparse `(tile, keyword)` returns
   `saturated=False`, so **no** subdivision happens and query count is unchanged. This protects the
   "Stages 1–3 are cheap" non-negotiable. *Verify:* test that a non-saturated fixture produces the
   exact same lead set/count as before this step (regression guard).
7. **Tests (offline, fixtures only).** See the Tests section. All via `FixturePlacesClient` — no
   network, no live Places.
8. **Docs.** Update `docs/sessions/session-07-post-mvp.md` (mark item B ✅ with a one-line outcome)
   and the README row note. Write/update a handoff if used.

## Contracts & types
- **`SearchPage`** — **new** pydantic model (`results: list[dict]`, `saturated: bool`). This is the
  one intentional contract change: `PlacesClient.search` now returns `SearchPage` instead of
  `list[dict]`. It is additive in information (the `results` list is the old return value) and both
  impls + every `search` call site (only `discover.discover`, `discover.py:123`) are updated in lock
  step. **`SourceClient.discover` is untouched** — extra sources don't tile and don't saturate
  (they search by city text; item A, `clients.py:216-221`), so their merge loop (`discover.py:132-140`)
  is unchanged.
- **`Tile`** — **add** `depth: int = 0` (`models.py:88-93`). Default 0 keeps every existing
  `Tile(lat=..., lng=..., radius_km=...)` construction valid (`discover.py:23`, `:54`, `:57`;
  `tests/test_discover.py`). The `radius_km` `Field(gt=0, le=50)` cap still holds for sub-tiles
  (half-radius is always < 50).
- **`GeographyInput`** — **unchanged**; `state` already present (`models.py:38`).
- **`discover.discover`** — signature unchanged (`geo, niche, client, extra_sources=None`). Internal
  loop refactored to consume `SearchPage` and subdivide. Return type unchanged: `list[Lead]`,
  deduped on `place_id`.
- **`Lead`** — **unchanged**. Subdivision only changes *which tiles* are searched, never the lead
  shape.
- **No change** to `filter`, `enrich`, `score` contracts, `ScoreResult`, `RunConfig`, or
  `pipeline.run_pipeline`. **Stage 4 LLM untouched.**

## Tests (offline; pytest stays fully green, zero network)
- **Keep green (update for `SearchPage`):** the three existing `tests/test_discover.py` tests. Only
  change: anywhere a test or fixture client returned/consumed `list[dict]` from `search`, it now uses
  `SearchPage.results`. Assertions on dedup and tile counts are unchanged.
- **Add (`tests/test_discover.py`):**
  1. **`SearchPage` plumbing:** `FixturePlacesClient.search(...)` returns a `SearchPage`; with no
     saturation flag, `.saturated is False` and `.results` equals today's list.
  2. **`_subdivide` geometry:** returns 4 tiles; each `radius_km == parent.radius_km / 2` (approx),
     each `depth == parent.depth + 1`, centers offset from the parent and staying near it. No tile
     exceeds the 50 km cap.
  3. **Saturation triggers subdivision:** with a fixture marking keyword `"dentist"` saturated at the
     top level, `discover` searches sub-tiles and the final deduped lead set is **a superset** of (or
     equal to) the non-subdivided run — and still has unique `place_id`s. (Model sub-tile-only
     results in the fixture if exercising "subdivision finds *new* leads"; otherwise assert
     subdivision ran without breaking dedup.)
  4. **Depth cap:** with saturation that would recurse forever, assert recursion stops at
     `MAX_SUBDIVIDE_DEPTH` (e.g. monkeypatch the constant lower in the test, or count searched tiles ≤
     the depth-bounded maximum). No infinite loop.
  5. **Dedup survives subdivision:** overlapping sub-tiles return overlapping results; final
     `len(ids) == len(set(ids))` (the existing `test_dedup_on_place_id` invariant, now under
     subdivision). Cross-source phone dedup from item A still holds if extra sources are wired.
  6. **State input resolves & runs offline:** `GeographyInput(state="Karnataka")` (or
     `load_geography(EXAMPLES / "karnataka.yaml")`) → `resolve_tiles` yields ≥4 tiles; `discover`
     returns a non-empty deduped list with no error.
  7. **Regression / cheapness:** a non-saturated fixture yields the **same** lead count as a baseline
     (no spurious subdivision; default path unchanged).
- **No live Places call anywhere in pytest.** Saturation is simulated purely via the fixture flag;
  `LivePlacesClient` is never instantiated in tests (consistent with `tests/conftest.py`).

## Final checks (the gate — all must pass)
```
uv run pytest -q          # existing + new discover tests, fully offline
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo examples/karnataka.yaml --niche examples/dental.yaml --offline
```
The offline smoke run must succeed with a **state** geography and exercise the `SearchPage`/initial
grid path (subdivision only fires if a fixture marks saturation; offline geocode returns the fixture
bbox). A **live** state run is operator-driven (real Google Maps key, real cost) and is **not** in
CI/pytest.

## Definition of done (adapted from session-07 item B)
`state`-level geography tiles correctly and a saturated `(tile, keyword)` subdivides into smaller
overlapping sub-tiles (bounded by `MAX_SUBDIVIDE_DEPTH` and `MAX_TILES`), with all results funneling
through the existing `place_id` (+ cross-source phone) dedup so overlap never produces duplicate
leads. Saturation is **observable** to `discover` via `SearchPage.saturated` (replacing the
log-only behavior and resolving the `resolve_tiles` `TODO(saturation)`). The sparse/non-saturated
path and Places-only runs are **byte-identical to today** (no spurious subdivision). Offline
fixture-backed tests cover subdivision, depth cap, dedup-under-overlap, and state resolution;
`uv run pytest` is green; `ruff`/`mypy` clean; the offline state smoke run passes. Roadmap item B
marked ✅.

**Commit message:**
```
Session 07B: state-level tiling with saturation-driven tile subdivision (SearchPage signal, bounded depth, dedup-preserving, offline-tested)
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **Cost / LLM only in Stage 4 (CLAUDE.md #1, rules.md Cost):** pure **Stage 1** work — **zero** LLM
  calls added. Subdivision only grows the *raw* pull where the area is genuinely dense; Stage 2 still
  gates before any token spend. `MAX_SUBDIVIDE_DEPTH` + `MAX_TILES` bound query count so a state run
  stays cheap and can't run away. Cache keys differ per sub-tile, so re-runs hit cache, not the
  network.
- **Dedup on `place_id` (CLAUDE.md #2, rules.md Dedup — mandatory):** preserved and **stress-tested**
  — overlapping sub-tiles produce more overlap, and `by_id` (+ `seen_phones` from item A) absorbs it.
  A dedicated test asserts uniqueness holds under subdivision.
- **Places reality (CLAUDE.md #3, idea.md §7/§10):** this step is *the* honest answer to "you cannot
  set radius = whole state" — tile, paginate, **subdivide on the 60-cap**, dedup. Sub-tile radius
  stays under `PLACES_RADIUS_CAP_KM`.
- **Scraping etiquette (rules.md):** unchanged — no new fetch surface; sub-tiles reuse the existing
  cached, paginated `LivePlacesClient.search`.
- **Legal (TRAI/TCCCPR):** unchanged — output stays a human-call list; subdivision only *finds* more
  businesses. No dialing / AI-voice / blasting.
- **Secrets:** no new keys; `.env`/`.env.example` untouched; pre-commit secret check intact.
- **Config is data:** state geography is a YAML (`examples/karnataka.yaml`); `--geo "Karnataka"` also
  works via `load_geography`. Subdivision constants are sensible internal defaults (tunable later);
  no product-specific value is hardcoded into logic.

## Risks / unknowns (research before any live run — never guess Places behavior)
- **The ~60-result cap is the only saturation signal we have — verify its exact shape.** The plan
  treats "`nextPageToken` still present when we stop" (`clients.py:133`) as the saturation truth.
  Confirm against the live Places (New) Text Search docs that (a) `MAX_PAGES = 3` × `pageSize = 20` is
  still the real ceiling, and (b) a present `nextPageToken` at the cap reliably means "more results
  exist." **Do not assume** — check current API behavior; the cap could have changed.
- **Subdivision does not guarantee escaping the cap.** A single ~half-radius sub-tile over a hyper-dense
  area (e.g. a metro core inside a state) can *still* return 60+. `MAX_SUBDIVIDE_DEPTH` deliberately
  caps recursion, so the deepest sub-tiles may still drop tail results — an accepted limitation for
  "boring plumbing." Note it; do not chase perfect recall with unbounded recursion (cost risk).
- **Geocoding a state returns a large viewport.** `geocode_bbox` returns the geocoder *viewport*
  (`clients.py:108-112`); for a whole state that bbox can be huge, yielding **hundreds** of top tiles
  before any subdivision. Verify the live tile count for a real state is sane and bounded by
  `MAX_TILES`; consider logging the initial tile count. (Offline, the fixture bbox is small, so tests
  can't catch a runaway — flag for the live operator.)
- **Cost of a live state run.** Many tiles × keywords × up to 3 pages × possible subdivision = many
  Places calls. This is a **discovery-cost** (Places billing), separate from the LLM budget ceiling.
  Surface the projected query count (e.g. log `len(tiles)` and a subdivision counter) so the operator
  isn't surprised. Caching keeps re-runs free; the *first* state run is the expensive one.
- **`SearchPage` cache compatibility.** Existing caches under `places_pages` store a bare list
  (`clients.py:145`). Decide: recompute `saturated` on cache read as `len(results) >= MAX_RESULTS`
  (simplest, no cache-format change, no migration) **or** store a dict `{results, saturated}` (cleaner
  but invalidates old cache entries). **Recommend recompute-on-read** to avoid a cache migration.
- **Sub-tile geometry edge cases.** Near the poles / antimeridian the lat-lng-per-km math degrades.
  India is far from both, so acceptable for this tool — note it, don't over-engineer.

## What NOT to do (don't pull work forward)
No owner-name / LinkedIn enrichment (item C). No SQLite cross-run store (item D) — keep the existing
`JsonCache`/CSV outputs. No opener-format variants (item E). No new LLM calls anywhere. No
Stage 2–4 contract changes. No changes to `SourceClient`/JustDial/IndiaMART beyond the unchanged
merge loop. No unbounded recursion (always honor `MAX_SUBDIVIDE_DEPTH`/`MAX_TILES`). No live Places
calls in pytest. Don't touch `.env`/`.env.example`, gitignored files, or Stage-4 budget enforcement.
