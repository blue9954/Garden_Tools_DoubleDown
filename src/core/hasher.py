"""Three-stage hash engine.

Stage 1 — size pre-filter   : group files by byte size; skip singletons.
Stage 2 — partial hash (MD5): hash first 64 KB; skip singletons again.
Stage 3 — full hash (SHA-256): hash entire file for remaining candidates.

Using a ThreadPoolExecutor for parallel I/O.
Cache hits skip re-reading unchanged files.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.models.file_info import FileInfo
from src.utils.cache import HashCache


_PARTIAL_BYTES = 65_536      # 64 KB for the quick first-pass hash
_READ_BUFFER   = 1 << 20    # 1 MB I/O buffer for full hash


# ── Pure functions (can be called from any thread) ────────────────────────────

def _partial_hash(path: Path) -> Optional[str]:
    try:
        h = hashlib.md5(usedforsecurity=False)
        with open(path, "rb") as fh:
            h.update(fh.read(_PARTIAL_BYTES))
        return h.hexdigest()
    except OSError:
        return None


def _full_hash(path: Path, stop_check=None) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(_READ_BUFFER), b""):
                if stop_check and not stop_check():
                    return None  # cancelled mid-file
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


# ── Worker thread ─────────────────────────────────────────────────────────────

class HashWorker(QThread):
    """
    Signals
    -------
    stage_changed(description)      — emitted when moving to a new stage
    progress(done, total, path)     — emitted periodically within a stage
    finished(files)                 — only files that have a full_hash collision
    error_occurred(message)
    """

    stage_changed  = pyqtSignal(str)
    progress       = pyqtSignal(int, int, str)
    finished       = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        files: list[FileInfo],
        cache: Optional[HashCache] = None,
        max_workers: int = 4,
    ) -> None:
        super().__init__()
        self.files = files
        self.cache = cache
        self.max_workers = max_workers
        self._running = True
        self._paused  = False

    def stop(self) -> None:
        self._running = False

    def set_paused(self, paused: bool) -> None:
        self._paused = paused

    def _check(self) -> bool:
        """Block while paused; return False if stopped."""
        while self._paused and self._running:
            self.msleep(100)
        return self._running

    # ── QThread entry point ───────────────────────────────────────────────

    def run(self) -> None:
        try:
            # ── Stage 1: size pre-filter ──────────────────────────────────
            self.stage_changed.emit("크기 기반 사전 필터링...")
            size_map: dict[int, list[FileInfo]] = {}
            for f in self.files:
                size_map.setdefault(f.size, []).append(f)
            candidates = [f for g in size_map.values() if len(g) > 1 for f in g]

            if not candidates:
                self.finished.emit([])
                return

            # ── Stage 2: partial hash ─────────────────────────────────────
            self.stage_changed.emit(f"부분 해시 계산 중... ({len(candidates):,}개)")
            candidates = self._batch(candidates, partial=True)
            if not self._running:
                return

            partial_map: dict[str, list[FileInfo]] = {}
            for f in candidates:
                if f.partial_hash:
                    partial_map.setdefault(f.partial_hash, []).append(f)
            candidates = [f for g in partial_map.values() if len(g) > 1 for f in g]

            if not candidates:
                self.finished.emit([])
                return

            # ── Stage 3: full hash ────────────────────────────────────────
            self.stage_changed.emit(f"전체 해시 계산 중... ({len(candidates):,}개)")
            candidates = self._batch(candidates, partial=False)
            if not self._running:
                return

            self.finished.emit(candidates)
        except Exception as exc:  # pragma: no cover
            self.error_occurred.emit(str(exc))

    # ── internals ─────────────────────────────────────────────────────────

    def _batch(self, files: list[FileInfo], partial: bool) -> list[FileInfo]:
        total = len(files)
        results: list[FileInfo] = []

        def process(fi: FileInfo) -> FileInfo:
            if partial:
                if self.cache:
                    cached = self.cache.get_partial(fi.path, fi.mtime)
                    if cached:
                        fi.partial_hash = cached
                        return fi
                h = _partial_hash(fi.path)
                fi.partial_hash = h
                if h and self.cache:
                    self.cache.set_partial(fi.path, fi.mtime, h)
            else:
                if self.cache:
                    cached = self.cache.get_full(fi.path, fi.mtime)
                    if cached:
                        fi.full_hash = cached
                        return fi
                h = _full_hash(fi.path, stop_check=lambda: self._running)
                fi.full_hash = h
                if h and self.cache:
                    self.cache.set_full(fi.path, fi.mtime, h)
            return fi

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map = {pool.submit(process, f): f for f in files}
            done = 0
            for fut in as_completed(future_map):
                if not self._check():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return results
                fi = fut.result()
                results.append(fi)
                done += 1
                if done % 20 == 0 or done == total:
                    self.progress.emit(done, total, str(fi.path))

        return results
