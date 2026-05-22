"""POST /process-emergency endpoint.

Accepts either:
  - multipart/form-data with audio_file (UploadFile) and/or transcript (str)
  - application/json with {"transcript": "...", "caller_id": "..."}

Pipeline:
  audio → Whisper STT → intent (heuristic) → emotion (EmotionAgent)
  → severity → dispatch → PostgreSQL → Redis cache → JSON response
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.redis_client import get_redis_client
from app.core.schemas import Transcript
from app.core.security import limiter, require_jwt_token
from app.dashboard import call_store
from app.models.emergency_call import EmergencyCall
from app.services.cache_service import cache_call
from app.services.dispatch_service import select_responder
from app.services.severity_service import compute_severity

log = logging.getLogger("redline_ai.api.emergency")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

emergency_pipeline_latency_seconds = Histogram(
    "emergency_pipeline_latency_seconds",
    "End-to-end latency of the emergency pipeline",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

emergency_pipeline_total = Counter(
    "emergency_pipeline_total",
    "Total emergency pipeline invocations",
    ["status"],
)

emergency_pipeline_fallback_total = Counter(
    "emergency_pipeline_fallback_total",
    "Emergency pipeline fallback activations",
    ["agent"],
)

router = APIRouter()


# ---------------------------------------------------------------------------
# JSON body schema (used when Content-Type is application/json)
# ---------------------------------------------------------------------------


class EmergencyJSONRequest(BaseModel):
    transcript: str = Field(..., max_length=10_000)
    caller_id: str | None = Field(default=None, max_length=64)


# ---------------------------------------------------------------------------
# Response schema
# ---------------------------------------------------------------------------


class EmergencyResponse(BaseModel):
    call_id: str
    transcript: str
    intent: str
    intent_confidence: float
    emotion: str
    severity: str
    responder: str
    latency_ms: int
    caller_id: str | None


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/process-emergency",
    response_model=EmergencyResponse,
    status_code=status.HTTP_200_OK,
    summary="Process an emergency call through the full AI pipeline",
    tags=["emergency"],
)
@limiter.limit("30/minute")
async def process_emergency(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token_payload: dict = Depends(require_jwt_token),
    # Multipart/form-data fields (all optional so JSON path works too)
    audio_file: UploadFile | None = File(default=None),
    transcript: str | None = Form(default=None),
    caller_id: str | None = Form(default=None, max_length=64),
) -> EmergencyResponse:
    """Process an emergency call end-to-end.

    Accepts **audio** (multipart upload) **or** a raw **transcript** (form
    field or JSON body).  At least one of the two must be supplied.

    When the Content-Type is ``application/json`` the endpoint falls back
    to parsing the body as an :class:`EmergencyJSONRequest`.
    """
    t_start = time.perf_counter()

    # ------------------------------------------------------------------
    # 1. Resolve transcript
    # ------------------------------------------------------------------

    # If the client sent JSON instead of a form, parse body manually.
    content_type = request.headers.get("content-type", "")
    if transcript is None and audio_file is None and "application/json" in content_type:
        try:
            body = await request.json()
            json_req = EmergencyJSONRequest.model_validate(body)
            transcript = json_req.transcript
            caller_id = caller_id or json_req.caller_id
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid JSON body: {exc}",
            ) from exc

    if audio_file is not None:
        # Validate content type
        if (
            audio_file.content_type
            and audio_file.content_type not in settings.ALLOWED_AUDIO_TYPES
        ):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported audio format: {audio_file.content_type}",
            )

        whisper_svc = getattr(request.app.state, "whisper_service", None)
        if whisper_svc is None or not whisper_svc.is_ready():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Whisper STT service is not available",
            )

        # Read with size limit
        audio_bytes = await audio_file.read(settings.MAX_AUDIO_BYTES + 1)
        if len(audio_bytes) > settings.MAX_AUDIO_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Audio file exceeds {settings.MAX_AUDIO_BYTES // (1024 * 1024)} MB limit",
            )

        try:
            transcript = await whisper_svc.transcribe(audio_bytes)
        except Exception as exc:
            log.error("Whisper transcription failed: %s", exc)
            emergency_pipeline_total.labels(status="error").inc()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Audio transcription failed",
            ) from exc

    # Narrow Optional[str] → str; guard empty input.
    resolved_transcript: str = transcript or ""
    if not resolved_transcript.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either an audio_file or a non-empty transcript.",
        )

    transcript = resolved_transcript.strip()

    # Sanitize: strip control characters (but preserve unicode text for multi-language)
    import re as _re

    transcript = _re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", transcript)

    if len(transcript) > settings.MAX_TRANSCRIPT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Transcript exceeds {settings.MAX_TRANSCRIPT_LENGTH} character limit.",
        )

    # ------------------------------------------------------------------
    # 2. Run pipeline (intent + emotion in parallel, then severity + dispatch)
    # ------------------------------------------------------------------

    intent = "unknown"
    intent_confidence = 0.0
    intent_fallback = True
    emotion_label = "neutral"
    emotion_confidence = 0.0
    emotion_fallback = True

    async def _run_intent():
        nonlocal intent, intent_confidence, intent_fallback
        try:
            from app.agents.intent.intent_agent import IntentAgent

            intent_loader = getattr(request.app.state, "intent_loader", None)
            intent_agent = IntentAgent(loader=intent_loader)
            intent_result = await intent_agent.process(
                Transcript(text=transcript, confidence=1.0)
            )
            intent = intent_result.intent.value
            intent_confidence = float(intent_result.confidence)
            intent_fallback = bool(intent_result.fallback_used)
        except Exception as exc:
            log.warning("IntentAgent failed, using unknown fallback: %s", exc)

    async def _run_emotion():
        nonlocal emotion_label, emotion_confidence, emotion_fallback
        try:
            from app.agents.emotion.emotion_agent import EmotionAgent

            emotion_loader = getattr(request.app.state, "emotion_loader", None)
            agent = EmotionAgent(loader=emotion_loader)
            emotion_result = await agent.process(
                Transcript(text=transcript, confidence=1.0)
            )
            emotion_label = emotion_result.primary_emotion.value
            emotion_confidence = float(emotion_result.confidence)
            emotion_fallback = emotion_confidence <= 0.0
        except Exception as exc:
            log.warning("EmotionAgent failed, using neutral fallback: %s", exc)

    await asyncio.gather(_run_intent(), _run_emotion())

    severity = await compute_severity(transcript, emotion_label)
    responder = await select_responder(intent, severity)

    # ------------------------------------------------------------------
    # 3. Persist to PostgreSQL
    # ------------------------------------------------------------------

    latency_ms = int((time.perf_counter() - t_start) * 1000)
    call_id = uuid.uuid4()

    # Validate tenant_id as UUID — pass None if invalid (tenant column is nullable)
    raw_tenant = token_payload.get("tenant_id")
    try:
        from uuid import UUID as _UUID

        tenant_uuid = _UUID(str(raw_tenant)) if raw_tenant else None
    except (ValueError, AttributeError):
        tenant_uuid = None

    call_row = EmergencyCall(
        call_id=call_id,
        caller_id=caller_id,
        tenant_id=tenant_uuid,
        transcript=transcript,
        intent=intent,
        emotion=emotion_label,
        severity=severity,
        responder=responder,
        latency_ms=latency_ms,
    )
    db.add(call_row)
    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.error("DB commit failed for call %s: %s", call_id, exc)
        emergency_pipeline_total.labels(status="error").inc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist call record",
        ) from exc

    # Audit: emergency call processed
    from app.services.audit_service import audit_event

    audit_event(
        action="emergency_call_processed",
        tenant_id=token_payload.get("tenant_id", ""),
        user_id=token_payload.get("sub"),
        entity_type="emergency_call",
        entity_id=str(call_id),
        details={"severity": severity, "intent": intent, "responder": responder},
    )

    # ------------------------------------------------------------------
    # 4. Cache in Redis (fire-and-forget — never blocks response)
    # ------------------------------------------------------------------

    call_data = {
        "call_id": str(call_id),
        "caller_id": caller_id,
        "transcript": transcript,
        "intent": intent,
        "intent_confidence": intent_confidence,
        "emotion": emotion_label,
        "severity": severity,
        "responder": responder,
        "latency_ms": latency_ms,
    }

    def _on_cache_done(task: asyncio.Task) -> None:
        if task.exception():
            log.warning("Background cache write failed: %s", task.exception())

    cache_task = asyncio.create_task(
        cache_call(get_redis_client(), str(call_id), call_data)
    )
    cache_task.add_done_callback(_on_cache_done)

    fallback_used = intent_fallback or emotion_fallback
    call_store.add_call(
        transcript=transcript,
        intent=intent,
        intent_confidence=intent_confidence,
        emotion=emotion_label,
        emotion_confidence=emotion_confidence,
        severity=severity,
        severity_score=0.0,
        responder=responder,
        fallback_used=fallback_used,
        intent_fallback=intent_fallback,
        emotion_fallback=emotion_fallback,
        latency_ms=float(latency_ms),
        tenant_id=token_payload.get("tenant_id", ""),
    )

    # ------------------------------------------------------------------
    # 5. Dispatch Celery background tasks (fire-and-forget)
    # ------------------------------------------------------------------

    try:
        from app.tasks import process_emergency_call, send_dispatch_notification

        process_emergency_call.delay(
            call_id=str(call_id),
            transcript=transcript,
            intent=intent,
            emotion=emotion_label,
            severity=severity,
            responder=responder,
        )
        send_dispatch_notification.delay(
            call_id=str(call_id),
            responder=responder,
            severity=severity,
            tenant_id=token_payload.get("tenant_id"),
        )
    except Exception as exc:
        log.warning("Failed to dispatch Celery tasks for call %s: %s", call_id, exc)

    # ------------------------------------------------------------------
    # 6. Prometheus metrics & Return
    # ------------------------------------------------------------------

    elapsed = time.perf_counter() - t_start
    emergency_pipeline_latency_seconds.observe(elapsed)
    emergency_pipeline_total.labels(status="success").inc()

    if intent_fallback:
        emergency_pipeline_fallback_total.labels(agent="intent").inc()
    if emotion_fallback:
        emergency_pipeline_fallback_total.labels(agent="emotion").inc()

    return EmergencyResponse(
        call_id=str(call_id),
        transcript=transcript,
        intent=intent,
        intent_confidence=intent_confidence,
        emotion=emotion_label,
        severity=severity,
        responder=responder,
        latency_ms=latency_ms,
        caller_id=caller_id,
    )
