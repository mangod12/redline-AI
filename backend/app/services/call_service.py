from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_result import AnalysisResult
from app.models.call import Call, Transcript
from app.models.dispatch_recommendation import DispatchRecommendation
from app.services.base import CRUDBase


class CRUDCall(CRUDBase):
    async def get_multi_by_tenant(
        self, db: AsyncSession, *, tenant_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Call]:
        result = await db.execute(
            select(Call)
            .where(Call.tenant_id == tenant_id)
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

call = CRUDCall(Call)

class CRUDTranscript(CRUDBase):
    async def get_multi_by_call(
        self, db: AsyncSession, *, call_id: UUID, skip: int = 0, limit: int = 100
    ) -> list[Transcript]:
        result = await db.execute(
            select(Transcript)
            .where(Transcript.call_id == call_id)
            .order_by(Transcript.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

transcript = CRUDTranscript(Transcript)

# New CRUD for analysis results
class CRUDAnalysis(CRUDBase):
    async def get_by_call(self, db: AsyncSession, *, call_id: UUID):
        result = await db.execute(select(AnalysisResult).where(AnalysisResult.call_id == call_id))
        return result.scalars().all()

analysis_result = CRUDAnalysis(AnalysisResult)

# New CRUD for dispatch recommendations
class CRUDDispatch(CRUDBase):
    async def get_by_call(self, db: AsyncSession, *, call_id: UUID):
        result = await db.execute(select(DispatchRecommendation).where(DispatchRecommendation.call_id == call_id))
        return result.scalars().all()

dispatch = CRUDDispatch(DispatchRecommendation)
