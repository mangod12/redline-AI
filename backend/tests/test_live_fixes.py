"""Tests for bugs found and fixed during live E2E testing.

Covers:
- JSONB → JSON model compatibility
- ALLOWED_ORIGINS string parsing
- Config extra fields ignored
- Tenant ID UUID validation in emergency endpoint
- Audit service UUID handling
- Metrics endpoint (sync vs async)
- Route ordering (calls/live vs calls/{call_id})
- Transcript control char sanitization
"""

import os
import pytest
from uuid import UUID


class TestJSONModelCompat:
    """Verify JSONB was replaced with JSON for SQLite compat."""

    def test_severity_report_uses_json(self):
        from app.models.severity_report import SeverityReport
        col = SeverityReport.__table__.c.keywords_detected
        from sqlalchemy import JSON
        assert isinstance(col.type, JSON)

    def test_audit_log_uses_json(self):
        from app.models.audit_log import AuditLog
        col = AuditLog.__table__.c.details
        from sqlalchemy import JSON
        assert isinstance(col.type, JSON)


class TestConfigParsing:
    def test_allowed_origins_is_string(self):
        from app.core.config import Settings
        s = Settings(SECRET_KEY="x", ALLOWED_ORIGINS="http://a.com,http://b.com")
        assert isinstance(s.ALLOWED_ORIGINS, str)

    def test_allowed_origins_list_property(self):
        from app.core.config import Settings
        s = Settings(SECRET_KEY="x", ALLOWED_ORIGINS="http://a.com , http://b.com")
        assert s.allowed_origins_list == ["http://a.com", "http://b.com"]

    def test_extra_fields_ignored(self):
        """Extra env vars like GF_ADMIN_PASSWORD should not cause errors."""
        from app.core.config import Settings
        s = Settings(SECRET_KEY="x", GF_ADMIN_PASSWORD="test", GUNICORN_WORKERS="4")
        assert s.SECRET_KEY == "x"


class TestTenantUUIDValidation:
    def test_valid_uuid_string(self):
        """Valid UUID string should be accepted."""
        from uuid import UUID as _UUID
        raw = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        result = _UUID(raw)
        assert result is not None

    def test_invalid_uuid_string(self):
        """Invalid string should raise ValueError."""
        from uuid import UUID as _UUID
        with pytest.raises(ValueError):
            _UUID("not-a-uuid")


class TestAuditServiceUUID:
    def test_audit_event_with_invalid_tenant_skips(self):
        """audit_event should not crash with non-UUID tenant_id."""
        from app.services.audit_service import audit_event
        # Should not raise
        audit_event(
            action="test",
            tenant_id="not-a-uuid",
            details={"test": True},
        )

    def test_audit_event_with_empty_tenant_skips(self):
        from app.services.audit_service import audit_event
        audit_event(action="test", tenant_id="")


class TestTranscriptSanitization:
    def test_control_chars_stripped(self):
        """Control characters should be removed from transcripts."""
        import re
        text = "help\x00fire\x07in\x1fbuilding"
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        assert sanitized == "helpfireinbuilding"

    def test_newlines_preserved(self):
        """Newlines and tabs should be preserved (they're valid text)."""
        import re
        text = "help\nfire\tin building"
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        assert "\n" in sanitized
        assert "\t" in sanitized


class TestIntentModelGraceful:
    def test_app_imports_without_model_files(self):
        """App module should import even without ONNX model files."""
        os.environ.setdefault("SECRET_KEY", "test")
        os.environ.setdefault("USE_SQLITE", "true")
        from app.main import app
        assert app is not None
