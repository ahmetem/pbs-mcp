"""Backup group / snapshot listing and snapshot deletion tools."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_bytes, fmt_unix_ts, md_table
from pbs_mcp.mcp_instance import mcp


# ---------- pbs_list_groups --------------------------------------------------


class ListGroupsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)


@mcp.tool(
    name="pbs_list_groups",
    annotations={
        "title": "List PBS backup groups",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_groups(params: ListGroupsInput) -> str:
    """List every backup group on a datastore with its snapshot count,
    last-backup time, owner, and file count. Groups with zero files are
    flagged as likely corrupt."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        data = await http_client.get(f"/admin/datastore/{ds}/groups")
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        return f"_No backup groups on datastore `{ds}`._"

    rows = []
    corrupt_count = 0
    for grp in data:
        files = grp.get("files") or []
        # A group with an empty `files` array usually means every snapshot is
        # corrupt (missing index.json.blob). Flag that visibly.
        marker = "" if files else " ⚠️"
        if not files:
            corrupt_count += 1
        rows.append(
            [
                f"{grp.get('backup-type', '?')}/{grp.get('backup-id', '?')}{marker}",
                grp.get("backup-count", 0),
                fmt_unix_ts(grp.get("last-backup")),
                grp.get("owner", "-"),
                len(files),
            ]
        )

    md = f"## PBS groups on `{ds}`\n\n" + md_table(
        ["Group", "Snapshots", "Last backup (UTC)", "Owner", "Files"], rows
    )
    if corrupt_count:
        md += (
            f"\n\n⚠️  {corrupt_count} group(s) have no manifest files — "
            f"likely corrupt or interrupted backups. Run `pbs_run_verify` "
            f"to confirm, then `pbs_forget_snapshot` to clean up."
        )
    return md


# ---------- pbs_list_snapshots -----------------------------------------------


class ListSnapshotsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: Optional[str] = Field(
        default=None,
        description="Filter by 'vm', 'ct', or 'host'.",
        pattern=r"^(vm|ct|host)$",
    )
    backup_id: Optional[str] = Field(
        default=None,
        description="Filter by backup ID (VMID or hostname). Requires backup_type.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )


@mcp.tool(
    name="pbs_list_snapshots",
    annotations={
        "title": "List PBS snapshots",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_snapshots(params: ListSnapshotsInput) -> str:
    """List snapshots on a datastore with size, file count, protected flag,
    last verify state, and owner. Optional filter by backup_type + backup_id."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    query: dict[str, Any] = {}
    if params.backup_type:
        query["backup-type"] = params.backup_type
    if params.backup_id:
        if not params.backup_type:
            return "Error: backup_id requires backup_type."
        query["backup-id"] = params.backup_id
    try:
        data = await http_client.get(
            f"/admin/datastore/{ds}/snapshots", params=query or None
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        scope = (
            f"`{params.backup_type}/{params.backup_id}`"
            if params.backup_id
            else f"type `{params.backup_type}`" if params.backup_type else "any"
        )
        return f"_No snapshots on `{ds}` matching {scope}._"

    rows = []
    for snap in data:
        files = snap.get("files") or []
        total_size = snap.get("size") or sum(
            f.get("size") or 0 for f in files if isinstance(f, dict)
        )
        verification = snap.get("verification") or {}
        v_state = verification.get("state") if isinstance(verification, dict) else None
        protected = "yes" if snap.get("protected") else "no"
        rows.append(
            [
                snap.get("backup-type", "?"),
                snap.get("backup-id", "?"),
                fmt_unix_ts(snap.get("backup-time")),
                fmt_bytes(total_size),
                len(files),
                protected,
                v_state or "-",
                snap.get("owner", "-"),
            ]
        )

    return f"## PBS snapshots on `{ds}`\n\n" + md_table(
        [
            "Type",
            "ID",
            "Time (UTC)",
            "Size",
            "Files",
            "Protected",
            "Verify",
            "Owner",
        ],
        rows,
    )


# ---------- pbs_forget_snapshot ----------------------------------------------


class ForgetSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: str = Field(
        description="'vm', 'ct', or 'host'.", pattern=r"^(vm|ct|host)$"
    )
    backup_id: str = Field(
        description="VMID or hostname.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    backup_time: str = Field(
        description=(
            "Snapshot timestamp in PBS ISO format, e.g. '2026-05-25T10:54:07Z'. "
            "Get from pbs_list_snapshots (the 'Time' column gives this format)."
        ),
        max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
    )
    confirm: bool = Field(default=False, description="Required.")
    reason: Optional[str] = Field(default=None, max_length=200)


@mcp.tool(
    name="pbs_forget_snapshot",
    annotations={
        "title": "Delete a PBS snapshot",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def pbs_forget_snapshot(params: ForgetSnapshotInput) -> str:
    """Permanently delete one snapshot. The on-disk chunks are freed by the
    next garbage collection. Requires PBS_ALLOW_WRITE=true and confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_forget_snapshot")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_forget_snapshot requires confirm=true. "
            "This deletes the snapshot permanently."
        )
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        await http_client.delete(
            f"/admin/datastore/{ds}/snapshots",
            params={
                "backup-type": params.backup_type,
                "backup-id": params.backup_id,
                "backup-time": params.backup_time,
            },
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: snapshot `{params.backup_type}/{params.backup_id}/"
        f"{params.backup_time}` removed from `{ds}`{reason_suffix}. "
        f"Chunks freed by next garbage collection."
    )
