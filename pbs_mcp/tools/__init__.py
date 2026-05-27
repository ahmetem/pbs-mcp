"""pbs-mcp tool modules.

Importing this subpackage triggers every `@mcp.tool` decorator, which
registers the tool with the shared FastMCP instance defined in
`pbs_mcp.mcp_instance`.
"""
from __future__ import annotations

from pbs_mcp.tools import datastore  # noqa: F401
from pbs_mcp.tools import snapshots  # noqa: F401
from pbs_mcp.tools import tasks  # noqa: F401
from pbs_mcp.tools import gc  # noqa: F401
from pbs_mcp.tools import verify  # noqa: F401
from pbs_mcp.tools import prune  # noqa: F401
