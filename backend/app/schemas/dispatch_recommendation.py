from uuid import UUID

from app.schemas.base import CoreModel, TenantBaseSchema


class DispatchRecommendationCreate(CoreModel):
    call_id: UUID
    unit_id: str
    eta_minutes: float | None = None
    priority: str

class DispatchRecommendationResponse(TenantBaseSchema):
    call_id: UUID
    unit_id: str
    eta_minutes: float | None = None
    priority: str
