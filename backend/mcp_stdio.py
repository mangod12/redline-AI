"""Standalone MCP stdio server entry point.

Run with:
    python -m mcp_stdio

Or configure in Claude Desktop / MCP client:
    {
        "mcpServers": {
            "redline-ai": {
                "command": "python",
                "args": ["mcp_stdio.py"],
                "cwd": "/path/to/backend"
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure the backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.stdio import stdio_server  # noqa: E402

from app.mcp.server import server  # noqa: E402


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
