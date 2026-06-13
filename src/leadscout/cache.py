"""Dead-simple JSON file cache keyed by place_id (+ namespace).

Used to make re-runs nearly free: place details and scrapes are written once and read back on
subsequent runs. No live API call in tests because fixtures pre-populate the cache path or the
fixture clients bypass the network entirely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonCache:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, namespace: str, key: str) -> Path:
        safe = key.replace("/", "_").replace(":", "_")
        return self.root / namespace / f"{safe}.json"

    def get(self, namespace: str, key: str) -> Any | None:
        p = self._path(namespace, key)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def set(self, namespace: str, key: str, value: Any) -> None:
        p = self._path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def has(self, namespace: str, key: str) -> bool:
        return self._path(namespace, key).exists()
