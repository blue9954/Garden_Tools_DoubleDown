"""SQLite-backed hash cache.

Stores partial and full hashes keyed by (path, mtime) so repeated scans
skip re-hashing files that have not changed.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional


class HashCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                path    TEXT PRIMARY KEY,
                mtime   REAL NOT NULL,
                partial TEXT,
                full    TEXT
            )
            """
        )
        self._conn.commit()

    # ── reads ─────────────────────────────────────────────────────────────
    # WAL mode allows concurrent reads from *separate connections*, but a single
    # sqlite3.Connection object is NOT thread-safe even with check_same_thread=False.
    # HashWorker submits many concurrent futures — all sharing this one connection —
    # so reads must also be serialised through the same lock as writes.

    def _row(self, path: Path, mtime: float) -> Optional[sqlite3.Row]:
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime, partial, full FROM cache WHERE path = ?",
                (str(path),),
            ).fetchone()
        # Tolerate sub-second mtime rounding differences (FAT32, etc.)
        # Guard row[0] against NULL: can happen if the table was created by an
        # older schema without NOT NULL, or due to an interrupted write.
        if row and row[0] is not None and abs(row[0] - mtime) < 2.0:
            return row
        return None

    def get_partial(self, path: Path, mtime: float) -> Optional[str]:
        row = self._row(path, mtime)
        return row[1] if row else None

    def get_full(self, path: Path, mtime: float) -> Optional[str]:
        row = self._row(path, mtime)
        return row[2] if row else None

    # ── writes ────────────────────────────────────────────────────────────

    def set_partial(self, path: Path, mtime: float, h: str) -> None:
        if mtime is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache(path, mtime, partial) VALUES(?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime,"
                " partial=excluded.partial",
                (str(path), mtime, h),
            )
            self._conn.commit()

    def set_full(self, path: Path, mtime: float, h: str) -> None:
        if mtime is None:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO cache(path, mtime, full) VALUES(?,?,?)"
                " ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime,"
                " full=excluded.full",
                (str(path), mtime, h),
            )
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()
