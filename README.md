# LeadScout

An internal CLI tool that turns a product's Ideal Customer Profile (ICP) into a ranked,
call-ready list of local businesses — each with detected pain signals and a personalized opener
drafted for the channel you intend to use (call, email, or WhatsApp).

> **Discovery is commodity plumbing. The product is the ICP-driven qualification + opener layer.**
> Finding the raw list of businesses is the easy 5%; the value is deciding *which* of them have the
> pain your product solves and *what to say* to them.

## What it does

Given an ICP, a target geography, and niche keywords, LeadScout runs a 4-stage pipeline with a
single LLM step at the end:

```
geography ──▶ 1. DISCOVER ──▶ 2. FILTER ──▶ 3. ENRICH ──▶ 4. SCORE ──▶ leads.csv / .jsonl
niche          tiles + dedup    free,          scrape +       LLM only on
ICP spec       (Places API)     rules-based    reviews        Stage-2 survivors
```

- **Stage 1 — Discover:** tiles the geography, searches Google Places per keyword, paginates,
  deduplicates on `place_id`. JustDial and IndiaMART can be enabled per niche YAML.
- **Stage 2 — Filter:** deterministic, free. Drops closed, uncontactable, wrong-size, or
  out-of-niche businesses before spending any LLM tokens.
- **Stage 3 — Enrich:** robots-aware, rate-limited, cached async scraper. Reads homepage + about
  pages + reviews. Results cached by `place_id` so repeat runs are free.
- **Stage 4 — Score:** the only LLM step, only on Stage-2 survivors, under a USD budget ceiling.
  Emits `fit_score`, `detected_signals`, `disqualifiers_hit`, `reasoning`, and opener drafts
  for each requested channel.

**Cost discipline is a hard rule:** Stages 1–3 are zero LLM. The LLM never touches a raw pull.
Scoring stops when the per-run budget ceiling is hit.

## Install

Requires **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Secrets go in `.env` only (gitignored, never committed):

```
GOOGLE_MAPS_API_KEY=...
OPENAI_API_KEY=...
```

## Quick start

```bash
# Live run — discovers real businesses, scrapes their sites, scores with OpenAI
uv run leadscout run --icp examples/clinic.yaml --geo "HSR Layout, Bengaluru" --niche examples/dental.yaml

# Offline run — no keys, no network, fixture data only (same path the tests use)
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
```

See [`howToUse.md`](howToUse.md) for all usage patterns with examples.

## All flags

| Flag | Default | Description |
|------|---------|-------------|
| `--icp` | required | Path to ICP YAML. |
| `--geo` | required | City name (`"HSR Layout, Bengaluru"`) or path to a geography YAML. |
| `--niche` | required | Path to niche YAML (keywords + category allowlist). |
| `--offline` | false | Use fixture data — no keys, no network. |
| `--no-score` | false | Stop after Stage 3, skip the LLM entirely. |
| `--max-score N` | unlimited | Cap how many candidates reach the LLM (cost guard). |
| `--max-enrich N` | unlimited | Cap how many candidates get website-scraped (speed guard). |
| `--opener-format` | `call` | Opener channel(s): `call`, `email`, `whatsapp`. Repeatable or comma-list. |
| `--fields` | all | Comma-separated list of fields to include in CSV/JSONL output. |
| `--out DIR` | `out` | Output directory. |
| `--db PATH` | `.cache/leadscout.db` | SQLite DB for cross-run dedup and lead state. |

## Outputs

All written to `--out` directory (default `out/`):

| File | Contents |
|------|----------|
| `leads.csv` | Ranked leads, highest `fit_score` first. |
| `leads.jsonl` | Same leads as JSON, one record per line. |
| `disqualified.jsonl` | Audit trail of every lead dropped in Stage 2, with reason. |

## Configuration is data, not code

Adding a new product = writing a new ICP YAML. No code change required.

- **ICP** ([`examples/clinic.yaml`](examples/clinic.yaml)) — product, buyer, `pain_signals`,
  `size_proxy`, `disqualifiers`, `require_website`, `contactability`.
- **Niche** ([`examples/dental.yaml`](examples/dental.yaml)) — `keywords`, `place_type_allowlist`,
  `sources` (defaults to `google_places`; add `justdial`/`indiamart` to enable them).
- **Geography** — pass a bare city name on the CLI, or a YAML file with a `point` (lat/lng/radius),
  `city`, `state`, or `bbox`.

## Development

```bash
uv run pytest          # must be green, fully offline
uv run ruff check .
uv run mypy
```

### Layout

```
src/leadscout/
  models.py      typed contracts between stages
  config.py      RunConfig, YAML loaders
  pipeline.py    wires the four stages together
  cli.py         typer CLI entrypoint
  clients.py     Places, HTTP, LLM clients (live + fixture)
  cache.py       JSON cache keyed by place_id
  store.py       SQLite cross-run lead state
  io_out.py      CSV / JSONL writers
  stages/
    discover.py  Stage 1
    filter.py    Stage 2
    enrich.py    Stage 3
    score.py     Stage 4 (LLM)
examples/        ICP / niche / geography YAML
fixtures/        recorded API responses + mocked LLM scores
tests/
docs/sessions/   one session file per build increment
```

## Scope & legal

Output is a list for a **human to contact manually** on publicly listed business numbers.
LeadScout does not — and will never — include bulk/automated dialing, AI-voice calling, email
blasting, or WhatsApp broadcasting (India TRAI / TCCCPR compliance). No CRM, no SaaS, no web UI.
