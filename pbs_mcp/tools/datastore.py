"""Datastore listing and status tools."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_bytes, md_table
from pbs_mcp.mcp_instance import mcp


# ---------- pbs_list_datastores ----------------------------------------------


class ListDatastoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


@mcp.tool(
    name="pbs_list_datastores",
    annotations={
        "title": "List PBS datastores",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_datastores(params: ListDatastoresInput) -> str:
    """List every configured PBS datastore with its path and any scheduled
    GC/prune jobs."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        data = await http_client.get("/config/datastore")
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        return "_No datastores configured._"

    rows = []
    for ds in data:
        rows.append(
            [
                ds.get("name", "?"),
                ds.get("path", "-"),
                ds.get("comment", "") or "-",
                ds.get("gc-schedule", "-"),
                ds.get("prune-schedule", "-"),
            ]
        )
    return "## PBS datastores\n\n" + md_table(
        ["Name", "Path", "Comment", "GC schedule", "Prune schedule"], rows
    )


# ---------- pbs_datastore_status ---------------------------------------------


class DatastoreStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(
        default=None,
        description="Datastore name. Omit to use PBS_DEFAULT_DATASTORE.",
        max_length=64,
    )


@mcp.tool(
    name="pbs_datastore_status",
    annotations={
        "title": "PBS datastore status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_datastore_status(params: DatastoreStatusInput) -> str:
    """Total / used / available bytes for one datastore."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        data = await http_client.get(f"/admin/datastore/{ds}/status")
    except Exception as exc:
        return http_client.format_http_error(exc)

    total = data.get("total", 0) or 0
    used = data.get("used", 0) or 0
    avail = data.get("avail", 0) or 0
    pct = (used / total * 100.0) if total else 0.0

    lines = [
        f"## Datastore `{ds}` — status",
        "",
        md_table(
            ["Metric", "Value"],
            [
                ["Total", fmt_bytes(total)],
                ["Used", f"{fmt_bytes(used)} ({pct:.1f}%)"],
                ["Available", fmt_bytes(avail)],
            ],
        ),
    ]
    # PBS returns gc-status inline in newer versions; surface the UPID
    gc_status = data.get("gc-status") or data.get("gcStatus")
    if isinstance(gc_status, dict):
        upid = gc_status.get("upid")
        if upid:
            lines += ["", f"Last GC UPID: `{upid}`"]
    return "\n".join(lines)
