# Step 07C — Owner-name enrichment — implementation plan

> Source of truth: `docs/sessions/session-07-post-mvp.md`, **item C**. This is the worked-out *how*
> for that one backlog item. Session 07 is a **menu** ("pick one per session, in roughly this
> order"); this plan implements **only item C** and explicitly does **not** pull forward B (state
> tiling), D (SQLite), or E (opener variants).
>
> **Core-principle check (CLAUDE.md):** discovery/enrich is *commodity plumbing*. Enrichment is
> **Stage 3: deterministic, ZERO LLM, I/O-bound, robots-aware, cache-by-`place_id`**. This step must
> be **boring, correct, and cheap** — better on-site extraction of a decision-maker name, behind the
> same etiquette bar `LiveHttpClient` already meets. Do not gold-plate. The product value lives in
> Stage 4; do not borrow effort from it.

## Goal & scope
`Lead.owner_name` (`models.py:120`) already exists and Stage 3 already fills it with a single
homepage regex (`enrich._OWNER_RE`, `enrich.py:30`; applied in `enrich._extract`, `enrich.py:48`).
Item C is about going **beyond the homepage** for a best-effort decision-maker name — and taking a
**clear, documented position on off-site sources (LinkedIn)**. "Done" means: (1) Stage 3 extracts an
owner name from a small set of **on-site** pages (homepage **plus** about/team/contact), not just the
homepage; (2) extraction is more robust than the lone `Dr. X` pattern — it picks up "Founder/Owner/
Proprietor/Managing Director: <Name>" and "Meet Dr. <Name>" style phrasings, while **never
guessing** (no match ⇒ `owner_name=None`); (3) the new fetches obey the **exact same etiquette** as
today (robots.txt, rate-limit, concurrency cap, real User-Agent, **cache by `place_id`**); (4)
**off-site / LinkedIn lookup is explicitly declined** with the reasoning recorded in code comments
and this plan (see "Position on LinkedIn"); (5) **zero LLM** calls added; (6) the stage contract is
unchanged (`owner_name` already exists) — no new pydantic field; (7) the whole thing is covered by
**offline** fixture-backed tests with `uv run pytest -q` green and `ruff`/`mypy` clean.

## Position on LinkedIn / off-site lookups (the decision item C demands)
**Recommendation: stay on-site. Accept business-level contact when the site yields no name. Do NOT
add any LinkedIn / off-site people-search source in this step.** Argued:

- **ToS & fragility.** LinkedIn's User Agreement prohibits automated scraping/crawling; people-search
  pages sit behind auth/login walls and aggressive anti-bot. Honoring it would mean either (a) an
  authenticated session (a ToS violation and a credential/secret we will not introduce) or (b)
  evasion (rotating proxies, headless-browser fingerprint spoofing, CAPTCHA-solving) — **explicitly
  out of bounds** (CLAUDE.md §5; step07 Risks). There is no etiquette-compliant path to LinkedIn data
  here, so we don't build one — not even a stub.
- **Value vs. cost.** The product value is the Stage-4 opener grounded in an **observable signal**,
  not the owner's surname. A first-name handle ("Hi, is this Dr. Rao's clinic?") from the *site* is
  plenty; a fragile, ToS-fraught off-site lookup is gold-plating discovery — the one thing CLAUDE.md
  tells us not to do.
- **Correctness.** Off-site name matching (name + city across a directory) is stochastic and produces
  confident-but-wrong names. A wrong owner name in an opener is worse than no name. Better to return
  `None` and let the opener stay business-level.

The code will carry a short comment at the owner-extraction site stating "on-site only by design;
off-site/LinkedIn declined on ToS + fragility grounds — see Implementations/step07C." If a future
session ever revisits this, the sanctioned route is an **official LinkedIn/partner API with
credentials in `.env`**, never scraping — note it as a future refinement, not this step.

## Prerequisites (confirmed against code, not just the roadmap)
- ✅ **MVP + item A done**: Stage 3 live + fixture paths exist and pass offline. `enrich.enrich_lead`
  (`enrich.py:69`, sync/fixture) and `enrich.enrich_async` (`enrich.py:88`, live) share `_merge`
  (`enrich.py:62`) and `_extract` (`enrich.py:48`) so the two paths cannot drift.
- ✅ **`Lead.owner_name` already exists** (`models.py:120`, `str | None = None`) alongside `email`
  (`models.py:119`) and `site_text` (`models.py:121`). **No model change is needed** for item C.
