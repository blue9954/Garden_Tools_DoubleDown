"""File-system scanner.

Walks a list of root folders recursively and collects FileInfo objects
that pass the configured size/extension filters.
Runs in a QThread so the UI stays responsive.
"""

import os
from pathlib import Path
from typing import Generator, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.models.file_info import FileInfo


# Directories that are always excluded to avoid scanning system internals.
_SYSTEM_DIRS: frozenset[str] = frozenset(
    {
        "Windows",
        "Program Files",
        "Program Files (x86)",
        "$Recycle.Bin",
        "System Volume Information",
        "Recovery",
        "PerfLogs",
        ".git",
        "__pycache__",
        "node_modules",
        ".svn",
    }
)


class ScanWorker(QThread):
    """Emits `progress(count, path)` during scan, `finished(files)` when done."""

    progress = pyqtSignal(int, str)       # files found so far, current path
    finished = pyqtSignal(list)           # list[FileInfo]
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        folders: list[Path],
        min_size: int = 0,
        max_size: int = 0,
        extensions: Optional[frozenset[str]] = None,
        excluded_extensions: Optional[frozenset[str]] = None,
        include_hidden: bool = False,
        excluded_dirs: Optional[frozenset[str]] = None,
    ) -> None:
        super().__init__()
        self.folders = folders
        self.min_size = min_size
        self.max_size = max_size
        self.extensions = extensions                        # None → all
        self.excluded_extensions = excluded_extensions or frozenset()
        self.include_hidden = include_hidden
        self.excluded_dirs = excluded_dirs or _SYSTEM_DIRS
        self._running = True

    def stop(self) -> None:
        self._running = False

    # ── QThread entry point ───────────────────────────────────────────────

    def run(self) -> None:
        all_files: list[FileInfo] = []
        count = 0
        try:
            for folder in self.folders:
                for fi in self._walk(folder):
                    if not self._running:
                        return
                    all_files.append(fi)
                    count += 1
                    if count % 100 == 0:
                        self.progress.emit(count, str(fi.path))
            self.progress.emit(count, "")
            self.finished.emit(all_files)
        except Exception as exc:  # pragma: no cover
            self.error_occurred.emit(str(exc))

    # ── internals ─────────────────────────────────────────────────────────

    def _walk(self, root: Path) -> Generator[FileInfo, None, None]:
        try:
            entries = list(os.scandir(root))
        except (PermissionError, OSError):
            return

        for entry in entries:
            if not self._running:
                return
            try:
                name: str = entry.name
                if not self.include_hidden and name.startswith("."):
                    continue

                if entry.is_dir(follow_symlinks=False):
                    if name in self.excluded_dirs:
                        continue
                    yield from self._walk(Path(entry.path))

                elif entry.is_file(follow_symlinks=False):
                    stat = entry.stat()
                    size = stat.st_size
                    if size == 0:
                        continue
                    if self.min_size > 0 and size < self.min_size:
                        continue
                    if self.max_size > 0 and size > self.max_size:
                        continue
                    ext = Path(name).suffix.lower()
                    if self.extensions is not None and ext not in self.extensions:
                        continue
                    if ext in self.excluded_extensions:
                        continue

                    yield FileInfo(
                        path=Path(entry.path),
                        size=size,
                        mtime=stat.st_mtime,
                        ctime=stat.st_ctime,
                    )
            except (PermissionError, OSError):
                continue
