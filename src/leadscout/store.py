"""SQLite-backed cross-run lead store: dedup reinforcement + lead state persistence.

Sits alongside JsonCache (raw HTTP bodies). This store owns structured, queryable concerns:
which place_ids we have seen across runs, and a per-lead state the operator can advance.
Zero LLM. Zero network. stdlib sqlite3 only.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from .models import Lead, LeadState

_SCHEMA_VERSION = 1

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS leads (
    place_id   TEXT PRIMARY KEY,
    source     TEXT,
    name       TEXT,
    state      TEXT NOT NULL DEFAULT 'new',
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO leads (place_id, source, name, state, first_seen, last_seen)
VALUES (?, ?, ?, 'new', ?, ?)
ON CONFLICT(place_id) DO UPDATE SET
    last_seen = excluded.last_seen,
    state = CASE WHEN state = 'new' THEN 'seen' ELSE state END;
"""

_GET_STATE_SQL = "SELECT state FROM leads WHERE place_id = ?"
_SET_STATE_SQL = "UPDATE leads SET state = ? WHERE place_id = ?"


class LeadStore:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()
        self._maybe_stamp_version()

    def _maybe_stamp_version(self) -> None:
        cur = self._conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]
        if version == 0:
            self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def upsert_seen(self, leads: list[Lead]) -> dict[str, LeadState]:
        """Record each lead by place_id; return the post-upsert state for each.

        Deduplicates within the batch (same place_id twice stays 'new' on first run).
        Bumps 'new' -> 'seen' on re-encounter; never downgrades 'contacted'.
        """
        now = datetime.now(UTC).isoformat()
        unique = {lead.place_id: lead for lead in leads}
        with self._conn:
            for lead in unique.values():
                self._conn.execute(
                    _UPSERT_SQL,
                    (lead.place_id, lead.source, lead.name, now, now),
                )
        states: dict[str, LeadState] = {}
        for place_id in unique:
            cur = self._conn.execute(_GET_STATE_SQL, (place_id,))
            row = cur.fetchone()
            states[place_id] = row[0] if row else "new"
        return states

    def get_state(self, place_id: str) -> LeadState | None:
        cur = self._conn.execute(_GET_STATE_SQL, (place_id,))
        row = cur.fetchone()
        return row[0] if row else None

    def set_state(self, place_id: str, state: LeadState) -> None:
        with self._conn:
            self._conn.execute(_SET_STATE_SQL, (state, place_id))

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> LeadStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