- ✅ **Cache-by-`place_id` pattern is in place**: `enrich_lead` keys the enrich cache on
  `lead.place_id` (`cache.get("enrich", lead.place_id)` / `cache.set(...)`, `enrich.py:70`/`77`); the
  async twin does the same (`enrich.py:95`/`102`). Any additional page fetch must fold into this
  single cache entry so a warm run makes **zero** network calls (the `test_enrich_is_cached_no_refetch`
  invariant, `tests/test_enrich.py:32`).
- ✅ **Robots/etiquette seam is the `HttpClient`/`AsyncHttpClient` Protocol** (`clients.py:403`/`408`).
  `enrich_lead` already gates every fetch on `http.robots_allows(url)` (`enrich.py:73`); the live
  `LiveHttpClient` (`clients.py:444`) owns robots caching, the politeness `Semaphore` (`clients.py:473`),
  real User-Agent (`clients.py:457`), and backoff. New page fetches **reuse this same client** — no
  new transport, no new etiquette code.
- ✅ **Fixture HTTP pattern keeps tests offline**: `FixtureHttpClient` (`clients.py:420`) serves
  `fixtures/scrapes/<host>.html` keyed by hostname (`_host`, `clients.py:430`) and counts fetches
  (`fetch_count`, `clients.py:439`). Tests drive it via the `fixture_clients` conftest fixture
  (`tests/conftest.py:16`). **Caveat to design around:** `FixtureHttpClient` maps a URL to a file by
  **host only**, so `https://brightsmile.example` and `https://brightsmile.example/about` resolve to
  the *same* `brightsmile.example.html`. The plan accounts for this (see step 4).
- ✅ **`_OWNER_RE`** (`enrich.py:30`) is `\b(?:Dr\.?|Doctor)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})`
  — homepage-only, "Dr."-prefixed only. This is the thing being broadened.

## Position on scope: which pages, how far
- Fetch **at most 3 candidate on-site pages per lead** beyond the homepage: a small, fixed set of
  likely paths derived from the homepage URL: `/about`, `/about-us`, `/team`, `/contact` — **stop at
  the first that returns HTML and yields a name** (cheapest correct behavior; don't fetch all if the
  homepage already has the name). Hard cap the extra fetches so a lead never triggers an unbounded
  crawl. **No following arbitrary links, no sitemap crawl** — fixed candidate paths only.
- Every extra fetch goes through `http.robots_allows(...)` + `http.fetch(...)` exactly like the
  homepage, so robots/rate-limit/concurrency are honored automatically.

## Files to create / modify
| Path | Change |
|---|---|
| `src/leadscout/stages/enrich.py` | **Modify.** Broaden owner extraction: keep `_OWNER_RE`, add `_OWNER_LABEL_RE` (Owner/Founder/Proprietor/Managing Director/Principal Dentist `: Name`) and a "Meet Dr. <Name>" variant; add `_best_owner(text) -> str | None` that tries patterns in priority order and returns `None` on no match (never guess). Add `_candidate_pages(homepage_url) -> list[str]` (homepage + fixed about/team/contact paths, deduped). Keep `_extract`'s homepage outputs (`site_text`/`email`/`detected_tech`) intact; add a narrow owner-over-pages path threaded into **both** `enrich_lead` and `enrich_async`, folding all page text into the single per-`place_id` cache entry. Add the "on-site only; LinkedIn declined" comment. |
| `fixtures/scrapes/familydental.example.html` | **Create.** Homepage that names the owner via a **role label** ("Owner: Ramesh Gupta" / "Proprietor:"), no `Dr.` prefix — exercises the broadened regex. |
| `fixtures/scrapes/teamclinic.example.html` | **Create.** Landing copy with **no** owner name, name reachable only via the about/team fetch — exercises the multi-page path (see step 4 re: host-keying). |
| `fixtures/scrapes/plainclinic.example.html` | **Create.** A site with no extractable name — negative case (`owner_name is None`). |
| `tests/test_enrich.py` | **Extend.** New offline tests: label-style owner, "Meet Dr. <Name>", multi-page extraction, negative case, plus `_best_owner`/`_candidate_pages` unit tests. Existing `Dr. X` + tech + caching tests stay green. |
| `docs/sessions/session-07-post-mvp.md`, `docs/sessions/README.md` | Mark item C ✅ with a one-line outcome (07 stays ⬜ overall until the menu is exhausted; record C as ✅ within the file). |

> **Note:** `src/leadscout/models.py`, the live scraper in `clients.py`, `config.py`, `cli.py`,
> `pipeline.py`, and Stages 1/2/4 are **untouched** unless the fixture-page decision in step 4 forces a
> *minimal* `FixtureHttpClient` tweak. No new pydantic field. No new config.

## Implementation steps (ordered, each independently verifiable)

