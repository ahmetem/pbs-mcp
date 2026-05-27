"""Async HTTP helpers for the Proxmox Backup Server REST API.

Built on httpx.AsyncClient — no blocking I/O on the asyncio loop.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Optional

import httpx

from pbs_mcp import config


def _client() -> httpx.AsyncClient:
    """Build a one-shot AsyncClient. Used inside `async with` blocks so
    connections are closed after each call — simpler lifetime than a
    long-lived session, and PBS keepalives are short anyway."""
    return httpx.AsyncClient(
        base_url=config.base_url(),
        headers=config.auth_header(),
        verify=config.PBS_VERIFY_TLS,
        timeout=config.PBS_HTTP_TIMEOUT,
    )


def format_http_error(exc: Exception) -> str:
    """Translate httpx exceptions into the markdown error strings tools
    return to the LLM."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:500]
        if status == 401:
            return (
                "Error: PBS authentication failed (HTTP 401). "
                "Check PBS_TOKEN_ID and PBS_TOKEN_SECRET."
            )
        if status == 403:
            return (
                f"Error: PBS permission denied (HTTP 403). "
                f"Token lacks the required privilege.\n\n{body}"
            )
        if status == 404:
            return f"Error: PBS resource not found (HTTP 404).\n\n{body}"
        return f"Error: PBS HTTP {status}.\n\n{body}"
    if isinstance(exc, httpx.ConnectError):
        return f"Error: cannot connect to {config.PBS_HOST}: {exc}"
    if isinstance(exc, httpx.TimeoutException):
        return f"Error: PBS request timed out after {config.PBS_HTTP_TIMEOUT}s"
    return f"Error: {type(exc).__name__}: {exc}"


def _unwrap(payload: Any) -> Any:
    """PBS wraps every response in {'data': ...}. Tools want the inner value."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


async def get(path: str, params: Optional[dict] = None) -> Any:
    async with _client() as c:
        r = await c.get(path, params=params)
        r.raise_for_status()
        return _unwrap(r.json())


async def post(
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Any:
    async with _client() as c:
        r = await c.post(path, params=params, json=json_body)
        r.raise_for_status()
        return _unwrap(r.json())


async def delete(path: str, params: Optional[dict] = None) -> Any:
    async with _client() as c:
        r = await c.delete(path, params=params)
        r.raise_for_status()
        return _unwrap(r.json())


# ----- task helpers ---------------------------------------------------------


def encode_upid(upid: str) -> str:
    """PBS task endpoints want the UPID URL-encoded (colons → %3A)."""
    return urllib.parse.quote(upid, safe="")


async def task_status(upid: str) -> Any:
    encoded = encode_upid(upid)
    return await get(f"/nodes/{config.PBS_NODE}/tasks/{encoded}/status")


async def task_log(
    upid: str,
    *,
    start: int | None = None,
    limit: int | None = None,
) -> Any:
    encoded = encode_upid(upid)
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if limit is not None:
        params["limit"] = limit
    return await get(
        f"/nodes/{config.PBS_NODE}/tasks/{encoded}/log",
        params=params or None,
    )
