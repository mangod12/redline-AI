"""Redis-backed call store for the dashboard.

Keeps the last `_MAXLEN` calls in a Redis sorted set (scored by timestamp)
and exposes add_call() / get_recent() with tenant_id filtering.
Falls back to an in-memory deque when Redis is unavailable.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

_MAXLEN = 100
_REDIS_KEY = "redline:dashboard:calls"

# In-memory fallback
_lock = threading.Lock()
_calls: deque[dict[str, Any]] = deque(maxlen=_MAXLEN)


def _get_redis():
    """Lazily import to avoid circular dependency at module load time."""
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception:
        return None


async def _redis_add(record: dict[str, Any]) -> None:
    redis = _get_redis()
    if redis is None:
        return
    score = time.time()
    await redis.zadd(_REDIS_KEY, {json.dumps(record): score})
    # Trim to keep only the latest _MAXLEN entries
    await redis.zremrangebyrank(_REDIS_KEY, 0, -(_MAXLEN + 1))


async def _redis_get_recent(limit: int, tenant_id: str | None) -> list[dict[str, Any]] | None:
    redis = _get_redis()
    if redis is None:
        return None
    raw = await redis.zrevrange(_REDIS_KEY, 0, -1)
    results: list[dict[str, Any]] = []
    for item in raw:
        record = json.loads(item)
        if tenant_id is not None and record.get("tenant_id") != tenant_id:
            continue
        results.append(record)
        if len(results) >= limit:
            break
    return results


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
    tenant_id: str | None = None,
) -> str:
    """Insert a new call record. Returns the generated call_id.

    Attempts to persist in Redis; always stores in the in-memory fallback.
    """
    call_id = uuid.uuid4().hex[:8].upper()
    record: dict[str, Any] = {
        "call_id": call_id,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
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
    with _lock:
        _calls.appendleft(record)

    # Fire-and-forget Redis persistence
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_redis_add(record))
    except RuntimeError:
        pass  # No running loop (e.g. during tests)

    return call_id


async def get_recent(limit: int = 50, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return up to `limit` most-recent call records, optionally filtered by tenant_id.

    Tries Redis first; falls back to in-memory store.
    """
    redis_result = await _redis_get_recent(limit, tenant_id)
    if redis_result is not None:
        return redis_result

    # Fallback to in-memory
    with _lock:
        items = list(_calls)
    if tenant_id is not None:
        items = [r for r in items if r.get("tenant_id") == tenant_id]
    return items[:limit]


def get_recent_sync(limit: int = 50, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Synchronous fallback for contexts without an event loop."""
    with _lock:
        items = list(_calls)
    if tenant_id is not None:
        items = [r for r in items if r.get("tenant_id") == tenant_id]
    return items[:limit]


def clear() -> None:
    """Clear all records (used in tests)."""
    with _lock:
        _calls.clear()
