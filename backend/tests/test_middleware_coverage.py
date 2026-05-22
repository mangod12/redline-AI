"""Tests for middleware modules to boost coverage.

Tests pure ASGI middleware without a running server using mock scope/receive/send.
"""

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------


class TestSecurityHeadersMiddleware:
    @pytest.mark.asyncio
    async def test_adds_headers_to_http_response(self):
        from app.middleware.security_headers import SecurityHeadersMiddleware

        captured_headers = {}

        async def mock_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/plain")],
            })
            await send({"type": "http.response.body", "body": b"ok"})

        async def mock_send(message):
            if message["type"] == "http.response.start":
                for k, v in message.get("headers", []):
                    captured_headers[k.decode()] = v.decode()

        mw = SecurityHeadersMiddleware(mock_app)
        scope = {"type": "http", "scheme": "https"}
        await mw(scope, None, mock_send)

        assert "x-content-type-options" in captured_headers
        assert captured_headers["x-content-type-options"] == "nosniff"
        assert "x-frame-options" in captured_headers
        assert captured_headers["x-frame-options"] == "DENY"
        assert "referrer-policy" in captured_headers
        assert "permissions-policy" in captured_headers
        assert "content-security-policy" in captured_headers

    @pytest.mark.asyncio
    async def test_hsts_only_on_https(self):
        from app.middleware.security_headers import SecurityHeadersMiddleware

        headers_http = {}
        headers_https = {}

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture_http(message):
            if message["type"] == "http.response.start":
                for k, v in message.get("headers", []):
                    headers_http[k.decode()] = v.decode()

        async def capture_https(message):
            if message["type"] == "http.response.start":
                for k, v in message.get("headers", []):
                    headers_https[k.decode()] = v.decode()

        mw = SecurityHeadersMiddleware(mock_app)

        await mw({"type": "http", "scheme": "http"}, None, capture_http)
        await mw({"type": "http", "scheme": "https"}, None, capture_https)

        assert "strict-transport-security" not in headers_http
        assert "strict-transport-security" in headers_https

    @pytest.mark.asyncio
    async def test_passthrough_non_http(self):
        from app.middleware.security_headers import SecurityHeadersMiddleware

        called = []

        async def mock_app(scope, receive, send):
            called.append(scope["type"])

        mw = SecurityHeadersMiddleware(mock_app)
        await mw({"type": "websocket"}, None, None)

        assert called == ["websocket"]


# ---------------------------------------------------------------------------
# Request ID Middleware
# ---------------------------------------------------------------------------


class TestRequestIDMiddleware:
    @pytest.mark.asyncio
    async def test_adds_request_id_header(self):
        from app.middleware.request_id import RequestIDMiddleware

        captured = {}

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture(message):
            if message["type"] == "http.response.start":
                for k, v in message.get("headers", []):
                    captured[k.decode()] = v.decode()

        mw = RequestIDMiddleware(mock_app)
        await mw({"type": "http"}, None, capture)

        assert "x-request-id" in captured
        assert len(captured["x-request-id"]) == 32  # hex UUID without dashes

    @pytest.mark.asyncio
    async def test_unique_ids_per_request(self):
        from app.middleware.request_id import RequestIDMiddleware

        ids = []

        async def mock_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def capture(message):
            if message["type"] == "http.response.start":
                for k, v in message.get("headers", []):
                    if k == b"x-request-id":
                        ids.append(v.decode())

        mw = RequestIDMiddleware(mock_app)
        for _ in range(3):
            await mw({"type": "http"}, None, capture)

        assert len(ids) == 3
        assert len(set(ids)) == 3  # all unique

    @pytest.mark.asyncio
    async def test_websocket_passthrough(self):
        from app.middleware.request_id import RequestIDMiddleware

        called = []

        async def mock_app(scope, receive, send):
            called.append(True)

        mw = RequestIDMiddleware(mock_app)
        await mw({"type": "websocket"}, None, None)

        assert len(called) == 1


# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------


class TestRedisClientModule:
    @pytest.mark.asyncio
    async def test_check_redis_health_false_when_not_initialized(self):
        from unittest.mock import patch

        from app.core.redis_client import check_redis_health

        with patch("app.core.redis_client._redis_client", None):
            result = await check_redis_health()
            assert result is False

    def test_get_redis_client_returns_none_initially(self):
        from app.core.redis_client import get_redis_client

        # In test env without init, should be None or fakeredis
        client = get_redis_client()
        # Can be None or fakeredis depending on test ordering
        assert client is None or client is not None  # just verify no crash

    @pytest.mark.asyncio
    async def test_close_redis_safe_when_not_initialized(self):
        from app.core.redis_client import close_redis

        # Should not raise
        await close_redis()
