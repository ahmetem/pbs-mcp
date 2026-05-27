"""Garbage collection tools. GC frees disk space from chunks no longer
referenced by any snapshot."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import fmt_bytes, md_table


# ---------- pbs_gc_status ----------------------------------------------------


class GcStatusInput(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)


def gc_status_handler(client: Any, params: GcStatusInput) -> str:
    ds = client.resolve_datastore(params.datastore)
    data = client.get(f"/admin/datastore/{ds}/gc")
    if not isinstance(data, dict):
        return f"_Unexpected gc-status payload: {data!r}_"

    upid = data.get("upid")
    last_status = (
        "no GC has run yet"
        if not upid
        else f"last GC UPID: `{upid}`"
    )

    rows = [
        ["Disk bytes (referenced)", fmt_bytes(data.get("disk-bytes"))],
        ["Disk chunks", data.get("disk-chunks", 0)],
        ["Index data bytes", fmt_bytes(data.get("index-data-bytes"))],
        ["Index file count", data.get("index-file-count", 0)],
        ["Pending bytes", fmt_bytes(data.get("pending-bytes"))],
        ["Pending chunks", data.get("pending-chunks", 0)],
        ["Removed bytes", fmt_bytes(data.get("removed-bytes"))],
        ["Removed chunks", data.get("removed-chunks", 0)],
        ["Removed bad", data.get("removed-bad", 0)],
        ["Still bad", data.get("still-bad", 0)],
    ]
    md = (
        f"## GC status for `{ds}`\n\n"
        f"{last_status}\n\n"
        + md_table(["Metric", "Value"], rows)
    )
    still_bad = data.get("still-bad", 0) or 0
    if still_bad:
        md += (
            f"\n\n⚠️  {still_bad} chunk(s) are flagged as bad and were NOT "
            f"removed. Check the GC task log for filenames."
        )
    return md


# ---------- pbs_run_gc -------------------------------------------------------


class RunGcInput(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)
    confirm: bool = Field(default=False)
    reason: str | None = Field(default=None, max_length=200)


def run_gc_handler(client: Any, params: RunGcInput) -> str:
    client.require_write("pbs_run_gc")
    if not params.confirm:
        return (
            "Refused: pbs_run_gc requires confirm=true. GC is read-mostly "
            "but disk-intensive and can take hours on large datastores."
        )
    ds = client.resolve_datastore(params.datastore)
    upid = client.post(f"/admin/datastore/{ds}/gc")
    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: GC started on datastore `{ds}`{reason_suffix}.\n\n"
        f"UPID: `{upid}`\n\n"
        f"Track with `pbs_get_task_status` or `pbs_get_task_log`. "
        f"GC scans the entire chunk store; expect minutes to hours."
    )


# ---------- tool specs -------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_gc_status",
        "title": "PBS garbage collection status",
        "description": (
            "Return the last garbage-collection statistics for a datastore: "
            "bytes referenced, pending, removed, plus any flagged-bad "
            "chunks. Read-only."
        ),
        "input_model": GcStatusInput,
        "handler": gc_status_handler,
    },
    {
        "name": "pbs_run_gc",
        "title": "Run PBS garbage collection",
        "description": (
            "Trigger a garbage-collection run on a datastore. GC walks every "
            "chunk and frees those no longer referenced by any snapshot. "
            "Async — returns a UPID immediately. Requires PBS_ALLOW_WRITE=true "
            "and confirm=true."
        ),
        "input_model": RunGcInput,
        "handler": run_gc_handler,
    },
]
