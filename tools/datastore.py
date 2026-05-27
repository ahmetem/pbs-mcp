"""Datastore listing and status tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .common import fmt_bytes, md_table


# ---------- pbs_list_datastores ----------------------------------------------


class ListDatastoresInput(BaseModel):
    pass


def list_datastores_handler(client: Any, params: ListDatastoresInput) -> str:
    """List every configured datastore (from /config/datastore)."""
    data = client.get("/config/datastore")
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
    return (
        "## PBS datastores\n\n"
        + md_table(
            ["Name", "Path", "Comment", "GC schedule", "Prune schedule"], rows
        )
    )


# ---------- pbs_datastore_status ---------------------------------------------


class DatastoreStatusInput(BaseModel):
    datastore: str | None = Field(
        default=None,
        description="Datastore name. Omit to use PBS_DEFAULT_DATASTORE.",
        max_length=64,
    )


def datastore_status_handler(client: Any, params: DatastoreStatusInput) -> str:
    """Return usage stats for one datastore."""
    ds = client.resolve_datastore(params.datastore)
    data = client.get(f"/admin/datastore/{ds}/status")
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
    # PBS also returns gc-status fields inline in newer versions; surface
    # them when present so users see GC freshness without a second call.
    gc_status = data.get("gc-status") or data.get("gcStatus")
    if isinstance(gc_status, dict):
        upid = gc_status.get("upid")
        if upid:
            lines += ["", f"Last GC UPID: `{upid}`"]
    return "\n".join(lines)


# ---------- tool metadata ----------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_list_datastores",
        "title": "List PBS datastores",
        "description": (
            "List every configured PBS datastore with its path and any "
            "scheduled GC/prune jobs from the global config. Read-only."
        ),
        "input_model": ListDatastoresInput,
        "handler": list_datastores_handler,
    },
    {
        "name": "pbs_datastore_status",
        "title": "PBS datastore status",
        "description": (
            "Total / used / available bytes for one datastore. Pulls from "
            "/admin/datastore/{ds}/status. Read-only."
        ),
        "input_model": DatastoreStatusInput,
        "handler": datastore_status_handler,
    },
]
