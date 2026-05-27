"""Shared formatting helpers used by every tool module."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence


def fmt_bytes(n: int | float | None) -> str:
    """Return '1.5 GB' style string. None → '-'."""
    if n is None:
        return "-"
    try:
        x = float(n)
    except (TypeError, ValueError):
        return str(n)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(x) < 1024.0:
            if unit == "B":
                return f"{int(x)} {unit}"
            return f"{x:.1f} {unit}"
        x /= 1024.0
    return f"{x:.1f} EB"


def fmt_unix_ts(ts: int | float | None) -> str:
    """Return UTC ISO-8601 string for a Unix timestamp, or '-' if falsy."""
    if not ts:
        return "-"
    try:
        return (
            datetime.fromtimestamp(int(ts), tz=timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (TypeError, ValueError, OSError):
        return str(ts)


def md_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render a simple Markdown table. Cells coerced to str."""
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
    body_lines = [
        "| " + " | ".join("" if c is None else str(c) for c in row) + " |"
        for row in rows
    ]
    return "\n".join([header_line, sep_line, *body_lines])


def truncate(s: str, limit: int = 4000) -> str:
    """Hard cap MCP responses so we don't blow context."""
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n\n... [truncated, total {len(s)} chars]"
