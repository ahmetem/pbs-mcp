"""Backup group / snapshot listing and snapshot deletion tools."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .common import fmt_bytes, fmt_unix_ts, md_table


_BACKUP_TYPE_RE = re.compile(r"^(vm|ct|host)$")
_BACKUP_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# UTC ISO-8601 with Z (the format PBS uses internally for backup-time strings)
_BACKUP_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


# ---------- pbs_list_groups --------------------------------------------------


class ListGroupsInput(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)


def list_groups_handler(client: Any, params: ListGroupsInput) -> str:
    ds = client.resolve_datastore(params.datastore)
    data = client.get(f"/admin/datastore/{ds}/groups")
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

    md = (
        f"## PBS groups on `{ds}`\n\n"
        + md_table(
            ["Group", "Snapshots", "Last backup (UTC)", "Owner", "Files"], rows
        )
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
    datastore: str | None = Field(default=None, max_length=64)
    backup_type: str | None = Field(
        default=None,
        description="Filter by 'vm', 'ct', or 'host'.",
        pattern=r"^(vm|ct|host)$",
    )
    backup_id: str | None = Field(
        default=None,
        description="Filter by backup ID (VMID or hostname). Requires backup_type.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )


def list_snapshots_handler(client: Any, params: ListSnapshotsInput) -> str:
    ds = client.resolve_datastore(params.datastore)
    query: dict[str, Any] = {}
    if params.backup_type:
        query["backup-type"] = params.backup_type
    if params.backup_id:
        if not params.backup_type:
            raise ValueError("backup_id requires backup_type")
        query["backup-id"] = params.backup_id

    data = client.get(
        f"/admin/datastore/{ds}/snapshots", params=query or None
    )
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

    return (
        f"## PBS snapshots on `{ds}`\n\n"
        + md_table(
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
    )


# ---------- pbs_forget_snapshot ----------------------------------------------


class ForgetSnapshotInput(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)
    backup_type: str = Field(
        description="'vm', 'ct', or 'host'.", pattern=r"^(vm|ct|host)$"
    )
    backup_id: str = Field(
        description="VMID or hostname.", max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
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
    reason: str | None = Field(default=None, max_length=200)


def forget_snapshot_handler(client: Any, params: ForgetSnapshotInput) -> str:
    client.require_write("pbs_forget_snapshot")
    if not params.confirm:
        return (
            "Refused: pbs_forget_snapshot requires confirm=true. "
            "This deletes the snapshot permanently."
        )
    ds = client.resolve_datastore(params.datastore)
    # PBS uses query params on DELETE for this endpoint
    client.delete(
        f"/admin/datastore/{ds}/snapshots",
        params={
            "backup-type": params.backup_type,
            "backup-id": params.backup_id,
            "backup-time": params.backup_time,
        },
    )
    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: snapshot `{params.backup_type}/{params.backup_id}/"
        f"{params.backup_time}` removed from `{ds}`{reason_suffix}. "
        f"Chunks freed by next garbage collection."
    )


# ---------- tool specs -------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_list_groups",
        "title": "List PBS backup groups",
        "description": (
            "List every backup group on a datastore with its snapshot count, "
            "last-backup time, owner, and file count. Groups with zero files "
            "are flagged as likely corrupt. Read-only."
        ),
        "input_model": ListGroupsInput,
        "handler": list_groups_handler,
    },
    {
        "name": "pbs_list_snapshots",
        "title": "List PBS snapshots",
        "description": (
            "List snapshots on a datastore with size, file count, protected "
            "flag, last verify state, and owner. Optional filter by "
            "backup_type + backup_id. Read-only."
        ),
        "input_model": ListSnapshotsInput,
        "handler": list_snapshots_handler,
    },
    {
        "name": "pbs_forget_snapshot",
        "title": "Delete a PBS snapshot",
        "description": (
            "Permanently delete one snapshot from a datastore. The on-disk "
            "chunks are freed by the next garbage collection, not "
            "immediately. Requires PBS_ALLOW_WRITE=true and confirm=true. "
            "Useful for cleaning up corrupt or interrupted backups."
        ),
        "input_model": ForgetSnapshotInput,
        "handler": forget_snapshot_handler,
    },
]