1. **Broaden the owner patterns (pure functions, no I/O).** In `enrich.py`, beside `_OWNER_RE`
   (`enrich.py:30`):
   - Keep `_OWNER_RE` as the "Dr./Doctor <Name>" pattern (don't regress the existing
     `test_enrich_extracts_email_owner_and_text` assertion `owner_name == "Anita Rao"`).
   - Add `_OWNER_LABEL_RE` matching a role label followed by a name, e.g.
     `\b(?:Owner|Founder|Co-?founder|Proprietor|Principal(?:\s+Dentist)?|Managing\s+Director|Director)\b\s*[:\-—]?\s+(?:Dr\.?\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})`.
   - Optionally a "Meet/Led by Dr. <Name>" variant, or let `_OWNER_RE` cover the `Dr.` case and the
     label regex cover the role-word case — keep the set **small**.
   - Add `_best_owner(text: str) -> str | None`: try patterns in priority order (explicit role label
     first, then `Dr.` pattern), return the captured name on the first hit, else `None`. **No match ⇒
     `None`. Never fabricate.** Strip a leading `Dr.` from the captured group so the stored name is a
     plain name (consistent with today's `"Anita Rao"`).
   *Verify:* unit tests calling `_best_owner` on inline strings (no fixtures, no I/O) return the
   expected names and `None` on junk.

2. **Decide and implement the multi-page candidate list.** Add
   `_candidate_pages(homepage_url: str) -> list[str]` returning the homepage first, then
   `urljoin(homepage, p)` for `("about", "about-us", "team", "contact")`, deduped and order-preserved.
   Pure function. *Verify:* unit test asserts the homepage is first and known paths are appended.

3. **Keep `_extract` homepage-only for its other outputs; add a narrow owner path.** `_extract`
   (`enrich.py:48`) returns `{site_text, email, owner_name, detected_tech}` from one HTML string. Keep
   that for the **homepage** so `email`/`detected_tech`/`site_text` continue to come from the homepage
   (do not let about/team pages pollute `site_text` or tech detection). Add a separate, narrow path
   that scans **additional** page texts **only for the owner name**: if the homepage `_extract` already
   produced an `owner_name`, keep it; otherwise call `_best_owner` over the extra pages until one
   returns a name. This bounds the new behavior to `owner_name`. *Verify:* `test_enrich_detects_booking_tech`
   (Practo on homepage) and the email assertion still pass.

4. **Resolve the fixture host-keying caveat (prefer no source change).** `FixtureHttpClient.fetch`
   keys by **host** (`clients.py:430`/`438`), so `/about` resolves to the same file as the homepage.
   Two options:
   - **(Preferred, zero `src` change to clients):** for the multi-page test, author the
     `teamclinic.example` fixture so the landing copy omits a name while a later
     `<section id="team">` in the **same file** includes "Owner: <Name>". `_best_owner` scans the
     fetched text; the multi-page *fetch* path still executes (a second `fetch` happens and is counted
     via `fetch_count`) because the homepage `_extract` produced no name, and the name is found in the
     returned (same-host) text. This proves both the broadened regex and the extra-fetch path without
     a distinct second file.
   - **(Fallback, minimal client tweak):** extend `FixtureHttpClient` to key by host + first path
     segment (e.g. `host__about.html`), backward-compatible (bare host still → `<host>.html`). Only do
     this if a test genuinely needs distinct per-path bodies.
   **Decision:** start with option 1; fall back to option 2 only if needed. Record which was used in
   the commit message.

5. **Thread multi-page fetch into both stage paths, folded into one cache entry.** In `enrich_lead`
   (`enrich.py:69`): when `cached is None` and the homepage `_extract` yields no `owner_name`, iterate
   `_candidate_pages(lead.website)[1:]`, and for each call `http.robots_allows(url)` then `http.fetch`
   (same gating as `enrich.py:73`), running `_best_owner` on the stripped text; stop at the first hit.
   Store the resolved `owner_name` **in the same `cached` dict** that gets `cache.set("enrich",
   lead.place_id, cached)` (`enrich.py:77`) — so a warm cache replays it with **zero** fetches. Mirror
   the identical logic in `enrich_async._one` (`enrich.py:94`) using `await http.robots_allows` /
   `await http.fetch`, keeping the two paths behaviorally identical (they already share `_merge`).
   *Verify:* the caching test (step 7) shows the warm run does not refetch.

6. **Bound the work + etiquette.** Cap extra fetches at the fixed candidate list (≤4 total pages incl.
   homepage); stop early on first name. No new concurrency/rate-limit code — the live `LiveHttpClient`
   `Semaphore` (`clients.py:473`) and per-host robots cache already bound it. Add the
   "on-site only; LinkedIn/off-site declined — ToS + fragility, see step07C" comment at the
   owner-extraction site. *Verify:* read-through; no `time.sleep`/transport added in `enrich.py`.

7. **Tests (offline).** See "Tests" below. *Verify:* `uv run pytest -q` green.

8. **Docs.** Mark item C ✅ in `docs/sessions/session-07-post-mvp.md` with a one-line outcome and note
   the README row. Write/update a handoff if used.

## Contracts & types
- **`Lead`** — **unchanged.** `owner_name: str | None` (`models.py:120`) already exists; this step only
  fills it more often/accurately. No new field, no shape change. Stage 3's output contract is stable.
- **`enrich.enrich` / `enrich.enrich_async`** — **signatures unchanged** (`enrich.py:82`/`88`): still
  `(leads, http, cache) -> list[Lead]`. The multi-page behavior is internal.
- **`HttpClient` / `AsyncHttpClient` Protocols** (`clients.py:403`/`408`) — **unchanged**; the new code
  only calls the existing `robots_allows` + `fetch`.
- **`_extract`** — internal helper; its public dict keys (`site_text`, `email`, `owner_name`,
  `detected_tech`) are preserved. New internals (`_best_owner`, `_candidate_pages`, `_OWNER_LABEL_RE`)
  are module-private.
- **No change** to `filter`, `score`, `discover`, `ScoreResult`, config, or CLI. **Stage 4 LLM
  untouched. Zero LLM added to Stage 3.**

## Tests (offline; pytest stays fully green, zero network)
All via `FixtureHttpClient` from the `fixture_clients` conftest fixture (`tests/conftest.py:16`) — **no
network**. Reuse the `_bright()` helper (`tests/test_enrich.py:7`).

- **Keep green (regression):**
  - `test_enrich_extracts_email_owner_and_text` (`tests/test_enrich.py:15`): `owner_name == "Anita Rao"`
    still holds — the homepage `Dr. Anita Rao` path must not regress.
  - `test_enrich_detects_booking_tech` (`tests/test_enrich.py:23`): Practo from the homepage unchanged.
  - `test_enrich_is_cached_no_refetch` (`tests/test_enrich.py:32`): a warm enrich still makes **zero**
    new fetches — now also covering the multi-page path (warm cache replays the resolved name).
- **Add — unit-level (pure, no fixtures):**
  - `test_best_owner_label_form`: `_best_owner("Owner: Ramesh Gupta. ...")` → `"Ramesh Gupta"`;
    `"Founded by Dr. Meera Iyer"` → `"Meera Iyer"`.
  - `test_best_owner_no_match_returns_none`: junk / generic copy → `None` (proves we never guess).
  - `test_candidate_pages`: homepage first; `/about`, `/about-us`, `/team`, `/contact` appended via
    `urljoin`; deduped.
- **Add — stage-level (fixture HTML):**
  - `test_enrich_extracts_owner_from_label` (`familydental.example`): homepage uses "Owner: <Name>" /
    "Proprietor: <Name>" (no `Dr.` prefix) → `out.owner_name` is the name. Proves the broadened regex.
  - `test_enrich_multipage_owner` (`teamclinic.example`): landing copy has **no** owner; the name is
    reachable via the about/team fetch → `out.owner_name` is found and `http.fetch_count` reflects the
    extra fetch. Proves multi-page extraction + that the extra fetch is gated/counted.
  - `test_enrich_owner_absent_is_none` (`plainclinic.example`): no extractable name → `out.owner_name
    is None` (business-level contact accepted, never fabricated).
- **No live calls anywhere.** No LinkedIn/off-site fetch is added to code or tests — there is nothing
  off-site to mock. Tests stay deterministic and offline.

## Final checks (the gate — all must pass)
```
uv run pytest -q          # existing enrich tests + new owner tests, fully offline
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
```
The offline smoke run must still succeed end-to-end on fixtures and now exercise the broadened
owner-extraction path. A **live** run remains operator-driven (real keys, real sites); it is **never**
in CI/pytest.

## Definition of done (adapted from session-07 item C)
Stage 3 produces a best-effort decision-maker `owner_name` from **on-site** pages (homepage +
about/team/contact), with extraction broadened beyond the lone `Dr. X` regex to role-label and
"Meet Dr." forms, returning `None` (business-level contact) when no name is reliably found — **never
guessing**. Off-site / LinkedIn lookup is **explicitly declined** on ToS + fragility grounds, with the
reasoning recorded in code and this plan; no off-site source, stub, or evasion is added. The new
fetches obey the existing etiquette (robots.txt, rate-limit, concurrency cap, real User-Agent) and
fold into the single per-`place_id` enrich cache so warm runs make zero network calls. The stage
contract is unchanged (`owner_name` already exists; no new field, no new config). Offline
fixture-backed tests cover label-form, multi-page, and negative cases; `uv run pytest -q` is green;
`ruff`/`mypy` clean; the offline smoke run passes. **Zero LLM** added. Roadmap item C marked ✅.

**Commit message:**
```
Session 07C: on-site owner-name enrichment (label + Dr. forms, about/team pages, cached, zero-LLM; LinkedIn declined on ToS)
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **Scraping etiquette (CLAUDE.md §5) — lead concern.** Every new page fetch goes through the existing
  `http.robots_allows(url)` gate (`enrich.py:73`) and `http.fetch`, so robots.txt, the politeness
  `Semaphore` (`clients.py:473`), real User-Agent (`clients.py:457`), and backoff all apply unchanged.
  Extra pages fold into the **same per-`place_id` cache entry** (`enrich.py:70`/`77`) so re-runs hit
  cache, not the network — the `test_enrich_is_cached_no_refetch` invariant holds. Fetches are bounded
  (≤4 fixed candidate pages, stop on first name) — no unbounded crawl. **No proxies, no CAPTCHA
  evasion, no login-wall bypass.**
- **ToS — lead concern.** **No LinkedIn / off-site scraping** is added — declined by design on ToS +
  fragility grounds (see "Position on LinkedIn"). The only sanctioned future route is an official
  API with `.env` credentials, explicitly out of this step.
- **Cost / LLM only in Stage 4 (CLAUDE.md §1, rules.md):** this is **Stage 3** work — **zero** LLM
  calls added. Owner extraction is pure deterministic regex over fetched HTML. The LLM still touches
  only Stage-2 survivors in Stage 4, unchanged.
- **Dedup on `place_id`:** unchanged; the enrich cache remains keyed on `place_id`.
- **Secrets:** none introduced (no LinkedIn token, no new key). Don't touch `.env`/`.env.example`; keep
  the pre-commit secret check. Don't stage `out/`/`.cache/`.
- **Config is data; typed contract + fixture test:** no new config needed; `owner_name` contract stays
  stable; the step is fixture-tested and runs end-to-end offline (definition of done).

## Risks / unknowns (research before any live step — never guess)
- **LinkedIn ToS & fragility (the decision driver).** LinkedIn prohibits automated scraping; pages are
  auth/anti-bot walled. There is **no etiquette-compliant scrape path** — hence declined. Do **not**
  revisit with proxies/headless evasion; the only legitimate future route is an official/partner API
  (credentials in `.env`), out of scope here.
- **False-positive owner names.** Broader regexes risk capturing non-owners (a quoted patient
  "Mr. Sharma", a staff dentist, a testimonial signature). Mitigations: prefer **explicit role labels**
  over bare `Dr.`; keep capture groups tight (2–3 capitalized tokens); **return `None` rather than a
  shaky match**. A wrong name in an opener is worse than none — bias to `None`.
- **Page-path guessing.** `/about`, `/team`, etc. are conventions, not guarantees; many sites won't have
  them (fetch returns nothing → fall back to business-level). That's acceptable and cheap. Don't crawl
  to discover pages.
- **Fixture host-keying** (`FixtureHttpClient` maps by host, `clients.py:430`). The multi-page test must
  be authored around this (step 4); if a test truly needs distinct per-path bodies, a minimal
  backward-compatible `FixtureHttpClient` key tweak is the only `src` change considered.
- **Live HTML brittleness.** Real about/team pages vary wildly; regexes will miss many. That's fine —
  best-effort, `None` otherwise. Lean on fixtures so tests are stable and a live miss is isolated.
- **Name normalization.** Decide whether to strip honorifics/suffixes ("Dr.", "BDS", "MDS"); keep it
  minimal (strip leading `Dr.`), don't over-engineer.

## What NOT to do (don't pull work forward)
No state-level tiling (item B / `discover.resolve_tiles` TODO). No SQLite cross-run store (item D). No
opener-format variants (item E). **No LinkedIn / off-site people-search source** — not even a stub —
and **no ToS evasion** (proxies, CAPTCHA-solving, login-wall bypass, headless fingerprint spoofing).
No new LLM calls anywhere (Stage 3 stays zero-LLM). No new pydantic field (`owner_name` already
exists). No stage-contract or signature changes beyond internal helpers. No live fetches in pytest.
Don't touch `.env`/`.env.example`, the pre-commit secret check, or Stage-4 enforcement.
