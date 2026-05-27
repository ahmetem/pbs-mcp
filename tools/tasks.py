"""Task tracking tools. PBS runs verify/GC/prune asynchronously and returns
a UPID string. These tools let you check status, tail the log, or browse
recent tasks."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from .common import fmt_unix_ts, md_table, truncate


# UPID format: UPID:node:pid_hex:pstart_hex:starttime_hex:type:id:user@realm[!token]:
_UPID_RE = re.compile(
    r"^UPID:[A-Za-z0-9._-]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:"
    r"[A-Za-z0-9_-]+:[^:]*:[A-Za-z0-9._@!-]+:$"
)


def _validate_upid(upid: str) -> None:
    if not _UPID_RE.match(upid):
        raise ValueError(
            f"Malformed UPID: {upid!r}. Expected 'UPID:node:...:user@realm:' format."
        )


# ---------- pbs_get_task_status ----------------------------------------------


class GetTaskStatusInput(BaseModel):
    upid: str = Field(
        description=(
            "Full UPID string as returned by run_gc / run_verify / prune. "
            "Format: 'UPID:node:hex:hex:hex:type:id:user@realm:'."
        ),
        max_length=256,
        min_length=10,
    )


def get_task_status_handler(client: Any, params: GetTaskStatusInput) -> str:
    _validate_upid(params.upid)
    data = client.task_status(params.upid)
    if not isinstance(data, dict):
        return f"_Unexpected task status payload: {data!r}_"

    status = data.get("status", "?")
    exitstatus = data.get("exitstatus")
    state_line = f"**{status}**"
    if exitstatus:
        state_line += f"  →  exit: `{exitstatus}`"

    rows = [
        ["Type", data.get("type", "-")],
        ["ID", data.get("id", "-")],
        ["Node", data.get("node", "-")],
        ["User", data.get("user", "-")],
        ["Token", data.get("tokenid", "-") or "-"],
        ["PID", data.get("pid", "-")],
        ["Started", fmt_unix_ts(data.get("starttime"))],
    ]
    return (
        f"## PBS task status\n\n{state_line}\n\n"
        + md_table(["Field", "Value"], rows)
    )


# ---------- pbs_get_task_log -------------------------------------------------


class GetTaskLogInput(BaseModel):
    upid: str = Field(max_length=256, min_length=10)
    start: int = Field(
        default=0,
        ge=0,
        description="Line number to start from (0-indexed).",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=5000,
        description="Max lines to fetch.",
    )


def get_task_log_handler(client: Any, params: GetTaskLogInput) -> str:
    _validate_upid(params.upid)
    data = client.task_log(
        params.upid, start=params.start, limit=params.limit
    )
    if not isinstance(data, list) or not data:
        return f"_No log lines for UPID (start={params.start}, limit={params.limit})._"
    # Each entry: {"n": <line_no>, "t": "<log text>"}
    lines = [
        f"{entry.get('n', '?'):>5}  {entry.get('t', '')}"
        for entry in data
        if isinstance(entry, dict)
    ]
    body = "\n".join(lines)
    return truncate(f"## Task log\n\n```\n{body}\n```", limit=8000)


# ---------- pbs_list_tasks ---------------------------------------------------


class ListTasksInput(BaseModel):
    typefilter: str | None = Field(
        default=None,
        description=(
            "Filter by task type (e.g. 'verify', 'garbage_collection', "
            "'prune', 'backup'). Omit for all types."
        ),
        max_length=64,
        pattern=r"^[a-z_]+$",
    )
    running: bool | None = Field(
        default=None,
        description="If true, only return currently running tasks.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Max tasks to return.",
    )
    errors_only: bool = Field(
        default=False,
        description="If true, only show tasks with a non-OK exitstatus.",
    )


def list_tasks_handler(client: Any, params: ListTasksInput) -> str:
    query: dict[str, Any] = {"limit": params.limit}
    if params.typefilter:
        query["typefilter"] = params.typefilter
    if params.running is not None:
        # PBS uses 1/0 for booleans on this endpoint
        query["running"] = 1 if params.running else 0
    if params.errors_only:
        query["errors"] = 1

    data = client.get(
        f"/nodes/{client.node}/tasks", params=query
    )
    if not isinstance(data, list) or not data:
        return "_No tasks match the given filters._"

    rows = []
    for t in data:
        status = t.get("status", "?")
        exitstatus = t.get("exitstatus") or ""
        if exitstatus and exitstatus != "OK":
            status_cell = f"{status} ({exitstatus[:30]})"
        else:
            status_cell = status
        rows.append(
            [
                t.get("type", "-"),
                t.get("id", "-"),
                fmt_unix_ts(t.get("starttime")),
                status_cell,
                t.get("user", "-"),
                # short UPID prefix is enough to identify; full one in detail call
                (t.get("upid") or "")[:55] + "...",
            ]
        )
    return (
        "## Recent PBS tasks\n\n"
        + md_table(
            ["Type", "ID", "Started (UTC)", "Status", "User", "UPID (truncated)"],
            rows,
        )
        + "\n\nUse `pbs_get_task_status` or `pbs_get_task_log` with the full UPID."
    )


# ---------- tool specs -------------------------------------------------------

TOOL_SPECS = [
    {
        "name": "pbs_get_task_status",
        "title": "Get PBS task status",
        "description": (
            "Return current state of a PBS task (running / stopped) plus "
            "exit status if finished. Identify the task by its full UPID "
            "string (returned by run_gc, run_verify, prune, etc). Read-only."
        ),
        "input_model": GetTaskStatusInput,
        "handler": get_task_status_handler,
    },
    {
        "name": "pbs_get_task_log",
        "title": "Get PBS task log",
        "description": (
            "Fetch log lines from a PBS task. Supports pagination via start "
            "and limit. Useful for watching verify or GC progress. Read-only."
        ),
        "input_model": GetTaskLogInput,
        "handler": get_task_log_handler,
    },
    {
        "name": "pbs_list_tasks",
        "title": "List recent PBS tasks",
        "description": (
            "Browse recent PBS tasks with optional type filter, running-only "
            "flag, and errors-only flag. Returns truncated UPIDs; pass the "
            "full UPID to pbs_get_task_status for details. Read-only."
        ),
        "input_model": ListTasksInput,
        "handler": list_tasks_handler,
    },
]
