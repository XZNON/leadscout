# Session roadmap

LeadScout is built **one session at a time**. Each file in this folder is a self-contained unit
of work: open it, do the steps, hit its "Definition of done", commit, then move to the next.

**How to use (start of a session):**
1. Read `idea.md` (product truth) and `CLAUDE.md` (how we work) if you're fresh.
2. Open the lowest-numbered session file that isn't `✅ done`.
3. Do its steps. Don't pull work forward from later sessions — that's the point.
4. Update the status box at the top of the file and the table below.

**Status legend:** ⬜ not started · 🔨 in progress · ✅ done

| # | Session | Status | One-line goal |
|---|---------|--------|---------------|
| 01 | [Bootstrap & walking skeleton](session-01-bootstrap.md) | 🔨 | Harness + scaffold + offline pipeline + tests written |
| 02 | [Verify & green the skeleton](session-02-verify.md) | ⬜ | `uv sync`, pytest green, offline run, first commit |
| 03 | [Live discovery (Google Places)](session-03-live-discover.md) | ⬜ | Replace Places/Geocoding stubs; real tiling + cache |
| 04 | [Live enrichment (scraping)](session-04-live-enrich.md) | ⬜ | robots-aware async scraper replaces HTTP stub |
| 05 | [Live scoring (OpenAI)](session-05-live-score.md) | ⬜ | Structured-output LLM + token-cost budget enforcement |
| 06 | [First real run & tuning](session-06-real-run.md) | ⬜ | End-to-end on Bengaluru dental; tune ICP/filters |
| 07+ | [Post-MVP backlog](session-07-post-mvp.md) | ⬜ | JustDial/IndiaMART, state tiling, owner enrichment, SQLite |

**Rule of thumb on effort (from CLAUDE.md):** discovery is commodity plumbing; the product is the
Stage-4 qualification + opener layer. Sessions 03–04 should be boring and correct. Session 05 and
06 are where the real thinking goes.
