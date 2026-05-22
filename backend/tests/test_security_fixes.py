"""Integration tests verifying security fixes are in place."""

import pytest


class TestSecurityConfiguration:
    """Verify security settings are correctly configured."""

    def test_jwt_expiry_is_reasonable(self):
        """HIGH-1: JWT should expire in hours, not days."""
        from app.core.config import settings
        assert settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 480, (
            f"JWT expiry is {settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes "
            f"({settings.ACCESS_TOKEN_EXPIRE_MINUTES / 60:.0f} hours). "
            f"Should be <= 8 hours for emergency system."
        )

    def test_upload_size_limit_exists(self):
        """CRIT-5: Audio upload size must be bounded."""
        from app.core.config import settings
        assert hasattr(settings, "MAX_AUDIO_BYTES")
        assert settings.MAX_AUDIO_BYTES <= 50 * 1024 * 1024  # max 50MB

    def test_transcript_length_limit_exists(self):
        """HIGH-7: Transcript length must be bounded."""
        from app.core.config import settings
        assert hasattr(settings, "MAX_TRANSCRIPT_LENGTH")
        assert settings.MAX_TRANSCRIPT_LENGTH <= 50_000

    def test_allowed_audio_types_defined(self):
        """CRIT-5: Allowed audio MIME types must be defined."""
        from app.core.config import settings
        assert hasattr(settings, "ALLOWED_AUDIO_TYPES")
        assert len(settings.ALLOWED_AUDIO_TYPES) > 0
        assert "audio/wav" in settings.ALLOWED_AUDIO_TYPES

    def test_cors_no_wildcard_in_primary_app(self):
        """CRIT-4: CORS must not use wildcard."""
        from app.core.config import settings
        assert "*" not in settings.allowed_origins_list

    def test_emotion_model_paths_exist(self):
        """CRIT-6: Emotion model paths must be configured."""
        from app.core.config import settings
        assert hasattr(settings, "EMOTION_ONNX_PATH")
        assert hasattr(settings, "EMOTION_PT_PATH")
        assert "emotion_model" in settings.EMOTION_ONNX_PATH

    def test_sqlite_blocked_in_production(self):
        """MED-2: SQLite must not be allowed in production."""
        from app.core.config import Settings
        import os
        # Temporarily override env vars to simulate production + sqlite
        original_env = os.environ.get("APP_ENV")
        original_sqlite = os.environ.get("USE_SQLITE")
        try:
            os.environ["APP_ENV"] = "production"
            os.environ["USE_SQLITE"] = "true"
            s = Settings()
            with pytest.raises(RuntimeError, match="not supported in production"):
                _ = s.SQLALCHEMY_DATABASE_URI
        finally:
            if original_env is not None:
                os.environ["APP_ENV"] = original_env
            else:
                os.environ.pop("APP_ENV", None)
            if original_sqlite is not None:
                os.environ["USE_SQLITE"] = original_sqlite
            else:
                os.environ.pop("USE_SQLITE", None)


class TestPasswordValidation:
    """Verify password strength requirements."""

    _tenant_id = "00000000-0000-0000-0000-000000000001"

    def test_weak_password_rejected(self):
        """LOW-4: Short passwords must be rejected."""
        from app.schemas.user import UserCreate
        with pytest.raises(Exception):
            UserCreate(email="test@test.com", password="short", tenant_id=self._tenant_id)

    def test_no_uppercase_rejected(self):
        """LOW-4: Passwords without uppercase must be rejected."""
        from app.schemas.user import UserCreate
        with pytest.raises(Exception):
            UserCreate(email="test@test.com", password="alllowercase123", tenant_id=self._tenant_id)

    def test_no_digit_rejected(self):
        """LOW-4: Passwords without digits must be rejected."""
        from app.schemas.user import UserCreate
        with pytest.raises(Exception):
            UserCreate(email="test@test.com", password="NoDigitsHere!", tenant_id=self._tenant_id)

    def test_strong_password_accepted(self):
        """Passwords meeting all criteria should be accepted."""
        from app.schemas.user import UserCreate
        user = UserCreate(email="test@test.com", password="SecurePass123!", tenant_id=self._tenant_id)
        assert user.password == "SecurePass123!"


class TestDispatchServiceCleanup:
    """Verify dead code was removed."""

    def test_dispatch_service_class_removed(self):
        """DispatchService class should no longer exist."""
        from app.services import dispatch_service
        assert not hasattr(dispatch_service, "DispatchService")

    def test_select_responder_exists(self):
        """select_responder function should still exist."""
        from app.services.dispatch_service import select_responder
        assert callable(select_responder)


class TestSecurityHeaders:
    """Verify security headers middleware exists."""

    def test_middleware_importable(self):
        """Security headers middleware should be importable."""
        from app.middleware.security_headers import SecurityHeadersMiddleware
        assert SecurityHeadersMiddleware is not None


class TestDatabaseHealth:
    """Verify database health check function exists."""

    def test_check_db_health_exists(self):
        """check_db_health function should exist."""
        from app.core.database import check_db_health
        assert callable(check_db_health)
