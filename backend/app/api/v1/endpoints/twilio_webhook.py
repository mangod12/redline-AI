"""Twilio-authenticated webhook for emergency call processing.

This endpoint validates the Twilio request signature before processing,
providing a secure ingress point for Twilio voice/SMS webhooks.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db
from app.core.security import limiter, verify_twilio_signature
from app.api.v1.endpoints.emergency import process_emergency_core

router = APIRouter()


@router.post(
    "/process-emergency",
    status_code=status.HTTP_200_OK,
    summary="Process an emergency call via Twilio webhook (signature-verified)",
    tags=["twilio"],
    dependencies=[Depends(verify_twilio_signature)],
)
@limiter.limit("5/minute")
async def twilio_process_emergency(
    request: Request,
    db: AsyncSession = Depends(get_db),
    audio_file: Optional[UploadFile] = File(default=None),
    transcript: Optional[str] = Form(default=None),
    caller_id: Optional[str] = Form(default=None),
):
    """Process an emergency call from a verified Twilio webhook."""
    return await process_emergency_core(
        request=request,
        db=db,
        audio_file=audio_file,
        transcript=transcript,
        caller_id=caller_id,
    )
