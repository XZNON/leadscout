"""Offline unit tests for LeadStore. All I/O goes to tmp_path — no network, no global state."""

from __future__ import annotations

import sqlite3

from leadscout.models import Lead
from leadscout.store import _SCHEMA_VERSION, LeadStore


def _lead(place_id: str, name: str = "Test Clinic") -> Lead:
    return Lead(place_id=place_id, name=name)


# ---------------------------------------------------------------------------


def test_schema_creation(tmp_path):
    db = tmp_path / "leadscout.db"
    with LeadStore(db):
        pass  # just opening should create the file + table

    assert db.exists()
    conn = sqlite3.connect(str(db))
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='leads'")
    assert cur.fetchone() is not None, "leads table not created"
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == _SCHEMA_VERSION
    conn.close()


def test_new_on_first_sight(tmp_path):
    db = tmp_path / "leadscout.db"
    lead_a = _lead("place_a", "Clinic A")
    lead_b = _lead("place_b", "Clinic B")

    with LeadStore(db) as store:
        states = store.upsert_seen([lead_a, lead_b])

    assert states == {"place_a": "new", "place_b": "new"}


def test_cross_run_seen(tmp_path):
    db = tmp_path / "leadscout.db"
    lead_a = _lead("place_a")

    with LeadStore(db) as store:
        store.upsert_seen([lead_a])

    # Second LeadStore = new connection, same file = simulates a second run
    with LeadStore(db) as store2:
        states = store2.upsert_seen([lead_a])

    assert states == {"place_a": "seen"}


def test_contacted_is_sticky(tmp_path):
    db = tmp_path / "leadscout.db"
    lead_a = _lead("place_a")

    with LeadStore(db) as store:
        store.upsert_seen([lead_a])
        store.set_state("place_a", "contacted")

    with LeadStore(db) as store2:
        states = store2.upsert_seen([lead_a])

    assert states == {"place_a": "contacted"}


def test_get_set_state_round_trip(tmp_path):
    db = tmp_path / "leadscout.db"
    lead_a = _lead("place_a")

    with LeadStore(db) as store:
        store.upsert_seen([lead_a])
        assert store.get_state("place_a") == "new"
        store.set_state("place_a", "contacted")
        assert store.get_state("place_a") == "contacted"
        assert store.get_state("no_such_place") is None


def test_place_id_dedup_single_row(tmp_path):
    db = tmp_path / "leadscout.db"
    lead_a = _lead("place_a")

    with LeadStore(db) as store:
        store.upsert_seen([lead_a, lead_a])

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM leads WHERE place_id = 'place_a'").fetchone()[0]
    conn.close()
    assert count == 1
