# LeadScout

An **internal CLI tool** that turns a product's Ideal Customer Profile (ICP) into a ranked,
call-ready list of local businesses to cold-call — each with detected pain signals and a
personalized, grounded opener.

> **Discovery is commodity plumbing. The product is the ICP-driven qualification + opener layer.**
> Finding the raw list of businesses is the easy 5%; the value is deciding *which* of them have the
> pain your product solves and *what to say* to them.

See [`idea.md`](idea.md) for the full product spec and [`CLAUDE.md`](CLAUDE.md) for the operating
contract.

## What it does

Given an ICP, a target geography, and niche keywords, LeadScout runs a deterministic 4-stage
pipeline with a single LLM step at the end:

```
geography ─▶ 1. DISCOVER ─▶ 2. FILTER ─▶ 3. ENRICH ─▶ 4. SCORE ─▶ ranked leads.csv / .jsonl
niche kw      tiles+dedup     free,       scrape +     LLM:
ICP spec      (Places)        rules       reviews      fit_score + signals + opener
```

- **Stage 1 — Discover:** geography → overlapping ~50 km tiles → Places keyword search →
  paginate → dedup on `place_id`.
- **Stage 2 — Filter:** deterministic, free. Drops closed, out-of-niche, uncontactable, or
  out-of-size-range businesses *before* spending any LLM tokens.
- **Stage 3 — Enrich:** robots-aware, rate-limited, cached async scrape of homepage/about +
  representative reviews.
- **Stage 4 — Score:** the only LLM step, run **only** on Stage 2 survivors. Emits structured JSON
  (`fit_score`, `detected_signals`, `disqualifiers_hit`, `reasoning`, `suggested_opener`).

**Cost discipline is a hard rule:** Stages 1–3 contain zero LLM calls. The LLM never touches a raw
pull, and the run aborts scoring when a per-run USD budget ceiling is hit.

## Install

Requires **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Secrets live in `.env` only (never committed):

```
GOOGLE_MAPS_API_KEY=...
OPENAI_API_KEY=...
```

## Usage

```bash
# Live run
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml

# Offline run on fixtures — no keys, no network (what the tests exercise)
uv run leadscout run --icp examples/clinic.yaml --geo examples/bengaluru.yaml \
  --niche examples/dental.yaml --offline
```

| Flag | Description |
|------|-------------|
| `--icp` | Path to ICP YAML (the heart of the system). |
| `--geo` | City name or geography YAML, e.g. `"Bengaluru"`. |
| `--niche` | Path to niche YAML (keywords + category allowlist). |
| `--offline` | Use fixtures; no keys, no network. |
| `--no-score` | Stop after Stage 3 (no LLM). |
| `--max-score N` | Cap the number of survivors sent to the LLM. |
| `--out DIR` | Output directory (default `out`). |

Outputs: `leads.csv` and `leads.jsonl` ranked by `fit_score`, plus a separate disqualified-rows
file for audit.

## Configuration is data, not code

Adding a new product = writing a new ICP YAML. No code change.

- **ICP** ([`examples/clinic.yaml`](examples/clinic.yaml)) — product, buyer, `pain_signals`,
  `size_proxy`, `disqualifiers`.
- **Niche** ([`examples/dental.yaml`](examples/dental.yaml)) — `keywords` + `place_type_allowlist`.
- **Geography** ([`examples/bengaluru.yaml`](examples/bengaluru.yaml)) — point+radius, named
  city/state, or bbox.

## Development

```bash
uv run pytest          # must be green, fully offline (cache hits, no live calls)
uv run ruff check .
uv run mypy
```

### Layout

```
src/leadscout/
  models.py    config.py   cache.py   pipeline.py   io_out.py   cli.py   clients.py
  stages/      discover.py  filter.py  enrich.py  score.py
examples/      ICP / niche / geography YAML
fixtures/      recorded businesses, pages, mocked LLM scores
tests/
docs/sessions/ one session per file — the build roadmap
```

## How we work

Development proceeds **one session at a time** under [`docs/sessions/`](docs/sessions/README.md).
Open the lowest-numbered file that isn't ✅ done, do its steps, update status, commit. Don't pull
work forward from later sessions.

Current progress (see [the roadmap](docs/sessions/README.md) for detail):

| # | Session | Status |
|---|---------|--------|
| 01 | Bootstrap & walking skeleton | ✅ |
| 02 | Verify & green the skeleton | ✅ |
| 03 | Live discovery (Google Places) | ✅ |
| 04 | Live enrichment (scraping) | ✅ |
| 05 | Live scoring (LLM) | ⬜ |
| 06 | First real run & tuning | ⬜ |
| 07+ | Post-MVP backlog | ⬜ |

## Scope & legal

Output is a list for a **human to contact manually** on publicly listed business numbers. LeadScout
does **not** do — and will never include — bulk/automated dialing, AI-voice calling, or email
blasting (India TCCCPR / TRAI compliance). No CRM, no SaaS, no web UI in v1 — CLI first.
