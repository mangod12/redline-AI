"""Audit log retention — purge records older than the retention period."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog

log = logging.getLogger("redline_ai.audit_retention")

AUDIT_RETENTION_DAYS = 90


async def purge_old_audit_logs() -> int:
    """Delete audit log entries older than AUDIT_RETENTION_DAYS. Returns count deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=AUDIT_RETENTION_DAYS)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                delete(AuditLog).where(AuditLog.created_at < cutoff)
            )
            await db.commit()
            deleted = result.rowcount  # type: ignore[union-attr]
            log.info("Purged %d audit log entries older than %s", deleted, cutoff.isoformat())
            return deleted
    except Exception:
        log.exception("audit_log_purge_failed")
        return 0
