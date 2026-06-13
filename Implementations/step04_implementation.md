# Step 04 — Live enrichment (robots-aware concurrent scraper) — implementation plan

> Source of truth: `docs/sessions/session-04-live-enrich.md`. This file is the worked-out *how* for
> that one step. **Do not pull work forward** from Sessions 05–07 (no live LLM, no JustDial/IndiaMART,
> no owner-enrichment-via-LinkedIn). This step makes **Stage 3 only** real: replace the two
> `LiveHttpClient` `NotImplementedError` stubs with a polite, robots-aware, concurrent `httpx`
> scraper. The HTML extraction logic in `enrich.py` (`_extract`, `_strip_html`) **already works and
> does not change** — this session is about *fetching that HTML correctly and considerately*.

## Goal & scope
Make Stage 3 real. Implement `LiveHttpClient.robots_allows` and `LiveHttpClient.fetch` in
`src/leadscout/clients.py` as a real scraper: per-host `robots.txt` fetched/parsed/honored and cached
per host; a real `User-Agent` (already on the class); a **concurrency cap via `asyncio.Semaphore`**
sized by `RunConfig.max_concurrency`; a per-request timeout (`RunConfig.request_timeout_s`) and
bounded retry/backoff on transient errors. The existing `JsonCache` keyed by `place_id` (already wired
through `enrich_lead`) makes second runs hit cache, not the network. "Done" means: a live run on ~5
real Bengaluru dental candidates populates `email` / `owner_name` / `site_text` / `detected_tech`
where present; robots-disallowed hosts are **skipped, not scraped**; a second run does **zero**
re-fetches (cache hits); and **all offline tests stay green with no live calls** — the live async
client is exercised purely through an injected `httpx.MockTransport`. Reviews-from-Places-Details
(session step 5) is **out of the gating DoD** and deferred (see Risks) because it touches the Stage-1
`PlacesClient` contract; this step stays focused on the scraper.

## Prerequisites (confirmed)
- ✅ Session 03 done (`b0e283a`): `LivePlacesClient.geocode_bbox`/`.search` real, behind the unchanged
  `PlacesClient` Protocol. There are now real candidates with `website` set to enrich.
- ✅ Baseline green right now: `uv run pytest -q` → **18 passed**; `ruff`/`mypy` clean.
- ✅ `enrich.enrich_lead` already: checks `cache.get("enrich", place_id)` → on miss, gates on
  `lead.website and http.robots_allows(...)`, calls `http.fetch(...)`, runs `_extract`, writes
  `cache.set("enrich", place_id, ...)`. The **caching and extraction are already correct** — only the
  live fetch/robots are stubs.
- ✅ `RunConfig.max_concurrency = 5` and `request_timeout_s = 10.0` already exist (`config.py`).
- ✅ `httpx>=0.27` and `selectolax>=0.3.21` already installed. `httpx.MockTransport` works with both
  `httpx.Client` and `httpx.AsyncClient`, so offline tests need **no new dependency** and **no
  pytest-asyncio** (drive coroutines with `asyncio.run(...)` inside ordinary sync test functions).
- ✅ `urllib.robotparser.RobotFileParser` (stdlib) handles parsing — **no new dep** for robots.
- ⚠️ Live spot-check needs `GOOGLE_MAPS_API_KEY` in `.env` (to produce candidates). Owner-managed; do
  **not** touch `.env`/`.env.example`. Tests never need it.

## Key design decision — sync fixture path stays; live path is async (recommended)
The `HttpClient` Protocol (`robots_allows`/`fetch`, **sync**) and `enrich.enrich`/`enrich_lead`
(**sync, sequential**) are what the existing tests use via `FixtureHttpClient`. The session file's
non-negotiable is explicit: *"concurrency cap via `asyncio` semaphore (`RunConfig.max_concurrency`)"*
and *"add an async path … while keeping the cached, deterministic fixture path for tests. Don't break
the `HttpClient` Protocol the tests rely on."*

**Therefore:** leave the sync Protocol + sync `enrich`/`enrich_lead` + all existing tests **untouched**
(fixtures are synchronous and cache-backed). Add a **parallel async path** used only on live runs:
- `LiveHttpClient` becomes async (`async def robots_allows`, `async def fetch`) over a shared
  `httpx.AsyncClient`, satisfying a new small `AsyncHttpClient` Protocol.
