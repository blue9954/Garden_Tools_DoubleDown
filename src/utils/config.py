"""Persistent JSON configuration store."""

import json
from pathlib import Path
from typing import Any

_DEFAULTS: dict[str, Any] = {
    "last_folders": [],
    "prefer_folders": [],
    "min_size_bytes": 0,
    "max_size_bytes": 0,
    "extensions": [],
    "excluded_extensions": [],
    "include_hidden": False,
    "use_trash": True,
    "dry_run": False,
    "max_workers": 4,
}


class Config:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text("utf-8"))
                self._data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8"
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
