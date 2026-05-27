"""Prune: drop snapshots according to a retention policy."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .common import fmt_unix_ts, md_table


def _keep_fields(p: "_PruneBase") -> dict[str, Any]:
    """Extract the keep-* params as PBS expects them."""
    out: dict[str, Any] = {}
    if p.keep_last is not None:
        out["keep-last"] = p.keep_last
    if p.keep_hourly is not None:
        out["keep-hourly"] = p.keep_hourly
    if p.keep_daily is not None:
        out["keep-daily"] = p.keep_daily
    if p.keep_weekly is not None:
        out["keep-weekly"] = p.keep_weekly
    if p.keep_monthly is not None:
        out["keep-monthly"] = p.keep_monthly
    if p.keep_yearly is not None:
        out["keep-yearly"] = p.keep_yearly
    return out


class _PruneBase(BaseModel):
    datastore: str | None = Field(default=None, max_length=64)
    backup_type: str = Field(
        description="'vm', 'ct', or 'host'.", pattern=r"^(vm|ct|host)$"
    )
    backup_id: str = Field(
        description="VMID or hostname.", max_length=64, pattern=r"^[A-Za-z0-9._-]+$"
    )
    keep_last: int | None = Field(default=None, ge=0, le=1000)
    keep_hourly: int | None = Field(default=None, ge=0, le=1000)
    keep_daily: int | None = Field(default=None, ge=0, le=1000)
    keep_weekly: int | None = Field(default=None, ge=0, le=1000)
    keep_monthly: int | None = Field(default=None, ge=0, le=1000)
    keep_yearly: int | None = Field(default=None, ge=0, le=1000)

    @model_validator(mode="after")
    def _at_least_one_keep(self) -> "_PruneBase":
        if not any(
            v is not None
            for v in (
                self.keep_last,
                self.keep_hourly,
                self.keep_daily,
                self.keep_weekly,
                self.keep_monthly,
                self.keep_yearly,
            )
        ):
            raise ValueError(
                "At least one keep-* parameter is required. Use keep_last=0 "
                "explicitly if you really want to drop all snapshots."
            )
        return self


# ---------- pbs_prune_dry_run ------------------------------------------------


class PruneDryRunInput(_PruneBase):
    pass


def prune_dry_run_handler(client: Any, params: PruneDryRunInput) -> str:
    ds = client.resolve_datastore(params.datastore)
    body = _keep_fields(params)
    body["dry-run"] = True
    body["backup-type"] = params.backup_type
    body["backup-id"] = params.backup_id

    data = client.post(f"/admin/datastore/{ds}/prune", json_body=body)
    if not isinstance(data, list) or not data:
        return (
            f"_Prune dry-run for `{params.backup_type}/{params.backup_id}` "
            f"on `{ds}`: no snapshots in this group._"
        )

    kept_rows = []
    drop_rows = []
    for snap in data:
        time_str = fmt_unix_ts(snap.get("backup-time"))
        prot = "yes" if snap.get("protected") else "no"
        row = [time_str, prot]
        if snap.get("keep"):
            kept_rows.append(row)
        else:
            drop_rows.append(row)

    parts = [
        f"## Prune dry-run for `{params.backup_type}/{params.backup_id}` on `{ds}`",
        f"\nPolicy: " + ", ".join(f"{k}={v}" for k, v in _keep_fields(params).items()),
        f"\n**KEEP ({len(kept_rows)}):**",
    ]
    if kept_rows:
        parts.append(md_table(["Time (UTC)", "Protected"], kept_rows))
    else:
        parts.append("_(none — every snapshot would be dropped)_")

    parts.append(f"\n**WOULD DROP ({len(drop_rows)}):**")
    if drop_rows:
        parts.append(md_table(["Time (UTC)", "Protected"], drop_rows))
    else:
        parts.append("_(none)_")

    if drop_rows:
        parts.append(
            "\nTo actually drop these, call `pbs_prune` with the same "
            "parameters and confirm=true."
        )
    return "\n".join(parts)


# ---------- pbs_prune --------------------------------------------------------


class PruneInput(_PruneBase):
    confirm: bool = Field(default=False)
    reason: str | None = Field(default=None, max_length=200)


def prune_handler(client: Any, params: PruneInput) -> str:
    client.require_write("pbs_prune")
    if not params.confirm:
        return (
            "Refused: pbs_prune requires confirm=true. Run pbs_prune_dry_run "
            "first to see exactly what would be dropped."
        )
    ds = client.resolve_datastore(params.datastore)
    body = _keep_fields(params)
    body["backup-type"] = params.backup_type
    body["backup-id"] = params.backup_id

    data = client.post(f"/admin/datastore/{ds}/prune", json_body=body)
    if not isinstance(data, list):
        return f"_Unexpected prune response: {data!r}_"

    kept = [s for s in data if s.get("keep")]
    dropped = [s for s in data if not s.get("keep")]

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    summary = (
        f"OK: prune on `{params.backup_type}/{params.backup_id}` "
        f"of `{ds}`{reason_suffix}. Kept {len(kept)}, dropped {len(dropped)}."
    )
    if dropped:
        rows = [
            [fmt_unix_ts(s.get("backup-time")), "yes" if s.get("protected") else "no"]
            for s in dropped
        ]
        summary += "\n\n**Dropped:**\n" + md_table(
            ["Time (UTC)", "Protected"], rows
        )
    summary += (
        "\n\nChunks for dropped snapshots are freed by the next garbage "
        "collection — call `pbs_run_gc` to reclaim disk now."
    )
    return summary


# ---------- tool specs -------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_prune_dry_run",
        "title": "PBS prune dry-run",
        "description": (
            "Preview which snapshots in a backup group would be kept or "
            "dropped by a given retention policy. Specify keep-last / "
            "keep-hourly / keep-daily / keep-weekly / keep-monthly / "
            "keep-yearly (at least one). Read-only."
        ),
        "input_model": PruneDryRunInput,
        "handler": prune_dry_run_handler,
    },
    {
        "name": "pbs_prune",
        "title": "PBS prune",
        "description": (
            "Apply a retention policy and drop matching snapshots. The "
            "on-disk chunks aren't freed until the next garbage collection. "
            "Always run pbs_prune_dry_run first. Requires "
            "PBS_ALLOW_WRITE=true and confirm=true."
        ),
        "input_model": PruneInput,
        "handler": prune_handler,
    },
]
