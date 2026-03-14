from uuid import UUID

from app.schemas.base import CoreModel, TenantBaseSchema


class SeverityReportCreate(CoreModel):
    severity_score: int
    category: str
    keywords_detected: list[str] = []

class SeverityReportResponse(TenantBaseSchema):
    call_id: UUID
    severity_score: int
    category: str
    keywords_detected: list[str]
