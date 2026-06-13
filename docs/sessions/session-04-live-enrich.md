# Session 04 — Live enrichment (scraping)

**Status:** ⬜ not started
**Goal:** make Stage 3 real. Replace `LiveHttpClient` stubs with a polite, robots-aware,
concurrent scraper. The extraction logic in `enrich.py` already works on HTML — this session is
about fetching that HTML correctly and considerately.
**Prereq:** Session 03 done (real candidates to enrich).

## Non-negotiable: scraping etiquette (.claude/rules.md)
- Respect `robots.txt` per host (cache the parsed rules per host).
- Real `User-Agent` (already defined on `LiveHttpClient`).
- Rate-limit + **concurrency cap via asyncio semaphore** (`RunConfig.max_concurrency`).
- Back off on errors; timeout per request (`RunConfig.request_timeout_s`).
- **Cache every fetch by `place_id`** (already wired through `JsonCache` in `enrich_lead`).

## Steps
1. Implement `LiveHttpClient.robots_allows` → fetch & parse `robots.txt`, honor it (cache result).
2. Implement `LiveHttpClient.fetch` → `httpx` GET with UA + timeout + retry/backoff; return HTML.
3. Decide sync vs async: `enrich.enrich` is currently a sequential loop. To go concurrent, add an
   async path (gather with a semaphore) while keeping the cached, deterministic fixture path for
   tests. Don't break the `HttpClient` Protocol the tests rely on.
4. Fetch homepage + try `/about` and `/contact`; feed combined text to the existing `_extract`.
5. Reviews: pull a few recent + low-star reviews (complaints carry the pain signals). Source them
   from Places details (place details `reviews` field) rather than scraping Google Maps HTML.

## Verify
- Live enrich on ~5 real candidates extracts emails/owner/tech where present; robots-disallowed
  hosts are skipped, not scraped.
- Second run hits cache (no refetch) — assert via `fetch_count` analog or cache presence.
- Offline tests still green.

## Definition of done
Polite concurrent scraping populates email/owner/site_text/detected_tech on real candidates,
robots respected, caching proven, offline tests green. Commit. Update roadmap.
