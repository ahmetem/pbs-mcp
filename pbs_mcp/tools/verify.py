"""Verify task: re-read every chunk of a backup to detect bitrot or corruption."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pbs_mcp import config, http_client
from pbs_mcp.mcp_instance import mcp


class RunVerifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: Optional[str] = Field(
        default=None,
        description="Restrict to one type: 'vm', 'ct', or 'host'.",
        pattern=r"^(vm|ct|host)$",
    )
    backup_id: Optional[str] = Field(
        default=None,
        description="Restrict to one ID (requires backup_type).",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    backup_time: Optional[str] = Field(
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
    reason: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_filter_hierarchy(self) -> "RunVerifyInput":
        if self.backup_id and not self.backup_type:
            raise ValueError("backup_id requires backup_type")
        if self.backup_time and not self.backup_id:
            raise ValueError("backup_time requires backup_type and backup_id")
        return self


@mcp.tool(
    name="pbs_run_verify",
    annotations={
        "title": "Run PBS verify",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def pbs_run_verify(params: RunVerifyInput) -> str:
    """Trigger a verify task. Verify re-reads every chunk and confirms it
    matches its expected hash, catching bitrot. By default skips snapshots
    that were verified OK in the past 30 days. Async — returns a UPID.
    Requires PBS_ALLOW_WRITE=true and confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_run_verify")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_run_verify requires confirm=true. Verify is "
            "read-only against your data but can saturate the datastore "
            "disk for hours."
        )
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"

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

    try:
        upid = await http_client.post(
            f"/admin/datastore/{ds}/verify", json_body=body
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

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
