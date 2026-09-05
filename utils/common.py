"""Shared helpers: file sizes, temp paths."""

from __future__ import annotations

import os
from pathlib import Path


def file_size(path: str | Path) -> int:
    """Return file size in bytes."""
    return os.path.getsize(path)


def format_size(num_bytes: int | float) -> str:
    """Human-readable size string."""
    n = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{n:.2f} GB"


def size_summary(before: int, after: int) -> str:
    """Before/after size line with percent change."""
    if before <= 0:
        return f"Before: {format_size(before)} → After: {format_size(after)}"
    ratio = (after / before) * 100.0
    saved = before - after
    pct = ((before - after) / before) * 100.0
    if saved >= 0:
        return (
            f"Before: {format_size(before)} → After: {format_size(after)} "
            f"({ratio:.1f}% of original, saved {format_size(saved)} / {pct:.1f}%)"
        )
    return (
        f"Before: {format_size(before)} → After: {format_size(after)} "
        f"({ratio:.1f}% of original, grew by {format_size(-saved)})"
    )


def ensure_parent(path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
