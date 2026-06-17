# Step 07 — JustDial / IndiaMART source adapters — implementation plan

> Source of truth: `docs/sessions/session-07-post-mvp.md`, **item A**. This is the worked-out *how*
> for that one backlog item. Session 07 is a **menu** ("pick one per session, in roughly this
> order"); this plan implements **only item A** and explicitly does **not** pull forward B (state
> tiling), C (owner enrichment), D (SQLite), or E (opener variants).
>
> **Core-principle check (CLAUDE.md):** discovery is *commodity plumbing*. This step must be
> **boring, correct, and cheap** — new source clients feeding the **same** dedup, normalized into the
> existing `Lead` shape with the right `source` tag. **Zero LLM** (Stage 1 only). Do not gold-plate.

## Goal & scope
Add **additional discovery sources** (JustDial, and IndiaMART as the same pattern) that feed the
**same** Stage-1 dedup step, so coverage improves where Google Places thins out for tier-2/3 Indian
shops (idea.md §7). "Done" means: each source has a **live adapter** (network) and a **fixture
adapter** (offline, deterministic) behind a small `SourceClient` interface; their results are
normalized into the common `Lead` shape with `source="justdial"` / `"indiamart"`; results merge into
`discover.discover`'s existing `place_id` dedup **plus** a best-effort cross-source phone dedup so the
same business pulled from two sources collapses to one row (Google Places staying canonical); sources
are **toggleable as data** (niche YAML), default Places-only so existing runs are unchanged; and the
whole thing is covered by **offline** fixture-backed tests with `uv run pytest` green and
`ruff`/`mypy` clean. No new LLM calls, no stage-contract churn beyond the discovery signature.

## Prerequisites (confirmed against code, not just the roadmap)
- ✅ **MVP (Sessions 01–06) done and verified**: no `NotImplementedError` in `src/`; all three live
  clients real (`clients.py`); `uv run pytest -q` → **35 passed**, fully offline.
- ✅ **The data model already anticipates this**: `models.py:14`
  `Source = Literal["google_places", "justdial", "indiamart"]` — the `Lead.source` field
  (`models.py:101`) already accepts the new tags. **No model change is needed for the tag.**
- ✅ **Stage 1 is the only stage touched**: `discover.discover(geo, niche, client)` (`discover.py:82`)
  owns the loop and the `by_id: dict[str, Lead]` dedup; `_raw_to_lead` (`discover.py:60`) normalizes a
  raw dict → `Lead`. The pipeline calls it once (`pipeline.py:46`). Stages 2–4 are untouched.
- ✅ **Client/test-seam pattern is established**: every live client takes an injectable transport
  (`httpx.Client(transport=httpx.MockTransport(...))`) so pytest never touches the network
  (`LivePlacesClient.__init__`, `clients.py:82`); `load_fixture_clients` (`clients.py:467`) wires the
  offline trio. The new sources follow this exact pattern.
- ⚠️ **ToS / robots / anti-bot is an open risk** — see Risks. The adapter code lands behind the
  interface and is **fully tested offline against recorded fixtures**; whether/how hard to run it live
  is an operator decision, not a code-correctness gate.

## Design decision required before coding — cross-source dedup key
Google Places dedup is on `place_id`. **JustDial/IndiaMART listings have no Google `place_id`.** Two
sub-problems, decide both up front:

1. **In-source uniqueness / `Lead.place_id` value.** `Lead.place_id: str` is required and is the dedup
   key. **Decision (recommended):** synthesize a namespaced id from the source's own listing id —
   `f"justdial:{listing_id}"`, `f"indiamart:{listing_id}"`. Deterministic, collision-free across
   sources, and keeps `place_id` meaningful as "the unique key for this row."
2. **Cross-source dedup (same business from Places *and* JustDial).** They never share a `place_id`,
   so a secondary key is needed. **Decision (recommended, keep it deterministic & cheap):** normalize
   the phone to **last-10-digits** (`_norm_phone`) and dedup on that as a fallback key. **Google
   Places wins as canonical** (richer, structured) — a JustDial/IndiaMART lead whose normalized phone
   already exists is dropped (or merged to fill only null fields; see step 4). Businesses with no
   phone fall back to `place_id` only (no cross-source merge — acceptable, they're rare and Stage-2
   drops phone-less leads anyway). **Name+pincode fuzzy matching is explicitly out of scope** — too
   stochastic for "boring plumbing"; note it as a future refinement.

