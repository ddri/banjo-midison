# src/banjo/mcp_server.py
"""
MCP server wrapping banjo's MIDI generator.

Transport: stdio (for use from Claude Desktop or any MCP host).

Exposes:
  - generate_midi_progression: render a Roman numeral progression to MIDI.
  - set_output_directory: persist the output directory to ~/.banjo/config.json.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from banjo import config

logger = logging.getLogger("banjo.mcp")

server: Server = Server("banjo")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

SET_OUTPUT_DIRECTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": (
                "Absolute or ~-prefixed directory path. Created on first write. "
                "Persisted to ~/.banjo/config.json across server restarts."
            ),
        },
    },
    "required": ["path"],
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="generate_midi_progression",
            description="(stub — implemented in next task)",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="set_output_directory",
            description=(
                "Set the directory where generated MIDI files are written. "
                "The setting is persisted to ~/.banjo/config.json across "
                "Claude Desktop restarts."
            ),
            inputSchema=SET_OUTPUT_DIRECTORY_SCHEMA,
        ),
    ]


# ---------------------------------------------------------------------------
# Tool handlers (pure functions on dicts — testable without transport)
# ---------------------------------------------------------------------------

def handle_set_output_directory(arguments: dict) -> dict:
    """Validate args, persist the directory, return a confirmation payload."""
    if "path" not in arguments:
        raise ValueError("Missing required argument: path")
    path = arguments["path"]
    if not isinstance(path, str):
        raise ValueError(f"path must be a string, got {type(path).__name__}")
    if not path.strip():
        raise ValueError("path must not be empty")

    resolved = config.set_output_directory(path)
    logger.info("output directory set to %s", resolved)
    return {"output_directory": str(resolved)}


# ---------------------------------------------------------------------------
# MCP dispatcher
# ---------------------------------------------------------------------------

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    logger.info("tool call: %s args=%s", name, list(arguments.keys()))
    if name == "set_output_directory":
        result = handle_set_output_directory(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
