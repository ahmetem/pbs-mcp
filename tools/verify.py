"""Verify task: re-read every chunk of a backup to detect bitrot or corruption."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------- pbs_run_verify ---------------------------------------------------


class RunVerifyInput(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)
    backup_type: str | None = Field(
        default=None,
        description="Restrict to one type: 'vm', 'ct', or 'host'.",
        pattern=r"^(vm|ct|host)$",
    )
    backup_id: str | None = Field(
        default=None,
        description="Restrict to one ID (requires backup_type).",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    backup_time: str | None = Field(
        default=None,
        description=(
            "Restrict to one snapshot (requires backup_type + backup_id). "
            "Format: '2026-05-25T10:54:07Z'."
        ),
        max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
    )
    ignore_verified: bool = Field(
        default=True,
        description=(
            "If true, skip snapshots that were verified successfully within "
            "the past `outdated_after` days. Default true."
        ),
    )
    outdated_after: int = Field(
        default=30,
        ge=1,
        le=3650,
        description=(
            "When ignore_verified=true, re-verify snapshots older than this "
            "many days since their last successful verify."
        ),
    )
    confirm: bool = Field(default=False)
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_filter_hierarchy(self) -> "RunVerifyInput":
        if self.backup_id and not self.backup_type:
            raise ValueError("backup_id requires backup_type")
        if self.backup_time and not self.backup_id:
            raise ValueError("backup_time requires backup_type and backup_id")
        return self


def run_verify_handler(client: Any, params: RunVerifyInput) -> str:
    client.require_write("pbs_run_verify")
    if not params.confirm:
        return (
            "Refused: pbs_run_verify requires confirm=true. Verify is "
            "read-only against your data but can saturate the datastore "
            "disk for hours."
        )
    ds = client.resolve_datastore(params.datastore)

    body: dict[str, Any] = {
        "ignore-verified": params.ignore_verified,
        "outdated-after": params.outdated_after,
    }
    if params.backup_type:
        body["backup-type"] = params.backup_type
    if params.backup_id:
        body["backup-id"] = params.backup_id
    if params.backup_time:
        body["backup-time"] = params.backup_time

    upid = client.post(f"/admin/datastore/{ds}/verify", json_body=body)

    scope_bits = []
    if params.backup_type:
        scope_bits.append(params.backup_type)
    if params.backup_id:
        scope_bits.append(params.backup_id)
    if params.backup_time:
        scope_bits.append(params.backup_time)
    scope = "/".join(scope_bits) if scope_bits else "entire datastore"

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: verify started on `{ds}` scope `{scope}`{reason_suffix}.\n\n"
        f"UPID: `{upid}`\n\n"
        f"Track with `pbs_get_task_status` or `pbs_get_task_log`."
    )


# ---------- tool specs -------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_run_verify",
        "title": "Run PBS verify",
        "description": (
            "Trigger a verify task on a datastore. Verify re-reads every "
            "chunk and confirms it matches its expected hash, catching "
            "bitrot. By default skips snapshots that were verified OK in "
            "the past 30 days. Async — returns a UPID. Requires "
            "PBS_ALLOW_WRITE=true and confirm=true."
        ),
        "input_model": RunVerifyInput,
        "handler": run_verify_handler,
    },
]