This plan assumes both recommendations. They touch only `discover.py` (merge logic) and the new
normalizers — **no new pydantic field**.

## Files to create / modify
| Path | Change |
|---|---|
| `src/leadscout/clients.py` | **Add** `SourceClient` Protocol (`source_name: Source`, `discover(geo, niche) -> list[dict]`); add `JustDialClient` (live) + `FixtureJustDialClient` (offline), and the IndiaMART pair following the same shape; extend the fixture loader (new `load_fixture_sources` or widen `load_fixture_clients`). |
| `src/leadscout/stages/discover.py` | **Modify** `discover` to merge extra `SourceClient`s into the same `by_id` dedup; add `_norm_phone` + a per-source `_raw_to_lead` path (or pass `source` into `_raw_to_lead`); add cross-source phone-dedup. **Keep Places tiling exactly as-is.** |
| `src/leadscout/config.py` | **Add** a data-driven source toggle: `NicheSpec.sources: list[Source]` (default `["google_places"]`) **or** a `RunConfig` field — pick one (see step 1). Config-as-data: enabling a source = editing YAML, no code change. |
| `src/leadscout/models.py` | **Likely no change** (Source literal already present). *Only* if the toggle lives on the niche: add `NicheSpec.sources: list[Source] = ["google_places"]`. |
| `src/leadscout/cli.py` | **Modify** the live branch (`cli.py:59-68`) to construct enabled live source clients; the `offline` branch wires the fixture sources. Pass the source list into `run_pipeline`/`discover`. |
| `src/leadscout/pipeline.py` | **Modify** `run_pipeline` signature/call (`pipeline.py:46`) to thread the extra sources into `s_discover.discover`. |
| `fixtures/justdial.json`, `fixtures/indiamart.json` | **Create** — recorded/representative listings (incl. one whose phone collides with a `fixtures/places.json` entry, to exercise cross-source dedup). |
| `tests/test_sources.py` | **Create** — offline tests for normalization, synthetic `place_id`, source tagging, phone-dedup, and toggle behavior. |
| `tests/test_discover.py` | **Extend** — multi-source merge + dedup assertions if not in the new file. |
| `examples/dental.yaml` | **Edit (data)** — add `sources: [google_places, justdial]` to demonstrate the toggle (keep `indiamart` off by default; see risks). |
| `docs/sessions/session-07-post-mvp.md`, `docs/sessions/README.md` | Mark item A done / note progress (07 stays ⬜ overall until the menu is exhausted — record A as ✅ within the file). |

## Implementation steps (ordered, each independently verifiable)
1. **Pick the toggle home (config-as-data).** Add `sources: list[Source] = ["google_places"]` to
   `NicheSpec` (recommended — sources are a *niche/geo* concern: which directories cover this vertical
   in this country). Validate entries against the `Source` literal. Default keeps every existing run
   Places-only → **no behavior change** until a YAML opts in. *Verify:* `load_niche` on the current
   `dental.yaml` still parses; a bad source value raises.
2. **Define the `SourceClient` Protocol** in `clients.py` (above the Places section):
   ```python
   class SourceClient(Protocol):
       source_name: Source
       def discover(self, geo: GeographyInput, niche: NicheSpec) -> list[dict]: ...
   ```
   Returns **raw dicts** (not `Lead`) so `discover._raw_to_lead` stays the single normalization choke
   point. *Verify:* `mypy` sees `LivePlacesClient`-style impls satisfy it (structural).
3. **Fixture adapters first (TDD-friendly, offline).** Implement `FixtureJustDialClient` /
   `FixtureIndiaMartClient` reading `fixtures/justdial.json` / `fixtures/indiamart.json` (mirror
   `FixturePlacesClient`, `clients.py:39`). Author the fixtures: a handful of listings each, with
   `listing_id`, `name`, `phone`, `address`, `website?`, `category`. Include **one JustDial listing
   whose phone equals a `fixtures/places.json` business** to prove cross-source dedup.
4. **Multi-source merge + dedup in `discover.discover`.** Keep the Places tiling loop intact. After it,
   loop enabled extra sources, normalize each raw via `_raw_to_lead(raw, source=...)`, and insert into
   `by_id` with two gates: (a) skip if `place_id` already present (in-source dedup, unchanged); (b)
   skip if `_norm_phone(lead.phone)` matches an already-collected lead (**cross-source**, Places
   canonical — iterate Places first). Implement `_norm_phone(s) -> str|None` (strip non-digits, take
   last 10, return `None` if <10). Generalize `_raw_to_lead` to set `source` and accept the synthetic
   `place_id` for non-Places sources. *Verify with the unit tests in step 8.*
