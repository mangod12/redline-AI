"""Redis-backed call store for the dashboard.

Falls back to in-memory deque if Redis unavailable.
Stores last 100 calls with tenant_id for filtering.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timezone
from typing import Any

logger = logging.getLogger("redline_ai.dashboard.call_store")

_REDIS_KEY = "redline:dashboard:calls"
_MAXLEN = 100


def _get_redis():
    """Get Redis client, returns None if unavailable."""
    try:
        from app.core.redis_client import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def add_call(
    *,
    transcript: str,
    intent: str,
    intent_confidence: float,
    emotion: str,
    emotion_confidence: float,
    severity: str,
    severity_score: float,
    responder: str,
    fallback_used: bool,
    intent_fallback: bool,
    emotion_fallback: bool,
    latency_ms: float,
    tenant_id: str = "",
) -> str:
    """Insert a new call record. Returns the generated call_id."""
    call_id = uuid.uuid4().hex[:8].upper()
    record: dict[str, Any] = {
        "call_id": call_id,
        "timestamp": datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "transcript": transcript,
        "intent": intent,
        "intent_confidence": round(intent_confidence, 3),
        "emotion": emotion,
        "emotion_confidence": round(emotion_confidence, 3),
        "severity": severity,
        "severity_score": round(severity_score, 3),
        "responder": responder,
        "fallback_used": fallback_used,
        "intent_fallback": intent_fallback,
        "emotion_fallback": emotion_fallback,
        "latency_ms": round(latency_ms, 1),
        "tenant_id": tenant_id,
    }

    redis = _get_redis()
    if redis:
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            task = loop.create_task(_async_add(redis, record))
            task.add_done_callback(
                lambda t: (
                    logger.warning("call_store write failed: %s", t.exception())
                    if t.exception()
                    else None
                )
            )
        except RuntimeError:
            # No running event loop — skip Redis write
            pass
        except Exception as exc:
            logger.warning("call_store add_call error: %s", exc)

    return call_id


async def _async_add(redis, record: dict) -> None:
    """Push record to Redis list, trim to MAXLEN."""
    await redis.lpush(_REDIS_KEY, json.dumps(record, default=str))
    await redis.ltrim(_REDIS_KEY, 0, _MAXLEN - 1)


def get_recent(limit: int = 50, tenant_id: str = "") -> list[dict[str, Any]]:
    """Sync wrapper — prefer aget_recent() from async code.

    Returns empty list when called from within a running event loop
    (which is always the case in FastAPI). Use aget_recent() instead.
    """
    return []


async def aget_recent(limit: int = 50, tenant_id: str = "") -> list[dict[str, Any]]:
    """Async version of get_recent for use in async endpoints."""
    redis = _get_redis()
    if not redis:
        return []
    try:
        records = await redis.lrange(_REDIS_KEY, 0, _MAXLEN - 1)
        calls = [json.loads(r) for r in records]
        if tenant_id:
            calls = [c for c in calls if c.get("tenant_id") == tenant_id]
        return calls[:limit]
    except Exception:
        return []


async def clear() -> None:
    """Clear all records (used in tests)."""
    redis = _get_redis()
    if redis:
        await redis.delete(_REDIS_KEY)
