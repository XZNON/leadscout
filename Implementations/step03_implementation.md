# Step 03 — Live discovery (Google Places API New) — implementation plan

> Source of truth: `docs/sessions/session-03-live-discover.md`. This file is the worked-out *how*
> for that one step. **Do not pull work forward** from Sessions 04–07 (no live scraping, no live
> LLM, no tile-subdivision feature). This step makes **Stage 1 only** real.

## Goal & scope
Replace the two `NotImplementedError` stubs on `LivePlacesClient` (`geocode_bbox`, `search`) in
`src/leadscout/clients.py` with real calls to Google **Geocoding API** and **Places API (New) Text
Search**, behind the *unchanged* `PlacesClient` Protocol so nothing downstream (`discover.discover`,
`run_pipeline`) or any existing test changes. "Done" means: a live run against a tight Bengaluru
point/radius returns real, **deduped-on-`place_id`** dentists; results are **cached** (per
`(tile,keyword)` page and per `place_id`) so a second run of the same geo makes ~zero new API calls;
the offline fixture pipeline and all existing tests stay green; and a new **offline** test proves
the live client's request-building, response-normalization, pagination, and caching using an
injected `httpx.MockTransport` (no network in pytest). The minimal field mask (no review text) is
honored; richer review fetching is explicitly deferred.

## Prerequisites (confirmed)
- ✅ Session 02 green (`219910d`): `pytest` 14 passed, `ruff`/`mypy` clean, offline run writes a
  correctly-ranked `leads.csv` + 6-row `disqualified.jsonl`.
- ✅ `httpx==0.28.1` already installed (declared in `pyproject.toml`); `httpx.MockTransport` is
  available for offline tests.
- ✅ `JsonCache` exists (`src/leadscout/cache.py`) with `get/set/has(namespace, key)` and is already
  instantiated in `pipeline.py` (`JsonCache(cfg.cache_dir)`), currently passed only to `enrich`.
- ✅ `PlacesClient` Protocol = `geocode_bbox(query) -> BBox`, `search(lat,lng,radius_km,keyword) -> list[dict]`.
- ✅ `discover._raw_to_lead` consumes raw dicts and already tolerates New-API-ish keys
  (`websiteUri`, `internationalPhoneNumber`, `formattedAddress`, `userRatingCount`, `primaryType`,
  `businessStatus`) — **except** it requires `raw["place_id"]` and a **string** `name`.
- ⚠️ `GOOGLE_MAPS_API_KEY` must be in `.env` for the *live* spot-check only. Owner-managed; do **not**
  touch `.env`/`.env.example`. Tests never need it (MockTransport).

## API facts (researched — do not re-guess; re-verify only if a 4xx says otherwise)
**Geocoding** — `GET https://maps.googleapis.com/maps/api/geocode/json?address=<query>&key=<key>`.
Viewport bbox at `results[0].geometry.viewport` → `{ "northeast": {lat,lng}, "southwest": {lat,lng} }`.
Map to `BBox(min_lat=southwest.lat, min_lng=southwest.lng, max_lat=northeast.lat, max_lng=northeast.lng)`.
Check top-level `status == "OK"` (else `ZERO_RESULTS` / `REQUEST_DENIED` → raise with the message).

**Places Text Search (New)** — `POST https://places.googleapis.com/v1/places:searchText`.
- Headers: `X-Goog-Api-Key: <key>`, `Content-Type: application/json`,
  `X-Goog-FieldMask: <comma-separated paths>`.
- Minimal field mask (billing-conscious, per session file — **no reviews**):
  `places.id,places.displayName,places.primaryType,places.rating,places.userRatingCount,places.websiteUri,places.internationalPhoneNumber,places.businessStatus,places.formattedAddress,nextPageToken`
  (include `nextPageToken` in the mask so pagination tokens are returned).
- Body: `{"textQuery": keyword, "pageSize": 20, "locationRestriction": {"circle": {"center":
  {"latitude": lat, "longitude": lng}, "radius": radius_m}}}`, where `radius_m = min(radius_km,50)*1000`
  (hard cap 50000.0 m). On later pages add `"pageToken": <token>`.
- Response: `{"places": [ {id, displayName:{text,languageCode}, primaryType, rating,
  userRatingCount, websiteUri, internationalPhoneNumber, businessStatus, formattedAddress}, ... ],
  "nextPageToken": <opt>}`. **Max 60 results across ≤3 pages.**

**Normalization seam (critical):** New API returns `id` (not `place_id`) and `displayName` as an
**object**. `LivePlacesClient.search` must emit dicts shaped for `_raw_to_lead`: set
`place_id = p["id"]` and `name = (p.get("displayName") or {}).get("text", "")` (a **string**),
then pass the rest through unchanged (`websiteUri`, `internationalPhoneNumber`, `formattedAddress`,
`rating`, `userRatingCount`, `primaryType`, `businessStatus`). Do **not** edit `_raw_to_lead` — it's
a stable shared contract; shape the live output to fit it.

