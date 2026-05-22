"""Tests targeting low-coverage modules to improve overall coverage."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.schemas import Transcript


# ---------------------------------------------------------------------------
# Dispatch service — full branch coverage
# ---------------------------------------------------------------------------


class TestDispatchFullBranch:
    """Cover every branch in select_responder."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "intent,severity,expected",
        [
            # critical
            ("fire", "critical", "fire_dispatch"),
            ("gas_hazard", "critical", "fire_dispatch"),
            ("medical", "critical", "ambulance"),
            ("mental_health", "critical", "ambulance"),
            ("violent_crime", "critical", "police_dispatch"),
            ("accident", "critical", "police_dispatch"),
            ("unknown", "critical", "police_dispatch"),
            # high
            ("medical", "high", "ambulance"),
            ("mental_health", "high", "ambulance"),
            ("fire", "high", "fire_dispatch"),
            ("gas_hazard", "high", "fire_dispatch"),
            ("violent_crime", "high", "police_dispatch"),
            ("unknown", "high", "police_dispatch"),
            # medium
            ("medical", "medium", "ambulance"),
            ("fire", "medium", "general_responder"),
            ("unknown", "medium", "general_responder"),
            # low
            ("medical", "low", "call_center_followup"),
            ("fire", "low", "call_center_followup"),
        ],
    )
    async def test_dispatch_matrix(self, intent, severity, expected):
        from app.services.dispatch_service import select_responder
        result = await select_responder(intent, severity)
        assert result == expected


# ---------------------------------------------------------------------------
# Severity service — full branch coverage
# ---------------------------------------------------------------------------


class TestSeverityFullBranch:
    @pytest.mark.asyncio
    async def test_non_emergency_override(self):
        from app.services.severity_service import compute_severity
        # Non-emergency base is "low", but fear promotes to "medium"
        result = await compute_severity("non emergency follow up call", "fear")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_non_emergency_neutral_stays_low(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("non emergency follow up call", "neutral")
        assert result == "low"

    @pytest.mark.asyncio
    async def test_fear_promotes_medium_to_high(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("someone is hurt", "fear")
        assert result == "high"  # medium + fear = promote to high

    @pytest.mark.asyncio
    async def test_sadness_promotes_low_to_medium(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("hello world", "sadness")
        assert result == "medium"

    @pytest.mark.asyncio
    async def test_sadness_does_not_promote_medium(self):
        from app.services.severity_service import compute_severity
        result = await compute_severity("someone is hurt", "sadness")
        assert result == "medium"  # sadness only promotes low->medium


# ---------------------------------------------------------------------------
# Severity engine — full coverage
# ---------------------------------------------------------------------------


class TestSeverityEngine:
    def test_calculate_known_incident(self):
        from app.services.severity_engine import SeverityEngine
        engine = SeverityEngine()
        score = engine.calculate(0.8, 0.6, "fire")
        assert score > 0

    def test_calculate_unknown_incident(self):
        from app.services.severity_engine import SeverityEngine
        engine = SeverityEngine()
        score = engine.calculate(0.5, 0.5, "unknown")
        assert 0 <= score <= 10

    def test_category_high(self):
        from app.services.severity_engine import SeverityEngine
        engine = SeverityEngine()
        assert engine.category(8.0) == "HIGH"

    def test_category_medium(self):
        from app.services.severity_engine import SeverityEngine
        engine = SeverityEngine()
        assert engine.category(5.0) == "MEDIUM"

    def test_category_low(self):
        from app.services.severity_engine import SeverityEngine
        engine = SeverityEngine()
        assert engine.category(2.0) == "LOW"


# ---------------------------------------------------------------------------
# Cache service — more paths
# ---------------------------------------------------------------------------


class TestCacheServicePaths:
    @pytest.mark.asyncio
    async def test_cache_call_handles_exception(self):
        from app.services.cache_service import cache_call
        mock_redis = AsyncMock()
        mock_redis.set.side_effect = Exception("Redis down")
        # Should not raise
        await cache_call(mock_redis, "test-123", {"key": "val"})

    @pytest.mark.asyncio
    async def test_get_cached_call_returns_data(self):
        from app.services.cache_service import cache_call, get_cached_call
        import json
        mock_redis = AsyncMock()
        data = {"call_id": "test", "intent": "fire"}
        mock_redis.get.return_value = json.dumps(data)
        result = await get_cached_call(mock_redis, "test")
        assert result == data

    @pytest.mark.asyncio
    async def test_get_cached_call_returns_none_on_miss(self):
        from app.services.cache_service import get_cached_call
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        result = await get_cached_call(mock_redis, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_cached_call_handles_bad_json(self):
        from app.services.cache_service import get_cached_call
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not-valid-json{{"
        result = await get_cached_call(mock_redis, "bad")
        assert result is None


# ---------------------------------------------------------------------------
# Intent model loader — initialization guard
# ---------------------------------------------------------------------------


class TestIntentModelLoader:
    def test_not_ready_initially(self):
        from app.ml.intent_model_loader import IntentModelLoader
        loader = IntentModelLoader()
        assert loader.is_ready() is False

    @pytest.mark.asyncio
    async def test_predict_raises_when_not_ready(self):
        from app.ml.intent_model_loader import IntentModelLoader
        loader = IntentModelLoader()
        with pytest.raises(RuntimeError, match="not initialized"):
            await loader.predict_proba("test")

    @pytest.mark.asyncio
    async def test_shutdown_clears_state(self):
        from app.ml.intent_model_loader import IntentModelLoader
        loader = IntentModelLoader()
        await loader.shutdown()
        assert loader.is_ready() is False


# ---------------------------------------------------------------------------
# Call store paths
# ---------------------------------------------------------------------------


class TestCallStorePaths:
    def test_get_recent_returns_empty(self):
        from app.dashboard.call_store import get_recent
        assert get_recent() == []

    def test_add_call_returns_id(self):
        from app.dashboard.call_store import add_call
        call_id = add_call(
            transcript="test",
            intent="fire",
            intent_confidence=0.9,
            emotion="fear",
            emotion_confidence=0.8,
            severity="high",
            severity_score=0.7,
            responder="fire_dispatch",
            fallback_used=False,
            intent_fallback=False,
            emotion_fallback=False,
            latency_ms=100.0,
            tenant_id="test-tenant",
        )
        assert isinstance(call_id, str)
        assert len(call_id) == 8
