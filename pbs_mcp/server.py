"""pbs-mcp FastMCP server entry point.

Configuration is loaded from environment variables (typically via .env):
    PBS_HOST              - PBS REST URL, e.g. https://192.168.1.27:8007
    PBS_TOKEN_ID          - API token id, e.g. root@pam!mcp
    PBS_TOKEN_SECRET      - API token secret (UUID)
    PBS_NODE              - node name in task UPIDs (default: 'pbs')
    PBS_VERIFY_TLS        - 'true' or 'false' (default: false)
    PBS_CA_BUNDLE         - optional path to a CA bundle PEM
    PBS_HTTP_TIMEOUT      - request timeout seconds (default: 30)
    PBS_DEFAULT_DATASTORE - used when a tool omits the `datastore` param
    PBS_ALLOW_WRITE       - 'true' enables run_gc/run_verify/prune/forget
"""
from __future__ import annotations

import logging
import sys

from pbs_mcp.mcp_instance import mcp

# Importing the tools subpackage registers every @mcp.tool decorator with `mcp`.
from pbs_mcp import tools  # noqa: F401


TOOLS = [
    # datastore
    "pbs_list_datastores",
    "pbs_datastore_status",
    # snapshots / groups
    "pbs_list_groups",
    "pbs_list_snapshots",
    "pbs_forget_snapshot",
    # tasks
    "pbs_get_task_status",
    "pbs_get_task_log",
    "pbs_list_tasks",
    # garbage collection
    "pbs_gc_status",
    "pbs_run_gc",
    # verify
    "pbs_run_verify",
    # prune
    "pbs_prune_dry_run",
    "pbs_prune",
]


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pbs-mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("pbs-mcp")


def main() -> None:
    log.info("pbs-mcp ready: %d tools registered", len(TOOLS))
    mcp.run()


if __name__ == "__main__":
    main()
