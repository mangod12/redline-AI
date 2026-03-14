from sqlalchemy import Column, Integer, JSON, String, ForeignKey
from sqlalchemy.orm import relationship

from app.models.base import TenantModel

class SeverityReport(TenantModel):
    __tablename__ = "severity_reports"

    call_id = Column(ForeignKey("calls.id", ondelete="CASCADE"), index=True, nullable=False)
    severity_score = Column(Integer, index=True, nullable=False)
    category = Column(String, nullable=False)
    keywords_detected = Column(JSON, default=list, nullable=False)
    
    call = relationship("Call", back_populates="severity_reports")
