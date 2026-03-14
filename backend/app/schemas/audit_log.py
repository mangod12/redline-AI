from typing import Any
from uuid import UUID

from app.schemas.base import CoreModel, TenantBaseSchema


class AuditLogCreate(CoreModel):
    user_id: UUID | None = None
    action: str
    entity_id: str | None = None
    entity_type: str | None = None
    details: dict[str, Any] = {}

class AuditLogResponse(TenantBaseSchema):
    user_id: UUID | None
    action: str
    entity_id: str | None
    entity_type: str | None
    details: dict[str, Any]