- A new `enrich.enrich_async(leads, http, cache)` gathers per-lead coroutines; the politeness/
  concurrency cap lives **inside** `LiveHttpClient` via one `asyncio.Semaphore(max_concurrency)`
  (matching the existing `enrich.py` docstring: *"Concurrency/politeness cap lives in the live
  HttpClient; the fixture path is synchronous"*).
- `pipeline.run_pipeline` branches on `cfg.offline`: offline → sync `enrich`; live →
  `asyncio.run(enrich_async(...))`. The offline branch (what every test drives) is byte-for-byte the
  current behavior.

## Files to create / modify
- `src/leadscout/clients.py` — **modify.** Add `AsyncHttpClient` Protocol (async `robots_allows`/
  `fetch`). Rewrite `LiveHttpClient` to be async over an injectable `httpx.AsyncClient` (test seam),
  owning a per-host robots cache `dict[str, RobotFileParser | None]` and an
  `asyncio.Semaphore(max_concurrency)`. Implement `robots_allows` (fetch+parse+cache robots.txt,
  honor it) and `fetch` (GET under semaphore, UA, timeout, bounded retry/backoff). Imports:
  `asyncio`, `from urllib.parse import urlsplit`, `from urllib.robotparser import RobotFileParser`.
  Keep `FixtureHttpClient` and the sync `HttpClient` Protocol **unchanged**.
- `src/leadscout/stages/enrich.py` — **modify (add, don't replace).** Add
  `async def enrich_async(leads, http, cache)` that mirrors `enrich_lead` per-lead logic but `await`s
  `http.robots_allows`/`http.fetch` and `asyncio.gather`s across leads. `_extract`/`_strip_html`/
  `enrich`/`enrich_lead` stay **exactly as they are**. Factor the shared "cached → update fields"
  merge into a tiny helper (`_merge(lead, cached)`) reused by both paths to avoid drift.
- `src/leadscout/pipeline.py` — **modify (wiring only).** `import asyncio`; branch the Stage-3 call on
  `cfg.offline` (sync `enrich` vs `asyncio.run(enrich_async(...))`). Broaden the `http` param type to
  `HttpClient | AsyncHttpClient`.
- `src/leadscout/cli.py` — **modify (wiring only).** Construct
  `LiveHttpClient(timeout_s=cfg.request_timeout_s, max_concurrency=cfg.max_concurrency)`; widen the
  local `http` annotation to `HttpClient | AsyncHttpClient`. Offline branch unchanged.
- `tests/test_live_enrich.py` — **create.** Offline-only tests via `httpx.MockTransport` +
  `httpx.AsyncClient`, driven with `asyncio.run(...)` (no pytest-asyncio). See **Tests**.
- *(create on run, gitignored)* `.cache/enrich/*.json` — cache artifacts. Don't stage.
- `docs/sessions/session-04-live-enrich.md` & `docs/sessions/README.md` — flipped to ✅ **only after**
  the live spot-check + gate pass (done by the implementing session, **not** this planning one).

## Implementation steps (ordered, each independently verifiable)
1. **`AsyncHttpClient` Protocol.** Add alongside the sync `HttpClient`:
   `async def robots_allows(self, url: str) -> bool` and `async def fetch(self, url: str) -> str | None`.
   *Verify:* `mypy` sees `LiveHttpClient` as structurally satisfying it after step 3.
2. **`LiveHttpClient.__init__`.** Signature
   `(self, timeout_s=10.0, max_concurrency=5, max_retries=2, client: httpx.AsyncClient | None = None)`.
   Store `self._client = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=True,
   headers={"User-Agent": self.USER_AGENT})`, `self._sem = asyncio.Semaphore(max_concurrency)`,
   `self._robots: dict[str, RobotFileParser | None] = {}`, `self._max_retries`. The `client` param is
   the **offline test seam** (inject `httpx.AsyncClient(transport=httpx.MockTransport(handler))`); not
   part of any Protocol. *Verify:* constructs without network.
3. **`robots_allows(url)`** (async). Parse host/scheme with `urlsplit`. On first sight of a host, GET
   `{scheme}://{host}/robots.txt` via `self._client` and cache a `RobotFileParser` (or sentinel) under
   the host. Policy (RFC-9309-ish, defensible): `2xx` → `rp.parse(resp.text.splitlines())`; `404/410/
   other 4xx` → `rp.parse([])` (allow-all, no rules); `5xx` or network error (`httpx.HTTPError`) →
   cache `None` and treat as **disallow** (be polite when robots is indeterminate). Return
   `rp.can_fetch(self.USER_AGENT, url)`, or `False` if the cached value is `None`. *Verify:* unit test
   below — disallowed path returns `False`, allowed returns `True`, second call doesn't re-hit handler.
4. **`fetch(url)`** (async). `async with self._sem:` then loop up to `max_retries + 1`: `await
   self._client.get(url)`; on `resp.is_success` return `resp.text`; on `429`/`5xx` (or
   `httpx.HTTPError`) and attempts remain, `await asyncio.sleep(0.5 * 2**attempt)` and retry; otherwise
   return `None`. The semaphore is what bounds in-flight GETs to `max_concurrency`. *Verify:* fetch test
   + retry test (with `asyncio.sleep` patched to no-op) below.
5. **`enrich.enrich_async(leads, http, cache)`.** Define an inner `async def _one(lead)` replicating
   `enrich_lead`: `cache.get("enrich", place_id)`; on miss build `{}`, and **if** `lead.website and
   await http.robots_allows(lead.website)` then `html = await http.fetch(lead.website)` and
   `cached = _extract(html)` when html truthy; `cache.set("enrich", place_id, cached)`. Return
   `_merge(lead, cached)`. Then `return list(await asyncio.gather(*(_one(l) for l in leads)))`.
   Extract `_merge(lead, cached) -> Lead` (the `{k:v for k,v in cached.items() if v not in (None,[],"")}`
   + `lead.model_copy(update=...)`) and call it from `enrich_lead` too. *Verify:* offline async test
   populates fields identically to the sync path on the same fixture HTML.
6. **Pipeline branch.** In `run_pipeline`, replace the single `enrich` call with:
   `enriched = s_enrich.enrich(candidates, http, cache) if cfg.offline else
   asyncio.run(s_enrich.enrich_async(candidates, http, cache))`. Widen the param type to
   `HttpClient | AsyncHttpClient`; `cast`/annotate locally so `mypy` is satisfied in each branch.
   *Verify:* `test_pipeline.py` (offline) unchanged and green.
7. **CLI wiring.** Build `LiveHttpClient(timeout_s=cfg.request_timeout_s,
   max_concurrency=cfg.max_concurrency)` in the live branch; widen the `http` annotation. Offline branch
   unchanged. *Verify:* `leadscout run --offline ...` still works end-to-end.
8. **Live spot-check (manual, not in CI).** With a real key in `.env`, run a tight Bengaluru point/geo
   on ~5 candidates. Confirm: emails/owner/tech extracted where present; a robots-disallowed host is
   skipped (log/empty enrich, no GET to the page); a **second** run re-fetches nothing (cache hit) —
   inspect `.cache/enrich/*.json`. **Never** add this command to pytest.

## Contracts & types (touched vs. stable)
- **Stable (do not change):** sync `HttpClient` Protocol, `FixtureHttpClient`, `enrich.enrich` /
  `enrich_lead` behavior, `_extract` / `_strip_html`, `Lead` model (stage-3 fields `email`,
  `owner_name`, `site_text`, `detected_tech`, `reviews` already exist — fill them, don't reshape),
  `PlacesClient`, `LlmClient`, `PipelineResult`, all Stage-1/2/4 code.
- **Touched (implementation detail / additive only):** new `AsyncHttpClient` Protocol; `LiveHttpClient`
  internals go async (was an unimplemented stub — no caller depends on its sync-ness); new
  `enrich.enrich_async` + private `_merge`; `run_pipeline`/CLI `http` param widened to
  `HttpClient | AsyncHttpClient`. Any change beyond these to a shared contract is out of scope — stop
  and reassess.

## Tests (existing stay green; one new file, all offline)
- **Keep green, unchanged:** `tests/test_enrich.py` (sync fixture path — extraction, tech detection,
  cache-no-refetch), `tests/test_pipeline.py` (offline → sync branch), and the other four files. They
  use `FixtureHttpClient` + sync `enrich`; they must not change.
- **New `tests/test_live_enrich.py` (offline via `httpx.MockTransport` + `AsyncClient`, no
  pytest-asyncio — wrap each in `asyncio.run`):**
  - `test_robots_allows_parses_and_caches`: handler serves `/robots.txt` with `User-agent: *` /
    `Disallow: /private`. Assert `robots_allows("https://h/")` is `True`, `robots_allows("https://h/private")`
    is `False`, and the robots.txt was fetched **once** (handler counter) across both calls.
  - `test_robots_5xx_or_error_disallows`: handler 503s `/robots.txt`; assert `robots_allows` → `False`
    (conservative). A `404` variant → `True` (allow-all).
  - `test_fetch_returns_html_and_extracts`: handler serves a homepage with an email + `Dr. Anita Rao`
    + a `Practo` marker; run `enrich_async([lead], http, JsonCache(tmp_path))`; assert `email`,
    `owner_name`, `site_text`, and `"Practo" in detected_tech` populated (proves the live path feeds
    `_extract` correctly — same asserts as the sync test, different fetch).
  - `test_robots_disallow_skips_fetch`: robots disallows the page; assert via a fetch-counter on the
    handler that the **page** URL was never requested and the lead's enrich fields stay empty.
  - `test_fetch_retries_then_gives_up`: monkeypatch `asyncio.sleep` to a no-op; handler returns `503`
    every time; assert `fetch` returns `None` after `max_retries + 1` attempts (assert attempt count).
    A `404` variant returns `None` with **no** retry.
  - `test_enrich_async_cached_no_refetch`: run `enrich_async` twice with the same `JsonCache(tmp_path)`;
    assert the page handler ran only on the first run (cost-zero re-runs).
  - *(optional smoke)* `test_semaphore_wired`: assert `LiveHttpClient(max_concurrency=3)._sem._value == 3`.
  - All inject `httpx.AsyncClient(transport=httpx.MockTransport(handler))` via the `client` param —
    **zero network, zero sleeps.**

## Final checks (the gate — all must pass)
```
uv run pytest -q            # existing 18 + new live-enrich tests, all offline/green
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline   # smoke: offline path unchanged
```
Plus the **manual live spot-check** (step 8: run twice; second run re-fetches nothing) — by hand with a
real key, **never** added to pytest.

## Definition of done
Polite, concurrent scraping populates `email`/`owner_name`/`site_text`/`detected_tech` on real
candidates; `robots.txt` respected (disallowed hosts skipped); caching proven (second run = zero
re-fetches); offline tests green; `ruff`/`mypy` clean. Then flip Session 04 → ✅ (status box + README
row) and commit.

**Commit message:**
```
Live enrichment (Stage 3): robots-aware concurrent httpx scraper behind AsyncHttpClient, cached
```

## Non-negotiables touched & how honored
- **Cost / LLM only in Stage 4:** this step adds **zero** LLM calls; Stage 3 stays deterministic.
- **Scraping etiquette:** `robots.txt` fetched, parsed, cached per host and honored (disallow →
  skip); real `User-Agent` on every request; `asyncio.Semaphore(max_concurrency)` caps concurrency;
  `request_timeout_s` per request; bounded exponential backoff on `429`/`5xx`/network errors. Every
  fetch cached by `place_id` so re-runs hit cache, not the network. *Don't get the key/IP blocked.*
- **Dedup on `place_id`:** untouched (Stage 1); enrich keys cache by `place_id`.
- **Secrets never committed:** no new secret; `GOOGLE_MAPS_API_KEY` read via `require_key` from `.env`
  only for the live spot-check. Don't touch `.env`/`.env.example`. Pre-commit secret hook stays; don't
  stage `.cache/`.
- **Legal:** untouched — scraping public business sites for context only; no dialing/outreach added.

## Risks / unknowns (research before assuming)
- **Reviews (session step 5) deferred — and why:** the session lists "pull a few recent/low-star
  reviews from **Places Details**," but the Stage-1 field mask deliberately omits `places.reviews`
  (Session 03 deferred it as the more expensive field), and the **DoD does not list `reviews`**.
  Fetching reviews means a new Place Details call → a change to the `PlacesClient` contract, i.e.
  Stage-1 scope. **Recommendation:** keep Session 04 to the scraper; record the hook (extend the
  Places mask or add `LivePlacesClient.place_details_reviews`) and do it in Session 05/06 tuning where
  review-driven signal quality is actually exercised. Flag for the implementer to confirm before
  pulling it in.
- **`robots.txt` indeterminate policy:** `5xx`/network error → **disallow** (conservative). Confirm
  this matches the owner's appetite during the spot-check; if too strict for flaky hosts, relax to
  allow-with-log — but default safe.
- **Redirects / non-HTML / huge pages:** `follow_redirects=True`; `_extract` already truncates
  `site_text` to 4000 chars. If a site returns non-HTML (PDF), `_strip_html`'s regex fallback yields
  junk but won't crash — acceptable for MVP; note it.
- **Per-host robots race:** two leads on the same host may both fetch robots.txt before the cache
  populates. Harmless (idempotent); add a per-host `asyncio.Lock` only if it shows up. Don't
  over-engineer.
- **`httpx.AsyncClient` lifecycle:** `asyncio.run(enrich_async(...))` runs one event loop per pipeline
  call; the injected/owned `AsyncClient` is created in `__init__` (sync) and used within that loop —
  fine for a single run. Don't reuse a `LiveHttpClient` across multiple `asyncio.run` calls in one
  process without re-checking the client's loop binding.

## What NOT to do (don't pull work forward)
- No live LLM (Session 05), no JustDial/IndiaMART or state tiling (Session 07), no tile subdivision,
  no live review-fetch (deferred above). Stage-4 and Stage-1 contracts stay frozen.
