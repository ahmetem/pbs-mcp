"""Garbage collection tools.

GC frees disk space from chunks no longer referenced by any snapshot.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_bytes, md_table
from pbs_mcp.mcp_instance import mcp


# ---------- pbs_gc_status ----------------------------------------------------


class GcStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)


@mcp.tool(
    name="pbs_gc_status",
    annotations={
        "title": "PBS garbage collection status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_gc_status(params: GcStatusInput) -> str:
    """Return the last garbage-collection statistics: bytes referenced,
    pending, removed, plus any flagged-bad chunks."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        data = await http_client.get(f"/admin/datastore/{ds}/gc")
    except Exception as exc:
        return http_client.format_http_error(exc)

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
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    confirm: bool = Field(default=False)
    reason: Optional[str] = Field(default=None, max_length=200)


@mcp.tool(
    name="pbs_run_gc",
    annotations={
        "title": "Run PBS garbage collection",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def pbs_run_gc(params: RunGcInput) -> str:
    """Trigger a garbage-collection run. GC walks every chunk and frees
    those no longer referenced by any snapshot. Async — returns a UPID
    immediately. Requires PBS_ALLOW_WRITE=true and confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_run_gc")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_run_gc requires confirm=true. GC is read-mostly "
            "but disk-intensive and can take hours on large datastores."
        )
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        upid = await http_client.post(f"/admin/datastore/{ds}/gc")
    except Exception as exc:
        return http_client.format_http_error(exc)

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: GC started on datastore `{ds}`{reason_suffix}.\n\n"
        f"UPID: `{upid}`\n\n"
        f"Track with `pbs_get_task_status` or `pbs_get_task_log`. "
        f"GC scans the entire chunk store; expect minutes to hours."
    )
