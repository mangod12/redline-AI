import asyncio
import contextlib
import json

import structlog

from app.core.database import AsyncSessionLocal
from app.core.redis_client import get_redis_client
from app.services.call_processing import CallProcessor

logger = structlog.get_logger("redline_ai.event")

_listener_task = None

# Events that should NEVER trigger re-processing (to prevent infinite loops)
_IGNORE_EVENTS = {
    "PROCESSING_STARTED",
    "ML_ANALYSIS_COMPLETE",
    "SEVERITY_UPDATED",
    "LOCATION_RESOLVED",
    "DISPATCH_RECOMMENDED",
}

_MAX_BACKOFF_S = 30
_INITIAL_BACKOFF_S = 1


def start_event_listener():
    """Create a background task that listens to the global Redis channel.

    Only TRANSCRIPT_RECEIVED events trigger the processing pipeline.
    Uses exponential backoff on repeated errors to avoid CPU spin.
    """

    async def _listener():
        backoff = _INITIAL_BACKOFF_S
        processor = CallProcessor()

        while True:
            redis = get_redis_client()
            if not redis:
                logger.warning(
                    "Redis not available for event listener, retrying", backoff=backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)
                continue

            pubsub = None
            try:
                pubsub = redis.pubsub()
                await pubsub.subscribe("redline.events.calls")
                logger.info("Subscribed to redline.events.calls channel")
                backoff = _INITIAL_BACKOFF_S  # reset on successful connect

                async for raw_message in pubsub.listen():
                    if raw_message["type"] != "message":
                        continue

                    try:
                        data = json.loads(raw_message["data"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Malformed event message, skipping")
                        continue

                    event = data.get("event_type")
                    if event in _IGNORE_EVENTS:
                        continue

                    if event == "TRANSCRIPT_RECEIVED":
                        call_id = data.get("call_id")
                        payload = data.get("payload", {})
                        logger.info("Processing TRANSCRIPT_RECEIVED", call_id=call_id)
                        async with AsyncSessionLocal() as db:
                            try:
                                await processor.process_transcript(
                                    db,
                                    call_id=call_id,
                                    transcript_text=payload.get("text", ""),
                                    language=payload.get("language", "en"),
                                    tenant_id=payload.get("tenant_id"),
                                )
                            except Exception as exc:
                                logger.error(
                                    "Transcript processing failed",
                                    call_id=call_id,
                                    error=str(exc),
                                )

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Event listener connection error", error=str(exc), backoff=backoff
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_S)
            finally:
                if pubsub:
                    with contextlib.suppress(Exception):
                        await pubsub.unsubscribe("redline.events.calls")

    global _listener_task
    loop = asyncio.get_running_loop()
    _listener_task = loop.create_task(_listener())


async def stop_event_listener():
    """Cancel the background listener task gracefully."""
    global _listener_task
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener_task
        _listener_task = None
