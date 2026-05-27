"""pbs-mcp tool modules. Each module exposes one or more `_handler`
async functions plus a `TOOLS` list of mcp.types.Tool definitions, mirroring
the proxmox-mcp pattern."""

from . import datastore, gc, prune, snapshots, tasks, verify

__all__ = ["datastore", "gc", "prune", "snapshots", "tasks", "verify"]
