import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import declarative_base, declared_attr


def _utc_now():
    """Return timezone-aware UTC datetime (replaces deprecated utcnow())."""
    return datetime.now(timezone.utc)


Base = declarative_base()

class BaseModel(Base):
    __abstract__ = True

    id = Column(Uuid, primary_key=True, default=uuid.uuid4, index=True)
    created_at = Column(DateTime(timezone=True), default=_utc_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False)

class TenantModel(BaseModel):
    __abstract__ = True

    @declared_attr
    def tenant_id(cls):
        return Column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True, nullable=False)
