"""Audit logging service.

Provides a fire-and-forget async function for recording security-relevant
events.  Failures are logged but never raised so audit logging cannot
break the request pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog

log = logging.getLogger("redline_ai.audit")


async def record_audit(
    *,
    tenant_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Write an audit log entry in its own DB session (fire-and-forget)."""
    try:
        async with AsyncSessionLocal() as db:
            entry = AuditLog(
                tenant_id=tenant_id,
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details or {},
            )
            db.add(entry)
            await db.commit()
    except Exception:
        log.exception("audit_log_write_failed", extra={"action": action})
