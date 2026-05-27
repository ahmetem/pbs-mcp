"""
pbs_client.py — Thin REST wrapper for Proxmox Backup Server (PBS) API.

Designed to be the single transport surface used by every tool in `tools/`.
Goals:
  * One configured client per process (load from .env once)
  * Consistent error messages — PBS returns plain text in some failure paths
    (e.g. "permission check failed", "backup owner check failed") and JSON
    in others; we normalize to PbsApiError with the raw body attached
  * No magic: tools build endpoint paths and parameters themselves and call
    `client.get(...)`, `client.post(...)`. The wrapper does auth, TLS, timeout,
    and parsing. It does not know about specific endpoints.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import urllib3


class PbsConfigError(RuntimeError):
    """Raised when required env vars are missing or malformed."""


class PbsApiError(RuntimeError):
    """Raised when the PBS API returns a non-2xx response."""

    def __init__(self, status_code: int, body: str, url: str):
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(f"PBS API {status_code} on {url}: {body[:500]}")


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no python-dotenv dependency, fewer surprises."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # strip surrounding quotes if present
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # do not clobber existing env (Docker / systemd may set these explicitly)
        if key and key not in os.environ:
            os.environ[key] = value


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


class PbsClient:
    """REST client for PBS configured from environment variables."""

    def __init__(
        self,
        host: str,
        token_id: str,
        token_secret: str,
        node: str,
        verify_tls: bool | str = False,
        timeout: float = 30.0,
        default_datastore: str | None = None,
        allow_write: bool = False,
    ) -> None:
        self.host = host.rstrip("/")
        self.token_id = token_id
        self.token_secret = token_secret
        self.node = node
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.default_datastore = default_datastore
        self.allow_write = allow_write

        self._session = requests.Session()
        self._session.headers["Authorization"] = (
            f"PBSAPIToken={token_id}:{token_secret}"
        )
        # Silence the noisy self-signed cert warning when verify=False.
        if verify_tls is False:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # ----------------------------------------------------------- factory

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "PbsClient":
        """Build a client from environment + optional .env file."""
        if env_path is None:
            # pyproject.toml / .env live alongside this file
            env_path = Path(__file__).resolve().parent / ".env"
        _load_dotenv(env_path)

        host = os.environ.get("PBS_HOST", "").strip()
        token_id = os.environ.get("PBS_TOKEN_ID", "").strip()
        token_secret = os.environ.get("PBS_TOKEN_SECRET", "").strip()
        node = os.environ.get("PBS_NODE", "pbs").strip() or "pbs"

        missing = [
            name
            for name, val in (
                ("PBS_HOST", host),
                ("PBS_TOKEN_ID", token_id),
                ("PBS_TOKEN_SECRET", token_secret),
            )
            if not val
        ]
        if missing:
            raise PbsConfigError(
                f"Missing required env vars: {', '.join(missing)}. "
                f"Copy .env.example to .env and fill in values."
            )

        # verify_tls can be: 'true' / 'false' / path to CA bundle
        verify_raw = os.environ.get("PBS_VERIFY_TLS", "false").strip()
        ca_bundle = os.environ.get("PBS_CA_BUNDLE", "").strip()
        if ca_bundle:
            verify_tls: bool | str = ca_bundle
        else:
            verify_tls = _truthy(verify_raw, default=False)

        timeout_raw = os.environ.get("PBS_HTTP_TIMEOUT", "30").strip()
        try:
            timeout = float(timeout_raw)
        except ValueError:
            timeout = 30.0

        default_datastore = (
            os.environ.get("PBS_DEFAULT_DATASTORE", "").strip() or None
        )

        allow_write = _truthy(os.environ.get("PBS_ALLOW_WRITE"), default=False)

        return cls(
            host=host,
            token_id=token_id,
            token_secret=token_secret,
            node=node,
            verify_tls=verify_tls,
            timeout=timeout,
            default_datastore=default_datastore,
            allow_write=allow_write,
        )

    # ----------------------------------------------------------- helpers

    def resolve_datastore(self, datastore: str | None) -> str:
        """Pick datastore: explicit arg > default > raise."""
        if datastore:
            return datastore
        if self.default_datastore:
            return self.default_datastore
        raise PbsConfigError(
            "No datastore specified and PBS_DEFAULT_DATASTORE is not set."
        )

    def require_write(self, tool_name: str) -> None:
        """Gate every state-changing tool through PBS_ALLOW_WRITE."""
        if not self.allow_write:
            raise PbsConfigError(
                f"Write operation '{tool_name}' refused: PBS_ALLOW_WRITE is not "
                f"true. Set PBS_ALLOW_WRITE=true in .env and restart the MCP "
                f"server to enable write tools."
            )

    # ----------------------------------------------------------- HTTP

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Internal: send request, raise PbsApiError on non-2xx, return parsed
        `data` field (PBS wraps every response in {"data": ...})."""
        url = f"{self.host}/api2/json{path}"
        resp = self._session.request(
            method,
            url,
            params=params,
            json=json_body,
            verify=self.verify_tls,
            timeout=timeout or self.timeout,
        )
        if resp.status_code >= 400:
            raise PbsApiError(resp.status_code, resp.text, url)
        try:
            payload = resp.json()
        except ValueError:
            # 2xx without JSON body — unusual but harmless, return raw text
            return resp.text
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("POST", path, params=params, json_body=json_body)

    def delete(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("DELETE", path, params=params)

    # ----------------------------------------------------------- task helpers

    @staticmethod
    def encode_upid(upid: str) -> str:
        """PBS task endpoints want the UPID URL-encoded (colons → %3A)."""
        return upid.replace(":", "%3A")

    def task_status(self, upid: str) -> dict[str, Any]:
        encoded = self.encode_upid(upid)
        return self.get(f"/nodes/{self.node}/tasks/{encoded}/status")

    def task_log(
        self,
        upid: str,
        *,
        start: int | None = None,
        limit: int | None = None,
    ) -> Any:
        encoded = self.encode_upid(upid)
        params: dict[str, Any] = {}
        if start is not None:
            params["start"] = start
        if limit is not None:
            params["limit"] = limit
        return self.get(
            f"/nodes/{self.node}/tasks/{encoded}/log", params=params or None
        )
