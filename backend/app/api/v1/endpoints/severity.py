import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.models.call import Call, Transcript
from app.models.severity_report import SeverityReport
from app.models.user import User
from app.schemas.severity_report import SeverityReportResponse
from app.services.base import CRUDBase

logger = logging.getLogger("redline_ai")
router = APIRouter()

severity_crud = CRUDBase(SeverityReport)

from app.services.severity_engine import SeverityEngine

severity_engine = SeverityEngine()

@router.post("/{call_id}/analyze", response_model=SeverityReportResponse)
async def analyze_severity(
    *,
    db: AsyncSession = Depends(get_db),
    call_id: UUID,
    current_user: User = Depends(get_current_user),
    tenant_id: UUID = Depends(get_tenant_id)
) -> Any:
    """
    Generate Severity Report for a call.
    """
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    # Get latest transcript or full transcript
    result = await db.execute(select(Transcript).where(Transcript.call_id == call_id))
    transcripts = result.scalars().all()

    full_text = " ".join([t.original_text for t in transcripts])

    # Run severity engine (keyword_score derived from text length heuristic,
    # panic_score unavailable without audio features)
    score = severity_engine.calculate(
        panic_score=0.0,
        keyword_score=min(len(full_text.split()) / 50, 1.0),
        incident_type="unknown",
    )
    category = severity_engine.category(score)

    report = await severity_crud.create(
        db,
        obj_in={
            "call_id": call_id,
            "severity_score": score,
            "category": category,
            "keywords_detected": [],
            "tenant_id": tenant_id
        }
    )

    # Cache in Redis
    from app.core.redis_client import get_redis_client
    redis = get_redis_client()
    if redis:
        try:
             # Need to use a json dump to avoid UUID serialization issues
             data = {
                 "id": str(report.id),
                 "call_id": str(report.call_id),
                 "severity_score": report.severity_score,
                 "category": report.category,
                 "keywords_detected": report.keywords_detected,
                 "tenant_id": str(report.tenant_id)
             }
             await redis.set(f"call:{call_id!s}:severity", json.dumps(data), ex=3600)
        except Exception as e:
            logger.error(f"Failed to cache severity: {e}")

    return report
