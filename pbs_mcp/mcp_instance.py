"""Shared FastMCP server instance.

All tool modules import `mcp` from here so they register with the same
server. Mirrors the proxmox-mcp pattern: one singleton, decorator-based
tool registration.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pbs-mcp")
