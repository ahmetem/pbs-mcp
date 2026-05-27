"""pbs-mcp — MCP server entry point.

Wires up the 13 tool handlers against a single PbsClient loaded from .env,
exposes them over stdio.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from pydantic import BaseModel, ValidationError

from pbs_client import PbsApiError, PbsClient, PbsConfigError
from tools import datastore, gc, prune, snapshots, tasks, verify

_ALL_TOOL_SPECS: list[dict[str, Any]] = (
    datastore.TOOL_SPECS
    + snapshots.TOOL_SPECS
    + tasks.TOOL_SPECS
    + gc.TOOL_SPECS
    + verify.TOOL_SPECS
    + prune.TOOL_SPECS
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pbs-mcp] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("pbs-mcp")


def _tool_to_mcp(spec: dict[str, Any]) -> Tool:
    model: type[BaseModel] = spec["input_model"]
    return Tool(
        name=spec["name"],
        title=spec.get("title"),
        description=spec["description"],
        inputSchema=model.model_json_schema(),
    )


def build_server(client: PbsClient) -> Server:
    server: Server = Server("pbs-mcp")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [_tool_to_mcp(spec) for spec in _ALL_TOOL_SPECS]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        spec = next((s for s in _ALL_TOOL_SPECS if s["name"] == name), None)
        if spec is None:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        model: type[BaseModel] = spec["input_model"]
        try:
            parsed = model.model_validate(arguments or {})
        except ValidationError as e:
            return [TextContent(type="text", text=f"Invalid arguments for {name}:\n{e}")]
        try:
            result = spec["handler"](client, parsed)
        except PbsConfigError as e:
            return [TextContent(type="text", text=f"Config error: {e}")]
        except PbsApiError as e:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"PBS API error on {name}: HTTP {e.status_code}\n\n"
                        f"URL: {e.url}\n\nBody:\n{e.body[:1500]}"
                    ),
                )
            ]
        except ValueError as e:
            return [TextContent(type="text", text=f"Invalid input for {name}: {e}")]
        except Exception as e:  # pragma: no cover - last-resort guardrail
            log.exception("Unhandled error in tool %s", name)
            return [TextContent(type="text", text=f"Unhandled error in {name}: {e}")]
        if not isinstance(result, str):
            result = str(result)
        return [TextContent(type="text", text=result)]

    return server


async def main() -> None:
    try:
        client = PbsClient.from_env()
    except PbsConfigError as e:
        log.error("Startup failed: %s", e)
        sys.exit(1)
    log.info(
        "pbs-mcp ready: host=%s node=%s default_datastore=%s allow_write=%s",
        client.host,
        client.node,
        client.default_datastore,
        client.allow_write,
    )
    log.info("Registered %d tools", len(_ALL_TOOL_SPECS))
    server = build_server(client)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
