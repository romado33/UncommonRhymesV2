"""Helpers for detecting Git-LFS pointer files."""
from __future__ import annotations

from pathlib import Path

_POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"


def looks_like_lfs_pointer(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_lines = [handle.readline().strip() for _ in range(3)]
    except OSError:
        return False
    return any(_POINTER_PREFIX in line for line in first_lines)

__all__ = ["looks_like_lfs_pointer"]
