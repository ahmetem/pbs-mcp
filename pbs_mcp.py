"""Compatibility shim for clients (e.g. Claude Desktop) that launch the
old single-file entry point `pbs_mcp.py`.

The implementation now lives in the `pbs_mcp` package. This file just
calls the package's main(), so existing MCP client configs keep working
without changes.
"""
from __future__ import annotations

from pbs_mcp.server import main

if __name__ == "__main__":
    main()
