from uuid import UUID

from app.schemas.base import CoreModel, TenantBaseSchema


class AnalysisResultCreate(CoreModel):
    call_id: UUID
    incident_type: str
    panic_score: float
    keyword_score: float
    severity_prediction: int | None = None
    location_text: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_confidence: float | None = None

class AnalysisResultResponse(TenantBaseSchema):
    call_id: UUID
    incident_type: str
    panic_score: float
    keyword_score: float
    severity_prediction: int | None = None
    location_text: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geo_confidence: float | None = None
