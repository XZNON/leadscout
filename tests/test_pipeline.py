"""End-to-end: all four stages on committed fixtures, fully offline. The definition-of-done test."""

from __future__ import annotations

import csv
import json

from leadscout.config import RunConfig
from leadscout.io_out import write_outputs
from leadscout.pipeline import run_pipeline
from leadscout.store import LeadStore


def test_walking_skeleton(geo, niche, icp, fixture_clients, tmp_path):
    places, http, llm = fixture_clients
    cfg = RunConfig(offline=True, cache_dir=tmp_path / "cache", out_dir=tmp_path / "out")

    result = run_pipeline(geo, niche, icp, cfg, places, http, llm)

    # Stage gates: raw deduped, filter narrowed, LLM only ran on survivors.
    assert result.raw_count == 8
    assert result.candidate_count == 2
    assert result.scored_count == 2
    assert result.llm_calls == 2, "LLM must run once per Stage-2 survivor, never on the raw pull"
    assert result.llm_calls <= result.candidate_count

    # Ranked: top row is the strong-fit clinic with a grounded opener.
    top = result.leads[0]
    assert top.place_id == "p_bright"
    assert top.fit_score is not None and top.fit_score >= 80
    assert top.detected_signals
    opener = top.suggested_opener.lower()
    assert any(
        any(w in opener for w in sig.lower().replace("'", " ").split() if len(w) > 3)
        for sig in top.detected_signals
    )

    # Disqualified candidate is capped low but still scored (kept for audit).
    city = next(x for x in result.leads if x.place_id == "p_cityhosp")
    assert city.disqualifiers_hit and city.fit_score <= 15

    # Outputs land on disk: ranked CSV, JSONL, and a separate disqualified audit file.
    paths = write_outputs(result.leads, result.dropped, cfg.out_dir)
    assert paths["csv"].exists() and paths["jsonl"].exists() and paths["disqualified"].exists()

    with paths["csv"].open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["name"] == "Bright Smile Dental"
    assert rows[0]["suggested_opener"]
    assert rows[0]["detected_signals"]

    # Audit file holds the deterministic Stage-2 rejects.
    assert len(result.dropped) == 6


def test_pipeline_records_leads_in_store(geo, niche, icp, fixture_clients, tmp_path):
    places, http, llm = fixture_clients
    db = tmp_path / "leadscout.db"
    cfg = RunConfig(
        offline=True, cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", db_path=db
    )

    result = run_pipeline(geo, niche, icp, cfg, places, http, llm)

    assert result.new_count == result.raw_count
    assert result.seen_count == 0

    with LeadStore(db) as store:
        assert store.get_state("p_bright") == "new"


def test_pipeline_cross_run_seen(geo, niche, icp, fixture_clients, tmp_path):
    places, http, llm = fixture_clients
    db = tmp_path / "leadscout.db"
    cfg = RunConfig(
        offline=True, cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", db_path=db
    )

    run_pipeline(geo, niche, icp, cfg, places, http, llm)
    result2 = run_pipeline(geo, niche, icp, cfg, places, http, llm)

    # Second run: all place_ids already in DB -> all seen
    assert result2.seen_count == result2.raw_count
    assert result2.new_count == 0
    # Stage counts unchanged — seen leads are flagged but NOT dropped
    assert result2.raw_count == 8
    assert result2.candidate_count == 2
    assert result2.scored_count == 2


def test_pipeline_export_with_lead_state(geo, niche, icp, fixture_clients, tmp_path):
    places, http, llm = fixture_clients
    db = tmp_path / "store.db"
    cfg = RunConfig(
        offline=True, cache_dir=tmp_path / "cache", out_dir=tmp_path / "out", db_path=db
    )

    result = run_pipeline(geo, niche, icp, cfg, places, http, llm)
    paths = write_outputs(result.leads, result.dropped, cfg.out_dir)

    assert paths["csv"].exists() and paths["jsonl"].exists() and paths["disqualified"].exists()

    with paths["csv"].open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert "lead_state" in (reader.fieldnames or [])
        rows = list(reader)
    assert rows[0]["lead_state"] in ("new", "seen", "contacted")

    with paths["jsonl"].open(encoding="utf-8") as f:
        top_row = json.loads(f.readline())
    assert "lead_state" in top_row
