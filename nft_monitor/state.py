from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .util import safe_dir_name, utc_now_iso

SCHEMA_VERSION = 1


class StateStore:
    """Последние снимки подарков (JSON) и журнал событий (JSONL: общий и по каждому подарку)."""

    def __init__(self, path: Path, events_path: Path) -> None:
        self.path = path
        self.events_path = events_path
        self.gift_events_dir = events_path.parent / "gifts"
        self.data = self._load()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"schema": SCHEMA_VERSION, "created_at": utc_now_iso(), "updated_at": None, "gifts": {}}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            text = self.path.read_text(encoding="utf-8-sig").strip()
            if not text:
                return self._empty_state()
            data = json.loads(text)
            if not isinstance(data, dict):
                raise json.JSONDecodeError("state is not an object", text, 0)
        except json.JSONDecodeError:
            self._quarantine_broken()
            return self._empty_state()
        data.setdefault("schema", SCHEMA_VERSION)
        data.setdefault("gifts", {})
        return data

    def _quarantine_broken(self) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_suffix(f"{self.path.suffix}.broken-{stamp}")
        try:
            self.path.replace(backup)
            logging.error("Broken state moved to %s", backup)
        except OSError:
            logging.exception("Cannot move broken state")

    def save(self) -> None:
        self.data["updated_at"] = utc_now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def gift(self, slug: str) -> dict[str, Any] | None:
        return self.data["gifts"].get(slug)

    def upsert_gift(self, slug: str, snapshot: dict[str, Any]) -> None:
        self.data["gifts"][slug] = snapshot
        self.save()

    def append_event(self, event: dict[str, Any]) -> None:
        event.setdefault("created_at", utc_now_iso())
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        self._append_line(self.events_path, payload)

        slug = event.get("slug") or event.get("snapshot", {}).get("slug")
        if slug:
            self._append_line(self.gift_events_dir / safe_dir_name(slug) / self.events_path.name, payload)

    @staticmethod
    def _append_line(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(payload)
