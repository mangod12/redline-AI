"""Lightweight audit logging service.

Writes security-relevant events to the audit_logs table asynchronously.
Fire-and-forget from request handlers — never blocks the response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.models.audit_log import AuditLog

log = logging.getLogger("redline_ai.audit")


async def _write_audit(
    action: str,
    tenant_id: UUID | str,
    user_id: UUID | str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Persist an audit log entry. Swallows exceptions to avoid impacting callers."""
    from uuid import UUID as _UUID

    # Validate UUIDs — skip write if tenant_id is invalid (fire-and-forget)
    def _to_uuid(val):
        if not val:
            return None
        try:
            return _UUID(str(val)) if not isinstance(val, _UUID) else val
        except (ValueError, AttributeError):
            return None

    resolved_tenant = _to_uuid(tenant_id)
    if not resolved_tenant:
        return  # Can't write without valid tenant (FK constraint)

    try:
        async with AsyncSessionLocal() as session:
            entry = AuditLog(
                action=action,
                tenant_id=resolved_tenant,
                user_id=_to_uuid(user_id),
                entity_type=entity_type,
                entity_id=entity_id,
                details=details or {},
            )
            session.add(entry)
            await session.commit()
    except Exception as exc:
        log.warning("Audit log write failed: %s", exc)


def audit_event(
    action: str,
    tenant_id: UUID | str,
    user_id: UUID | str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget audit log entry. Safe to call from sync or async code."""
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(
            _write_audit(action, tenant_id, user_id, entity_type, entity_id, details)
        )
        task.add_done_callback(lambda t: None)
    except RuntimeError:
        log.warning("No event loop — audit log skipped for action=%s", action)
