"""Tests for iteration-2 features: middleware, readiness, circuit breaker,
whisper service, and security headers."""

import asyncio
import inspect
from unittest.mock import MagicMock

import pybreaker
import pytest

# ---------------------------------------------------------------------------
# 1. Request ID middleware
# ---------------------------------------------------------------------------
from app.middleware.request_id import RequestIDMiddleware


class TestRequestIDMiddleware:
    def test_is_pure_asgi_middleware(self):
        """Must have __init__(app) and async __call__(scope, receive, send)."""
        assert hasattr(RequestIDMiddleware, "__init__")
        assert hasattr(RequestIDMiddleware, "__call__")
        assert asyncio.iscoroutinefunction(RequestIDMiddleware.__call__)

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        """Non-http scopes (e.g. websocket) should be forwarded unchanged."""
        calls: list[tuple] = []

        async def fake_app(scope, receive, send):
            calls.append(("app_called", scope))

        mw = RequestIDMiddleware(fake_app)
        scope = {"type": "websocket"}

        await mw(scope, None, None)

        assert len(calls) == 1
        assert calls[0][1]["type"] == "websocket"


# ---------------------------------------------------------------------------
# 2. Readiness endpoint helpers — check_db_health / get_pool_status
# ---------------------------------------------------------------------------
from app.core.database import check_db_health, get_pool_status


class TestReadinessHelpers:
    def test_check_db_health_exists_and_is_async(self):
        assert callable(check_db_health)
        assert asyncio.iscoroutinefunction(check_db_health)

    def test_get_pool_status_exists_and_is_sync(self):
        assert callable(get_pool_status)
        # get_pool_status is a regular (sync) function
        assert not asyncio.iscoroutinefunction(get_pool_status)


# ---------------------------------------------------------------------------
# 3. Intent circuit breaker
# ---------------------------------------------------------------------------
from app.agents.intent.intent_agent import (
    IntentAgent,
    _intent_breaker,
    _keyword_fallback,
)
from app.core.schemas.intent import IntentType
from app.core.schemas.transcript import Transcript


class TestIntentCircuitBreaker:
    def test_breaker_exists_and_is_circuit_breaker(self):
        assert isinstance(_intent_breaker, pybreaker.CircuitBreaker)

    @pytest.mark.asyncio
    async def test_open_breaker_returns_keyword_fallback(self):
        """When the circuit breaker is OPEN, process() must return a keyword
        fallback immediately without calling the ML model."""
        # Force the breaker into OPEN state via its public API
        _intent_breaker.open()
        try:
            loader = MagicMock()
            loader.is_ready.return_value = True
            loader.predict_proba = MagicMock()  # should never be called

            agent = IntentAgent(loader=loader)
            transcript = Transcript(
                text="there is a huge fire",
                confidence=0.9,
                language="en",
                audio_duration=3.0,
            )

            result = await agent.process(transcript)

            assert result.fallback_used is True
            assert result.metadata.get("reason") == "circuit_open"
            assert result.metadata.get("source") == "keyword"
            # Fire keywords present in text
            assert result.intent == IntentType.FIRE
            # ML model should never have been invoked
            loader.predict_proba.assert_not_called()
        finally:
            _intent_breaker.close()


# ---------------------------------------------------------------------------
# 4. Whisper service
# ---------------------------------------------------------------------------
from app.services.whisper_service import WhisperService, _MAX_CONCURRENT


class TestWhisperService:
    def test_max_concurrent_is_defined(self):
        assert isinstance(_MAX_CONCURRENT, int)
        assert _MAX_CONCURRENT > 0

    def test_service_has_semaphore(self):
        svc = WhisperService()
        assert hasattr(svc, "_semaphore")
        assert isinstance(svc._semaphore, asyncio.Semaphore)

    def test_is_ready_false_before_init(self):
        svc = WhisperService()
        assert svc.is_ready() is False


# ---------------------------------------------------------------------------
# 5. Security headers middleware
# ---------------------------------------------------------------------------
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.security_headers import SecurityHeadersMiddleware


class TestSecurityHeadersMiddleware:
    def test_is_pure_asgi_not_base_http(self):
        """Must be a pure ASGI middleware, NOT a BaseHTTPMiddleware subclass."""
        assert not issubclass(SecurityHeadersMiddleware, BaseHTTPMiddleware)
        assert hasattr(SecurityHeadersMiddleware, "__init__")
        assert hasattr(SecurityHeadersMiddleware, "__call__")
        assert asyncio.iscoroutinefunction(SecurityHeadersMiddleware.__call__)
