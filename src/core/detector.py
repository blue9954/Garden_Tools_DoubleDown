"""Duplicate-group detector.

Groups files that share the same full SHA-256 hash and applies a
configurable keep-file heuristic.
"""

from pathlib import Path
from typing import Optional

from src.models.file_info import DuplicateGroup, FileInfo


class DuplicateDetector:
    """
    Parameters
    ----------
    prefer_folders
        Files inside these folders are sorted first (i.e. marked 'keep')
        over files elsewhere. Useful for protecting an "original" drive.
    """

    def __init__(self, prefer_folders: Optional[list[Path]] = None) -> None:
        self.prefer_folders: list[Path] = prefer_folders or []

    def detect(self, files: list[FileInfo]) -> list[DuplicateGroup]:
        """Return groups of duplicate files, sorted by wasted space (desc)."""
        hash_map: dict[str, list[FileInfo]] = {}
        for f in files:
            if f.full_hash:
                hash_map.setdefault(f.full_hash, []).append(f)

        groups: list[DuplicateGroup] = []
        for h, file_list in hash_map.items():
            if len(file_list) < 2:
                continue
            sorted_files = sorted(file_list, key=self._sort_key)
            groups.append(DuplicateGroup(hash_value=h, files=sorted_files))

        groups.sort(key=lambda g: g.wasted_size, reverse=True)
        return groups

    # ── keep-file heuristic ───────────────────────────────────────────────

    def _sort_key(self, f: FileInfo) -> tuple:
        """Lower sort value → more likely to be the original (kept)."""
        not_preferred = int(
            not any(
                str(f.path).startswith(str(p)) for p in self.prefer_folders
            )
        )
        # 1. Prefer files in preferred folders
        # 2. Prefer older creation time (original)
        # 3. Prefer shorter name (copies often have "(1)" suffix)
        return (not_preferred, f.ctime, len(f.name))
