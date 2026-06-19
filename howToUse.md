# How to use LeadScout

LeadScout takes your product's target customer profile, a location, and a business category — and gives you a ranked list of real local businesses to cold-contact, each with a personalized opening line.

---

## Setup (one time)

```bash
uv sync
```

Create a `.env` file in the project root:
```
GOOGLE_MAPS_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

---

## The basic run

```bash
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml
```

Three things you always need:
- `--icp` — your product's ICP (who you're selling to and what pain you solve)
- `--geo` — where to search
- `--niche` — what kind of business to look for

Outputs land in `out/` by default:
- `leads.csv` — ranked list, best fit first
- `leads.jsonl` — same data as JSON
- `disqualified.jsonl` — businesses that were found but filtered out, with the reason

---

## Search a specific area

Pass any neighbourhood, city, or area name:

```bash
--geo "HSR Layout, Bengaluru"
--geo "Koramangala, Bengaluru"
--geo "Pune"
--geo "Delhi NCR"
```

For precise control (exact lat/lng + radius), create a YAML file:

```yaml
# examples/hsr.yaml
point:
  lat: 12.9116
  lng: 77.6473
  radius_km: 3.0
```

Then use it:
```bash
--geo examples/hsr.yaml
```

---

## Test without using your API credits (offline mode)

Uses pre-recorded fixture data — no Google Maps, no OpenAI, no keys needed:

```bash
uv run leadscout run --icp examples/clinic.yaml --geo "Bengaluru" --niche examples/dental.yaml --offline
```

Note: you always get the same 2 fixture businesses in offline mode regardless of the geo you pass. This is for testing the pipeline works, not for real prospecting.

---

## Fast runs (when you don't want to wait)

A busy area like HSR Layout can return 1,500+ businesses. Full scraping takes 20+ minutes cold.
Use these flags to cap it:

```bash
# Scrape only 20 websites, score only 10 — done in ~2 minutes
uv run leadscout run --icp examples/clinic.yaml --geo "HSR Layout, Bengaluru" --niche examples/dental.yaml \
  --max-enrich 20 --max-score 10
```

| Flag | What it caps |
|------|-------------|
| `--max-enrich N` | How many candidates get their website scraped (Stage 3) |
| `--max-score N` | How many scraped leads get sent to the LLM (Stage 4) |

After the first run, everything is cached — repeat runs on the same area are fast automatically.

---

## Skip the LLM entirely

Just discover and scrape, no OpenAI cost at all:

```bash
uv run leadscout run --icp examples/clinic.yaml --geo "HSR Layout, Bengaluru" --niche examples/dental.yaml --no-score
```

Useful for checking discovery is working before committing to scoring spend.

---

## Get openers for different channels

By default you get a call-script opener. Ask for email or WhatsApp instead, or all three at once:

```bash
# Email opener only
--opener-format email

# WhatsApp opener only
--opener-format whatsapp

# All three at once (one LLM call per lead — no extra cost)
--opener-format call --opener-format email --opener-format whatsapp
```

The output CSV/JSONL will have `opener_call`, `opener_email`, and `opener_whatsapp` columns.
Every opener is grounded in a real signal detected from the business's website — never a generic template.

---

## Control which fields appear in your output

If you only want specific columns in your CSV and JSONL:

```bash
--fields "name,phone,website,category,fit_score,suggested_opener"
```

Available fields:
```
fit_score       name            phone           email
owner_name      website         category        address
city            rating          review_count    detected_signals
disqualifiers_hit  suggested_opener  opener_call  opener_email
opener_whatsapp    reasoning     place_id        source
lead_state
```

Order in the output always follows the canonical column order regardless of the order you list them.

---

## Save to a different folder

```bash
--out my_results
```

---

## Track leads across runs (cross-run dedup)

LeadScout automatically remembers which businesses it has seen before using a local SQLite database.
On the first run a business is `new`. On every subsequent run it's `seen`. This prevents re-working
the same leads.

The DB is at `.cache/leadscout.db` by default. To use a different path:

```bash
--db my_project/leads.db
```

To manually mark a lead as contacted:
```bash
uv run leadscout mark <place_id> contacted --db my_project/leads.db
```

States: `new` → `seen` → `contacted` (never goes backwards automatically).

---

## Save outputs to a named folder per run

Good practice when running multiple areas:

```bash
uv run leadscout run --icp examples/clinic.yaml --geo "HSR Layout, Bengaluru" --niche examples/dental.yaml --out out/hsr
uv run leadscout run --icp examples/clinic.yaml --geo "Koramangala, Bengaluru" --niche examples/dental.yaml --out out/koramangala
```

---

## Full production run example

```bash
uv run leadscout run \
  --icp examples/clinic.yaml \
  --geo "HSR Layout, Bengaluru" \
  --niche examples/dental.yaml \
  --opener-format call --opener-format email \
  --fields "name,phone,email,website,fit_score,suggested_opener,opener_call,opener_email,detected_signals" \
  --out out/hsr_jun19 \
  --db .cache/leadscout.db
```

---

## All flags at a glance

| Flag | Default | What it does |
|------|---------|-------------|
| `--icp PATH` | required | Your ICP YAML file |
| `--geo TEXT` | required | Area to search — city name or YAML file |
| `--niche PATH` | required | Niche YAML (keywords + business types) |
| `--offline` | off | Use fixture data, no API keys needed |
| `--no-score` | off | Skip Stage 4 (no LLM, no OpenAI cost) |
| `--max-enrich N` | unlimited | Cap website scraping (speed) |
| `--max-score N` | unlimited | Cap LLM calls (cost) |
| `--opener-format` | `call` | Channel for opener: `call`, `email`, `whatsapp` |
| `--fields TEXT` | all fields | Comma-separated fields to include in output |
| `--out DIR` | `out` | Where to write leads.csv / leads.jsonl |
| `--db PATH` | `.cache/leadscout.db` | SQLite DB for cross-run state |

---

## How long does it take?

| Scenario | Time |
|----------|------|
| Offline (fixture) run | ~1 second |
| Cached run (same area, already run before) | ~30 seconds |
| Fast run with `--max-enrich 20 --max-score 10` | ~2 minutes |
| Full cold run on a busy area (1,500+ businesses) | 20–30 minutes |

The cache is the key — run any area once and every run after that is fast.
