"""Output writers: ranked leads.csv + leads.jsonl, and a separate disqualified audit file."""

from __future__ import annotations

import json
from pathlib import Path

from .models import DropRecord, Lead

# Flat column order for the CSV (the call-ready view).
CSV_COLUMNS = [
    "fit_score", "name", "phone", "email", "owner_name", "website",
    "category", "address", "city", "rating", "review_count",
    "detected_signals", "disqualifiers_hit", "suggested_opener",
    "opener_call", "opener_email", "opener_whatsapp", "reasoning",
    "place_id", "source", "lead_state",
]


def _row(lead: Lead, columns: list[str]) -> dict:
    d = lead.model_dump()
    d["detected_signals"] = " | ".join(lead.detected_signals)
    d["disqualifiers_hit"] = " | ".join(lead.disqualifiers_hit)
    return {col: d.get(col, "") for col in columns}


def _filter(d: dict, fields: list[str] | None) -> dict:
    if fields is None:
        return d
    return {k: v for k, v in d.items() if k in fields}


def write_outputs(
    leads: list[Lead],
    dropped: list[DropRecord],
    out_dir: str | Path,
    fields: list[str] | None = None,
) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    csv_path = out / "leads.csv"
    jsonl_path = out / "leads.jsonl"
    disq_path = out / "disqualified.jsonl"

    # Columns: if --fields given, keep only requested ones in CSV_COLUMNS order.
    columns = [c for c in CSV_COLUMNS if fields is None or c in fields]

    # CSV via pandas (idea.md §8). Import locally so a missing pandas doesn't break imports.
    import pandas as pd

    pd.DataFrame([_row(x, columns) for x in leads], columns=columns).to_csv(
        csv_path, index=False
    )

    with jsonl_path.open("w", encoding="utf-8") as f:
        for lead in leads:
            f.write(json.dumps(_filter(lead.model_dump(), fields), ensure_ascii=False) + "\n")

    with disq_path.open("w", encoding="utf-8") as f:
        for rec in dropped:
            f.write(json.dumps(_filter(rec.model_dump(), fields), ensure_ascii=False) + "\n")

    return {"csv": csv_path, "jsonl": jsonl_path, "disqualified": disq_path}
