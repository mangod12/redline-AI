from sqlalchemy import Column, ForeignKey, JSON, String, Uuid

from app.models.base import BaseModel


class AuditLog(BaseModel):
    """Audit log for security-relevant events.

    Uses BaseModel (not TenantModel) so that system-level events
    (e.g. failed logins, emergency calls) can be recorded without
    a tenant context.
    """

    __tablename__ = "audit_logs"

    tenant_id = Column(
        Uuid,
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, index=True, nullable=False)
    entity_id = Column(String, nullable=True)
    entity_type = Column(String, nullable=True)
    details = Column(JSON, default=dict, nullable=False)
