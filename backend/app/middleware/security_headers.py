"""Pure ASGI security headers middleware.

Avoids BaseHTTPMiddleware which breaks streaming responses in Starlette/FastAPI.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self' 'unsafe-inline'; "
        b"style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'",
    ),
]

_HSTS_HEADER: tuple[bytes, bytes] = (
    b"strict-transport-security",
    b"max-age=31536000; includeSubDomains",
)


class SecurityHeadersMiddleware:
    """Add standard security headers to all HTTP responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_https = scope.get("scheme") == "https"

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                if is_https:
                    headers.append(_HSTS_HEADER)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
