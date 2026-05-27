"""Configuration: load .env once, expose typed accessors.

Pulled out of pbs_client into its own module to mirror proxmox-mcp.
"""
from __future__ import annotations

import os
from pathlib import Path


class PbsConfigError(RuntimeError):
    """Raised when required env vars are missing or malformed."""


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader — no python-dotenv dependency."""
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
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # Don't clobber existing env (Docker / systemd may set these explicitly)
        if key and key not in os.environ:
            os.environ[key] = value


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


# Load .env from the package's parent directory at import time.
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
_load_dotenv(_ENV_PATH)


PBS_HOST: str = os.environ.get("PBS_HOST", "").strip().rstrip("/")
PBS_TOKEN_ID: str = os.environ.get("PBS_TOKEN_ID", "").strip()
PBS_TOKEN_SECRET: str = os.environ.get("PBS_TOKEN_SECRET", "").strip()
PBS_NODE: str = os.environ.get("PBS_NODE", "pbs").strip() or "pbs"


def _verify_tls() -> bool | str:
    """verify_tls can be: True / False / path to CA bundle."""
    ca_bundle = os.environ.get("PBS_CA_BUNDLE", "").strip()
    if ca_bundle:
        return ca_bundle
    return _truthy(os.environ.get("PBS_VERIFY_TLS"), default=False)


PBS_VERIFY_TLS: bool | str = _verify_tls()


def _timeout() -> float:
    raw = os.environ.get("PBS_HTTP_TIMEOUT", "30").strip()
    try:
        return float(raw)
    except ValueError:
        return 30.0


PBS_HTTP_TIMEOUT: float = _timeout()
PBS_DEFAULT_DATASTORE: str | None = (
    os.environ.get("PBS_DEFAULT_DATASTORE", "").strip() or None
)
PBS_ALLOW_WRITE: bool = _truthy(os.environ.get("PBS_ALLOW_WRITE"), default=False)


def require_config() -> str | None:
    """Return a human-readable error string if required env vars are missing,
    or None if config looks complete. Tools call this first."""
    missing = [
        name
        for name, val in (
            ("PBS_HOST", PBS_HOST),
            ("PBS_TOKEN_ID", PBS_TOKEN_ID),
            ("PBS_TOKEN_SECRET", PBS_TOKEN_SECRET),
        )
        if not val
    ]
    if missing:
        return (
            f"Error: Missing required env vars: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill in values."
        )
    return None


def auth_header() -> dict[str, str]:
    return {
        "Authorization": f"PBSAPIToken={PBS_TOKEN_ID}:{PBS_TOKEN_SECRET}",
    }


def base_url() -> str:
    return f"{PBS_HOST}/api2/json"


def resolve_datastore(datastore: str | None) -> str:
    """Pick datastore: explicit arg > default > raise."""
    if datastore:
        return datastore
    if PBS_DEFAULT_DATASTORE:
        return PBS_DEFAULT_DATASTORE
    raise PbsConfigError(
        "No datastore specified and PBS_DEFAULT_DATASTORE is not set."
    )


def require_write(tool_name: str) -> str | None:
    """Return error string if writes are disabled, else None."""
    if not PBS_ALLOW_WRITE:
        return (
            f"Refused: '{tool_name}' is a write operation, but "
            f"PBS_ALLOW_WRITE is not true. Set PBS_ALLOW_WRITE=true in "
            f".env and restart the MCP server to enable write tools."
        )
    return None
