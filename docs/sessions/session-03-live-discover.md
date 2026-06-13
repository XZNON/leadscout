# Session 03 — Live discovery (Google Places)

**Status:** ✅ done
**Goal:** make Stage 1 real. Replace `LivePlacesClient` stubs in `clients.py` with live Google
Places API (New) + Geocoding, keeping the same `PlacesClient` interface so nothing downstream or
the tests change.
**Prereq:** Session 02 green. `GOOGLE_MAPS_API_KEY` in `.env`.

## Research first (don't guess the API)
- Confirm current Places API (New) endpoints: Text Search / Nearby Search, the field mask header,
  and **pagination** (next-page token; ~3 pages × 20 = ~60 cap). Verify the radius cap (~50 km).
- Confirm Geocoding API returns a `viewport` (bbox) for a city query.
- Note billing: Places charges per request + per field mask. Keep the field mask minimal
  (place_id, name, type, rating, userRatingCount, website, phone, businessStatus).

## Steps
1. Implement `LivePlacesClient.geocode_bbox` → call Geocoding, return the viewport as `BBox`.
2. Implement `LivePlacesClient.search` → Nearby/Text Search at `(lat,lng,radius)`, **paginate
   fully**, return raw dicts shaped for `discover._raw_to_lead`.
3. **Cache place details by `place_id`** via `JsonCache` (namespace `"places"`) so re-runs and
   detail lookups don't re-bill. Search-result pages can also be cached by `(tile,keyword)`.
4. Handle the 60-cap: if a `(tile,keyword)` hits the cap, log it; tile subdivision / keyword
   narrowing can stay a TODO for now but record where it'd hook in (`discover.resolve_tiles`).
5. Keep `internationalPhoneNumber` populated — Stage 2 contactability depends on phone at filter
   time (email isn't known until Stage 3).

## Verify
- A small live run against a tight `point+radius` (e.g. `examples/bengaluru.yaml`) returns real
  deduped dentists. Spot-check `place_id` dedup across keywords.
- **Tests stay offline and green** — do not let live calls leak into pytest.
- Re-run the same geo: second run hits cache, near-zero new API cost.

## Definition of done
Live discovery returns real, deduped leads for a Bengaluru point/radius; caching proven; offline
tests still green; cost-per-rerun ~0. Commit. Update roadmap.