5. **Live `JustDialClient`.** Implement `discover(geo, niche)` honoring etiquette (this is the risky
   part — see Risks; **confirm robots.txt + ToS before any live fetch**): injectable `httpx.Client`
   seam; real User-Agent; rate-limit / concurrency cap; **cache by synthetic `place_id`** (reuse
   `JsonCache`, namespace `"justdial"`) so re-runs hit cache; back off on errors. Parse listings →
   raw dicts. Keep the parser tolerant (sites change) and **small**.
6. **Live `IndiaMartClient`** — same pattern. *Flag:* IndiaMART is a **B2B supplier/manufacturer**
   directory; for the clinic ICP it may yield little. Implement the adapter for parity but leave it
   **off by default** in `dental.yaml`; let the operator enable per-niche. Don't over-invest.
7. **Wire CLI + pipeline.** `cli.py` live branch builds the enabled live source clients from
   `niche_spec.sources` (Places always available; others gated by the list and by key/availability);
   offline branch builds the fixture sources. Thread the extra-source list through `run_pipeline`
   (`pipeline.py:46`) into `s_discover.discover(geo, niche, places, extra_sources=...)`. Keep the
   default empty so existing callers/tests are source-compatible.
8. **Tests (offline).** Create `tests/test_sources.py` (and extend `tests/test_discover.py`):
   normalization (raw → `Lead` with correct `source` + `justdial:`/`indiamart:` `place_id`),
   source-tagging, cross-source **phone dedup** (the colliding fixture collapses to one row, Places
   canonical), **toggle** (sources off ⇒ identical to today's output), and `_norm_phone` edge cases
   (spaces, `+91`, `<10` digits → `None`). All via fixture clients — **no network**.
9. **Docs.** Update `docs/sessions/session-07-post-mvp.md` (mark item A ✅ with a one-line outcome) and
   the README row note. Write/update a handoff if used.

## Contracts & types
- **`Lead`** — unchanged shape; `source` already typed via the `Source` literal. New `place_id`
  *values* are namespaced strings (`justdial:…`) — still a `str`, contract intact.
- **`NicheSpec`** — **add** `sources: list[Source] = ["google_places"]` (the one intentional schema
  add; backward-compatible default).
- **New `SourceClient` Protocol** — structural interface mirroring `PlacesClient`'s role; live +
  fixture impls. `PlacesClient` stays as-is (it has tiling-specific `geocode_bbox`/`search`); it is
  *adapted into* the merge as the canonical first source, not forced under `SourceClient`.
- **`discover.discover`** — signature gains an optional `extra_sources: list[SourceClient] = []`
  (additive, default-empty ⇒ existing call sites compile and behave identically).
- **No change** to `filter`, `enrich`, `score` contracts, or `ScoreResult`. **Stage 4 LLM untouched.**

## Tests (offline; pytest stays fully green, zero network)
- **Keep green:** the existing 35 (they drive fixture clients; default empty extra-sources keeps the
  Places-only path byte-identical).
- **Add (`tests/test_sources.py`):**
  1. `FixtureJustDialClient.discover` returns the recorded raws; `_raw_to_lead` yields
     `source="justdial"`, `place_id="justdial:<id>"`, fields mapped.
  2. Same for IndiaMART.
  3. **Merge dedup:** Places + JustDial fixtures where one phone collides → final count = union minus
     the collision; the surviving row is the **Places** record (`source="google_places"`).
  4. **In-source dedup** still holds (duplicate `place_id` collapses).
  5. **Toggle:** `discover(..., extra_sources=[])` == today's result; with sources, count grows by the
     non-colliding listings.
  6. `_norm_phone`: `"+91 98765 43210"`, `"098765-43210"`, `"12345"` → `"9876543210"`,
     `"9876543210"`, `None`.
- **Live adapters are NOT tested live.** If a `MockTransport`-backed unit test for `JustDialClient`'s
  HTML/JSON parsing is added, it uses a **recorded** response fixture and asserts parse → raw dict;
  still offline. **Never add a live JustDial/IndiaMART fetch to pytest.**

## Final checks (the gate — all must pass)
```
uv run pytest -q          # 35 + new source tests, fully offline
uv run ruff check .
uv run mypy
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
```
The offline smoke must still succeed and now exercise the merge path (fixtures present). A **live**
multi-source run is operator-driven and **gated on confirming robots.txt/ToS first** — do it by hand,
never in CI/pytest.

## Definition of done (adapted from session-07 item A)
JustDial (and IndiaMART, parity) adapters exist behind a `SourceClient` interface with live + fixture
impls; results normalize into the `Lead` shape with the correct `source` tag and synthetic namespaced
`place_id`; they feed the **same** `discover` dedup, with best-effort cross-source phone dedup (Places
canonical); sources are toggled as **data** (`NicheSpec.sources`), default Places-only so existing
runs are unchanged; offline fixture-backed tests cover normalization + dedup + toggle and
`uv run pytest` is green; `ruff`/`mypy` clean; the offline smoke run passes. Roadmap item A marked ✅.

**Commit message:**
```
Session 07A: JustDial/IndiaMART source adapters feeding shared place_id + phone dedup (data-toggled, offline-tested)
```
(The owner runs `git commit` — leave committing to them.)

## Non-negotiables touched & how honored
- **Cost / LLM only in Stage 4:** this is **Stage 1** work — **zero** LLM calls added. The LLM still
  touches only Stage-2 survivors. New sources only grow the *raw* pull; Stage 2 still gates before any
  token spend.
- **Dedup on `place_id` (mandatory):** preserved and *extended* — synthetic namespaced ids keep
  per-source uniqueness; cross-source phone dedup is additive, never replaces place_id dedup.
- **Scraping etiquette:** robots.txt respected, rate-limited, concurrency-capped, real User-Agent,
  back-off, **cache by id** so re-runs don't refetch — the same bar `LiveHttpClient` already meets.
- **Legal (TRAI/TCCCPR):** output stays a list for a **human to contact manually**. No dialing /
  AI-voice / blasting — not even a stub. New sources only *find* businesses.
- **Secrets:** any source key (if required) read from `.env` via `require_key`; never hardcoded,
  printed, or committed. Don't touch `.env`/`.env.example`; keep the pre-commit secret check.
- **Config is data:** sources enabled via YAML (`NicheSpec.sources`), not code. Don't stage
  `out/`/`.cache/`.

## Risks / unknowns (research before the live step — never guess)
- **ToS & anti-bot (the #1 risk).** JustDial and IndiaMART Terms may restrict automated access; both
  deploy anti-scraping (rate limits, CAPTCHAs, JS rendering, possibly login walls). **Confirm
  robots.txt and ToS before any live fetch.** If a site disallows it, the adapter still exists and is
  offline-tested, but mark the live path "operator-discretion / may require an official API or a
  partner feed." Do **not** build evasion (rotating proxies, CAPTCHA-solving) — out of bounds.
- **No official free API.** Verify whether either offers a sanctioned API; if so, prefer it over HTML
  scraping. Don't assume an endpoint shape — inspect a real response first and record it as a fixture.
- **Cross-source dedup precision.** Phone-last-10 is a deliberate, cheap heuristic; it misses
  same-business-different-number and can over-merge shared reception lines. Acceptable for "boring
  plumbing"; note name+pincode fuzzy matching as a future refinement (not this step).
- **IndiaMART fit.** It's B2B supplier-oriented — likely low yield for local-clinic ICPs. Implement
  for parity but keep off by default; don't over-invest (CLAUDE.md: don't gold-plate discovery).
- **Geography mapping.** JustDial/IndiaMART search by **city/locality text**, not lat/lng tiles. The
  adapter consumes `GeographyInput` (use `geo.city`/`geo.state`); they don't need the Places tiling
  machinery — keep their `discover` simple and **don't** force them through `resolve_tiles`.
- **HTML brittleness.** Parsers break when markup changes. Keep selectors minimal and tolerant; lean
  on fixtures so tests are stable and a live break is obvious and isolated.

## What NOT to do (don't pull work forward)
No state-level tiling (item B / `resolve_tiles` TODO), no owner-name/LinkedIn enrichment (C), no
SQLite cross-run store (D), no opener-format variants (E). No new LLM calls anywhere. No
stage-contract changes beyond the additive `discover` param and `NicheSpec.sources`. No scraping-ToS
evasion. No live source calls in pytest. Don't touch `.env`/`.env.example` or Stage-4 enforcement.
