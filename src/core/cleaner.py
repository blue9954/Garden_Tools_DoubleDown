"""File deletion worker.

Supports:
  - Trash (via send2trash) — safe default
  - Permanent deletion
  - Dry-run mode (no actual deletion)
  - JSON audit log written after each run
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal
import send2trash

from src.models.file_info import FileInfo

log = logging.getLogger(__name__)


class CleanWorker(QThread):
    """
    Signals
    -------
    progress(done, total, path)   — emitted for each file processed
    finished(deleted, freed)      — total count and bytes freed
    error_occurred(message)       — non-fatal errors are logged; fatal ones here
    """

    progress       = pyqtSignal(int, int, str)
    finished       = pyqtSignal(int, int)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        to_delete: list[FileInfo],
        use_trash: bool = True,
        dry_run: bool = False,
        log_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self.to_delete = to_delete
        self.use_trash = use_trash
        self.dry_run   = dry_run
        self.log_path  = log_path
        self._running  = True

    def stop(self) -> None:
        self._running = False

    # ── QThread entry point ───────────────────────────────────────────────

    def run(self) -> None:
        deleted = 0
        freed   = 0
        entries: list[dict] = []
        total = len(self.to_delete)

        for i, fi in enumerate(self.to_delete):
            if not self._running:
                break

            self.progress.emit(i + 1, total, str(fi.path))

            entry: dict = {
                "path"      : str(fi.path),
                "size"      : fi.size,
                "hash"      : fi.full_hash,
                "timestamp" : datetime.now().isoformat(),
                "method"    : "trash" if self.use_trash else "permanent",
                "dry_run"   : self.dry_run,
            }

            try:
                if not self.dry_run:
                    if self.use_trash:
                        send2trash.send2trash(str(fi.path))
                    else:
                        fi.path.unlink(missing_ok=True)
                deleted += 1
                freed   += fi.size
                entry["status"] = "ok"
            except Exception as exc:
                log.warning("Delete failed %s: %s", fi.path, exc)
                entry["status"] = "error"
                entry["error"]  = str(exc)

            entries.append(entry)

        self._write_log(entries)
        self.finished.emit(deleted, freed)

    def _write_log(self, entries: list[dict]) -> None:
        if not self.log_path or not entries:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_path.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2), "utf-8"
            )
        except OSError as exc:
            log.warning("Could not write delete log: %s", exc)