## Files to create / modify
- `src/leadscout/clients.py` — **modify**. Implement `LivePlacesClient.geocode_bbox` and
  `.search`; extend `LivePlacesClient.__init__` to accept `cache: JsonCache | None = None` and
  `timeout_s: float = 10.0` and own an internal `httpx.Client` (injectable for tests). Add a tiny
  private `_post`/`_get` + normalize + paginate helper(s). Import `httpx` and `JsonCache`.
  **The `PlacesClient` Protocol is unchanged.**
- `src/leadscout/cli.py` — **modify (wiring only)**. Construct
  `LivePlacesClient(require_key("GOOGLE_MAPS_API_KEY"), cache=JsonCache(cfg.cache_dir), timeout_s=cfg.request_timeout_s)`.
  Add `from .cache import JsonCache`. No behavior change to the offline branch.
- `tests/test_live_discover.py` — **create**. Offline-only tests using `httpx.MockTransport`:
  request-building, response normalization, pagination across `nextPageToken`, and cache-hit
  (no second network call). Plus a `geocode_bbox` viewport→`BBox` test.
- *(create on run, gitignored)* `.cache/places/*.json`, `.cache/geocode/*.json` — cache artifacts.
- `docs/sessions/session-03-live-discover.md` & `docs/sessions/README.md` — flipped to ✅ **only
  after** the live spot-check + gate pass (done by the implementing session, not this planning one).

## Implementation steps (ordered, each independently verifiable)
1. **Constructor + HTTP seam.** Change `LivePlacesClient.__init__(self, api_key, cache=None,
   timeout_s=10.0, client: httpx.Client | None = None)`. Store `self.api_key`, `self._cache`,
   `self._http = client or httpx.Client(timeout=timeout_s)`. The `client` param is the **offline
   test seam** (pass `httpx.Client(transport=httpx.MockTransport(handler))`); it is implementation
   detail, not part of the `PlacesClient` Protocol. *Verify:* constructs without network.
2. **`geocode_bbox(query)`.** Check cache namespace `"geocode"` key `query` first; on miss, GET the
   Geocoding endpoint, assert `status == "OK"`, read `results[0].geometry.viewport`, build `BBox`,
   `cache.set("geocode", query, bbox.model_dump())`, return it. *Verify:* unit test maps a canned
   viewport to the right `BBox`; second call returns cached value without a transport hit.
3. **`search(lat,lng,radius_km,keyword)` with full pagination.** Compute a stable cache key
   `key = f"{round(lat,4)},{round(lng,4)},r{int(min(radius_km,50)*1000)}|{keyword}"`. If
   `cache.has("places_pages", key)`, return the cached list. Otherwise loop: POST `:searchText`
   with the field mask + circle body; append `_normalize(p)` for each `p` in `places`; if
   `nextPageToken` present and pages `< 3` and total `< 60`, set `pageToken` and continue, else
   stop. Write the assembled list to `cache.set("places_pages", key, results)` **and** each
   normalized place to `cache.set("places", place_id, place)` (namespace `"places"`, per session
   file). Return the list. *Verify:* pagination test below.
4. **Normalize helper.** `_normalize(p: dict) -> dict` → `{**p, "place_id": p["id"], "name":
   (p.get("displayName") or {}).get("text","")}`. Keeps `_raw_to_lead` untouched. *Verify:* a
   normalized dict round-trips through `_raw_to_lead` into a valid `Lead`.
