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
import logging
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool

logger = logging.getLogger("banjo.mcp")

server: Server = Server("banjo")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise the two banjo tools to the MCP host."""
    return [
        Tool(
            name="generate_midi_progression",
            description="(stub — implemented in a later task)",
            inputSchema={"type": "object"},
        ),
        Tool(
            name="set_output_directory",
            description="(stub — implemented in a later task)",
            inputSchema={"type": "object"},
        ),
    ]


async def _run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Console-script entry point."""
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
