"""Celery tasks for Redline AI background processing.

These tasks are dispatched from the API layer so that heavy or
side-effectful work (logging, notifications, event publishing) does not
block the request/response cycle.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import redis

from app.core.config import settings
from app.worker import celery_app

logger = logging.getLogger("redline_ai.tasks")

REDIS_EVENTS_CHANNEL = "redline.events.calls"


def _get_redis_sync() -> redis.Redis:
    """Return a synchronous Redis client for use inside Celery workers."""
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


@celery_app.task(
    bind=True,
    name="process_emergency_call",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def process_emergency_call(
    self,
    call_id: str,
    transcript: str,
    intent: str,
    emotion: str,
    severity: str,
    responder: str,
) -> dict:
    """Record an emergency call and publish the event to Redis.

    Logs structured call data and publishes a JSON event to the
    ``redline.events.calls`` Redis pub/sub channel so that downstream
    consumers (dashboards, analytics, external integrations) can react
    in near-real-time.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    event_payload = {
        "event": "emergency_call_processed",
        "call_id": call_id,
        "transcript": transcript[:500],  # truncate for pub/sub safety
        "intent": intent,
        "emotion": emotion,
        "severity": severity,
        "responder": responder,
        "timestamp": timestamp,
    }

    logger.info(
        "Processing emergency call | call_id=%s intent=%s emotion=%s severity=%s responder=%s",
        call_id,
        intent,
        emotion,
        severity,
        responder,
    )

    try:
        r = _get_redis_sync()
        r.publish(REDIS_EVENTS_CHANNEL, json.dumps(event_payload))
        logger.info(
            "Published event to %s | call_id=%s", REDIS_EVENTS_CHANNEL, call_id
        )
    except Exception as exc:
        logger.error(
            "Failed to publish event to Redis | call_id=%s error=%s", call_id, exc
        )
        raise self.retry(exc=exc)

    return {
        "call_id": call_id,
        "status": "processed",
        "timestamp": timestamp,
    }


@celery_app.task(
    bind=True,
    name="send_dispatch_notification",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def send_dispatch_notification(
    self,
    call_id: str,
    responder: str,
    severity: str,
    tenant_id: Optional[str] = None,
) -> dict:
    """Notify the appropriate dispatch unit of an incoming emergency.

    Currently logs structured dispatch data.  The body of this task is
    designed to be extended with external notification integrations
    (e.g. PagerDuty, Twilio, webhook) in the future.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    dispatch_record = {
        "event": "dispatch_notification_sent",
        "call_id": call_id,
        "responder": responder,
        "severity": severity,
        "tenant_id": tenant_id,
        "timestamp": timestamp,
    }

    logger.info(
        "Dispatch notification | call_id=%s responder=%s severity=%s tenant_id=%s",
        call_id,
        responder,
        severity,
        tenant_id,
    )

    # Publish dispatch event to the same channel so consumers can
    # differentiate by the ``event`` field.
    try:
        r = _get_redis_sync()
        r.publish(REDIS_EVENTS_CHANNEL, json.dumps(dispatch_record))
        logger.info(
            "Published dispatch event to %s | call_id=%s",
            REDIS_EVENTS_CHANNEL,
            call_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to publish dispatch event | call_id=%s error=%s", call_id, exc
        )
        raise self.retry(exc=exc)

    return {
        "call_id": call_id,
        "responder": responder,
        "notified": True,
        "tenant_id": tenant_id,
        "timestamp": timestamp,
    }