5. **60-cap / saturation handling (log, don't subdivide).** If the loop stops because it hit 3
   pages / 60 results while `nextPageToken` was still present, emit a `warnings.warn` /
   `logging.warning` that the `(tile,keyword)` is saturated and note that tile subdivision /
   keyword narrowing hooks in at `discover.resolve_tiles` (leave as a TODO comment there — **do not
   implement** subdivision this step).
6. **Pagination-token validity backoff (live only).** New-API `pageToken` may briefly return
   `INVALID_ARGUMENT` immediately after the prior page (legacy needed ~2 s). If a paged POST returns
   that, retry up to 2× with a short backoff (e.g. 1.5 s) **in live code only**. Tests use
   MockTransport that returns valid pages immediately, so **pytest never sleeps**. (Flag in Risks —
   confirm against a real 4xx during the spot-check.)
7. **CLI wiring.** Pass the cache + timeout into `LivePlacesClient` in `cli.py` (see Files). Offline
   branch unchanged.
8. **Live spot-check (manual, not in CI).** With a real key in `.env`:
   `uv run leadscout run --icp examples/clinic.yaml --geo examples/bengaluru.yaml --niche examples/dental.yaml`
   (the `bengaluru.yaml` point = single 10 km tile → no geocoding, cheap). Confirm: real deduped
   dentists; `place_id` dedup holds across the two niche keywords; a **second** run prints the same
   counts with ~zero new API cost (cache hits). Spot-check `.cache/places/*.json` exists. **Never
   add this command to pytest.**

## Contracts & types (touched vs. stable)
- **Stable (do not change):** `PlacesClient` Protocol signature, `BBox`, `Tile`, `GeographyInput`,
  `Point`, `Lead`, `discover._raw_to_lead`, `discover.discover`, `discover.resolve_tiles` behavior,
  `run_pipeline`, `PipelineResult`. Stage 1's typed output (`list[Lead]`) is unchanged.
- **Touched (implementation detail only):** `LivePlacesClient.__init__` gains `cache`, `timeout_s`,
  `client` params; new private helpers `_normalize`, `_get_geocode`, `_search_page`. None of these
  appear in the `PlacesClient` Protocol, so downstream/tests are unaffected. Any change beyond these
  to a shared contract is out of scope — stop and reassess.

## Tests (existing stay green; one new file, all offline)
- **Keep green, unchanged:** `tests/test_discover.py` (dedup-on-`place_id`, point→single tile,
  bbox→multi-tile cap), and the other four test files. They use `FixturePlacesClient` — no live
  path — so they must not change.
- **New `tests/test_live_discover.py` (offline via `httpx.MockTransport`):**
  - `test_search_paginates_and_normalizes`: handler returns page 1 (2 places, `nextPageToken="t2"`)
    then page 2 (1 place, no token). Assert `search` returns 3 dicts; each has `place_id` (from
    `id`) and a string `name` (from `displayName.text`); assert `_raw_to_lead` accepts the first one
    and yields a `Lead` with the right `place_id`/`website`/`phone`.
  - `test_search_respects_field_mask_and_circle`: assert the outgoing request carried
    `X-Goog-FieldMask` and a `locationRestriction.circle` with `radius == min(radius_km,50)*1000`
    and the right center (inspect the request inside the MockTransport handler).
  - `test_search_cache_prevents_refetch`: pass a `JsonCache(tmp_path)`; call `search` twice with the
    same args; assert the transport handler ran only for the first call (counter), proving cost-zero
    re-runs.
  - `test_geocode_bbox_maps_viewport`: handler returns a canned Geocoding `viewport`; assert the
    `BBox` corners map southwest→min and northeast→max; second call hits cache (no 2nd handler call).
  - All use `httpx.Client(transport=httpx.MockTransport(handler))` injected via the new `client`
    param — **zero network**.

## Final checks (the gate — all must pass)
```
uv run pytest -q            # existing 14 + new live-client tests, all offline/green
uv run ruff check .
uv run mypy
```
Plus the **manual live spot-check** in step 8 (run twice; second run ~zero new API cost) — performed
by hand with a real key, **never** added to pytest.

## Definition of done
Live `geocode_bbox` + `search` implemented behind the unchanged `PlacesClient` Protocol; a live
Bengaluru point/radius run returns real, `place_id`-deduped dentists; per-`(tile,keyword)` and
per-`place_id` caching proven (second run ≈ zero new API calls); offline fixture pipeline and all
tests still green; `ruff`/`mypy` clean. Then flip Session 03 → ✅ (status box + README row) and
commit.

**Commit message:**
```
Live Google Places discovery (Stage 1): Text Search + Geocoding behind PlacesClient, cached
```

## Non-negotiables touched & how honored
- **Cost / LLM only in Stage 4:** this step adds **zero** LLM calls; discovery stays deterministic.
  Minimal field mask (no reviews) keeps Places billing low. (Reviews deferred — see Risks.)
- **Dedup on `place_id`:** unchanged in `discover.discover`; the live client only *feeds* it and
  must emit a `place_id` per result (`id`→`place_id` normalization). `test_discover.py` stays green;
  live spot-check confirms cross-keyword dedup.
- **Scraping/etiquette → caching:** every `(tile,keyword)` page and every place is cached by
  key/`place_id` so re-runs hit cache, not the network (rules.md "Re-runs hit cache"). Real
  `httpx.Client` timeout set; backoff on the pagination-token race.
- **Secrets never committed:** key read via `require_key("GOOGLE_MAPS_API_KEY")` from `.env`; never
  hardcoded, never printed, never sent in logs. Do **not** touch `.env`/`.env.example`. Pre-commit
  secret hook stays intact; `.cache/` is gitignored — don't stage it.
- **Legal:** untouched — discovery only; no dialing/outreach added.

## Risks / unknowns (research before assuming)
- **Pagination-token latency:** New-API `pageToken` may return `INVALID_ARGUMENT` if used too
  quickly after the previous page. Confirm during the live spot-check; the step-6 bounded retry
  handles it without ever sleeping in tests. Do **not** blind-`sleep` in the hot path.
- **`displayName` shape:** confirmed an object `{text,languageCode}` — normalization is mandatory or
  `Lead.name` (str) validation fails. Covered by the normalization test.
- **Reviews excluded by the minimal mask:** Stage 4 signal quality leans on review text, but
  `places.reviews` is a more expensive field and the session file's mask omits it. **Deferred** to
  Session 05/06 tuning (Place Details / reviews mask) — record the hook point; do not pull forward.
- **Text Search vs Nearby Search:** niche inputs are free-text keywords and we need pagination, so
  **Text Search (New)** is correct (Nearby New takes typed categories and lacks a page token).
- **API enablement/billing:** the live spot-check needs Geocoding + Places API (New) enabled on the
  key's project; a `REQUEST_DENIED`/403 means enablement, not a code bug — surface the message, don't
  silently swallow it.
