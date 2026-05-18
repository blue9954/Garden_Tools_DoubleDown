from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def fmt_size(size: int) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


@dataclass
class FileInfo:
    path: Path
    size: int
    mtime: float          # modification time (epoch)
    ctime: float          # creation time (epoch)
    partial_hash: Optional[str] = None
    full_hash: Optional[str] = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def extension(self) -> str:
        return self.path.suffix.lower()

    @property
    def size_str(self) -> str:
        return fmt_size(self.size)


@dataclass
class DuplicateGroup:
    """A set of files that are byte-for-byte identical."""
    hash_value: str
    files: list[FileInfo] = field(default_factory=list)
    keep_index: int = 0   # index inside files[] that will NOT be deleted

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def wasted_size(self) -> int:
        """Bytes that can be freed (all files except the one to keep)."""
        if not self.files:
            return 0
        # All files in a group have the same content → same size.
        return self.files[0].size * (len(self.files) - 1)

    @property
    def wasted_size_str(self) -> str:
        return fmt_size(self.wasted_size)

    def files_to_delete(self) -> list[FileInfo]:
        return [f for i, f in enumerate(self.files) if i != self.keep_index]
