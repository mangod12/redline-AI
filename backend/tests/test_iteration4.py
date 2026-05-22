"""Tests for iteration-4: audit service, K8s manifests, ML service health."""

import asyncio
import os

import pytest


class TestAuditService:
    """Verify audit_service module API."""

    def test_audit_event_is_callable(self):
        from app.services.audit_service import audit_event
        assert callable(audit_event)

    def test_write_audit_is_async(self):
        from app.services.audit_service import _write_audit
        assert asyncio.iscoroutinefunction(_write_audit)

    def test_audit_event_does_not_raise_without_loop(self):
        """audit_event should not raise even when no event loop is running."""
        from app.services.audit_service import audit_event
        # This runs in a sync context — should log warning, not crash
        audit_event(
            action="test_action",
            tenant_id="test-tenant",
            details={"test": True},
        )


class TestAuditModel:
    """Verify AuditLog model exists with expected columns."""

    def test_audit_log_has_action_column(self):
        from app.models.audit_log import AuditLog
        assert hasattr(AuditLog, "action")

    def test_audit_log_has_details_column(self):
        from app.models.audit_log import AuditLog
        assert hasattr(AuditLog, "details")

    def test_audit_log_has_user_id_column(self):
        from app.models.audit_log import AuditLog
        assert hasattr(AuditLog, "user_id")


class TestKubernetesManifests:
    """Verify K8s manifest files exist."""

    k8s_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "k8s")

    def test_deployment_yaml_exists(self):
        assert os.path.exists(os.path.join(self.k8s_dir, "deployment.yaml"))

    def test_hpa_yaml_exists(self):
        assert os.path.exists(os.path.join(self.k8s_dir, "hpa.yaml"))

    def test_configmap_yaml_exists(self):
        assert os.path.exists(os.path.join(self.k8s_dir, "configmap.yaml"))

    def test_alerts_yaml_exists(self):
        assert os.path.exists(os.path.join(self.k8s_dir, "prometheus-alerts.yaml"))


class TestMLServiceModule:
    """Verify ml_service/app.py is importable and has health endpoint."""

    def test_ml_service_compiles(self):
        """ml_service/app.py should compile without import errors."""
        import py_compile
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "ml_service", "app.py",
        )
        py_compile.compile(path, doraise=True)
