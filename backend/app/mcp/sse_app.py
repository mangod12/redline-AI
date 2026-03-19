"""SSE transport for mounting the MCP server inside FastAPI.

Usage in main.py:
    from app.mcp.sse_app import create_mcp_routes
    create_mcp_routes(app)

This adds two routes:
    GET  /mcp/sse      – SSE stream (client connects here)
    POST /mcp/messages – Client-to-server message endpoint
"""

from __future__ import annotations

import logging

from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from .server import server

log = logging.getLogger("redline_ai.mcp.sse")

_sse_transport = SseServerTransport("/mcp/messages")


async def handle_sse(request: Request) -> Response:
    """Start an SSE session — streams MCP events to the client."""
    log.info("MCP SSE client connected")
    async with _sse_transport.connect_sse(
        request.scope, request.receive, request._send,
    ) as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
    return Response()


async def handle_messages(request: Request) -> Response:
    """Receive a client message over the POST channel."""
    return await _sse_transport.handle_post_message(
        request.scope, request.receive, request._send,
    )


def create_mcp_routes(app) -> None:
    """Mount MCP SSE routes on the FastAPI app."""
    mcp_routes = Mount(
        "/mcp",
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
    )
    app.routes.append(mcp_routes)
    log.info("MCP SSE transport mounted at /mcp/sse")
