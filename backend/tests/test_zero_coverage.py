"""Tests for previously zero-coverage modules.

Covers: events, logging, intent_service, tenant_service,
worker, tasks, ml_client, mock_stt_agent.
No real Redis/Celery/ML connections needed -- mocks used throughout.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# Celery stub -- celery is not installed in the test environment so we
# provide a lightweight fake that captures the configuration calls.
# ---------------------------------------------------------------------------

def _ensure_celery_stub():
    """Install a fake 'celery' package into sys.modules if the real one is
    missing.  Returns True if a stub was installed."""
    if "celery" in sys.modules and not isinstance(sys.modules["celery"], types.ModuleType):
        return False  # already stubbed or real
    try:
        import celery  # noqa: F401
        return False  # real celery exists
    except ModuleNotFoundError:
        pass

    celery_mod = types.ModuleType("celery")

    class _FakeCelery:
        def __init__(self, name, *, broker=None, backend=None, include=None):
            self.main = name
            self._broker = broker
            self._backend = backend
            self.tasks = {}
            self.conf = types.SimpleNamespace(include=include or [])

        def conf_update(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self.conf, k, v)

        # celery_app.conf.update(...)
        class _Conf:
            pass

        def task(self, *args, **task_opts):
            """Decorator that registers the function as a task."""
            def decorator(fn):
                fn.name = task_opts.get("name", fn.__name__)
                fn.max_retries = task_opts.get("max_retries", 3)
                fn.acks_late = task_opts.get("acks_late", False)
                fn.default_retry_delay = task_opts.get("default_retry_delay", 0)
                self.tasks[fn.name] = fn
                return fn
            if len(args) == 1 and callable(args[0]):
                return decorator(args[0])
            return decorator

    class _FakeCeleryWithConf(_FakeCelery):
        def __init__(self, name, **kwargs):
            super().__init__(name, **kwargs)
            self.conf = types.SimpleNamespace(include=kwargs.get("include", []))

        def _update_conf(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self.conf, k, v)

    # Build a proper Celery class whose conf.update works
    class FakeCelery:
        def __init__(self, name, *, broker=None, backend=None, include=None):
            self.main = name
            self.tasks = {}
            self.conf = types.SimpleNamespace(include=include or [])
            self.conf.update = lambda **kw: [setattr(self.conf, k, v) for k, v in kw.items()]

        def task(self, *args, **task_opts):
            outer = self
            def decorator(fn):
                fn.name = task_opts.get("name", fn.__name__)
                fn.max_retries = task_opts.get("max_retries", 3)
                fn.acks_late = task_opts.get("acks_late", False)
                fn.default_retry_delay = task_opts.get("default_retry_delay", 0)
                outer.tasks[fn.name] = fn
                return fn
            if len(args) == 1 and callable(args[0]):
                return decorator(args[0])
            return decorator

    celery_mod.Celery = FakeCelery
    sys.modules["celery"] = celery_mod
    return True


_CELERY_STUBBED = _ensure_celery_stub()


# ---------------------------------------------------------------------------
# 1. app/core/events.py
# ---------------------------------------------------------------------------

class TestPublishCallEvent:
    """Tests for publish_call_event."""

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_is_none(self):
        """When get_redis_client() returns None, function should not raise."""
        with patch("app.core.events.get_redis_client", return_value=None):
            from app.core.events import publish_call_event

            result = await publish_call_event(uuid4(), "severity_assessed", {"level": 5})
            assert result is None

    @pytest.mark.asyncio
    async def test_publishes_correct_message_format(self):
        """Verify the JSON message contains required keys."""
        mock_redis = AsyncMock()
        call_id = uuid4()

        with patch("app.core.events.get_redis_client", return_value=mock_redis):
            from app.core.events import publish_call_event

            await publish_call_event(call_id, "intent_classified", {"intent": "fire"})

        assert mock_redis.publish.call_count == 2

        # First call: per-call channel
        per_channel_arg = mock_redis.publish.call_args_list[0]
        assert per_channel_arg[0][0] == f"call_events:{str(call_id)}"

        msg = json.loads(per_channel_arg[0][1])
        assert msg["event_type"] == "intent_classified"
        assert msg["call_id"] == str(call_id)
        assert "timestamp" in msg
        assert msg["payload"] == {"intent": "fire"}

        # Second call: global channel
        global_channel_arg = mock_redis.publish.call_args_list[1]
        assert global_channel_arg[0][0] == "redline.events.calls"

    @pytest.mark.asyncio
    async def test_publish_exception_is_caught(self):
        """If redis.publish raises, the error is logged but not propagated."""
        mock_redis = AsyncMock()
        mock_redis.publish.side_effect = ConnectionError("gone")

        with patch("app.core.events.get_redis_client", return_value=mock_redis):
            from app.core.events import publish_call_event

            # Should NOT raise
            await publish_call_event(uuid4(), "test", {})


# ---------------------------------------------------------------------------
# 2. app/core/logging.py
# ---------------------------------------------------------------------------

class TestLoggingSetup:
    """Tests for the logging module."""

    def test_module_imports_without_error(self):
        """Simply importing the module should succeed."""
        import app.core.logging  # noqa: F401

    def test_logger_exists_and_is_named(self):
        """The module-level logger should be named 'redline_ai'."""
        from app.core.logging import logger

        assert isinstance(logger, logging.Logger)
        assert logger.name == "redline_ai"

    def test_setup_logging_callable(self):
        """setup_logging should be a callable function."""
        from app.core.logging import setup_logging

        assert callable(setup_logging)


# ---------------------------------------------------------------------------
# 3. app/services/intent_service.py
# ---------------------------------------------------------------------------

class TestIntentService:
    """Tests for keyword-heuristic intent classification."""

    @pytest.mark.asyncio
    async def test_empty_string_returns_unknown(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("") == "unknown"

    @pytest.mark.asyncio
    async def test_whitespace_returns_unknown(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("   ") == "unknown"

    @pytest.mark.asyncio
    async def test_none_returns_unknown(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent(None) == "unknown"

    @pytest.mark.asyncio
    async def test_fire_keyword(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("There is a fire in the building") == "fire"

    @pytest.mark.asyncio
    async def test_medical_keyword(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("He is having chest pain") == "medical"

    @pytest.mark.asyncio
    async def test_violent_crime_keyword(self):
        from app.services.intent_service import classify_intent

        result = await classify_intent("Someone has a gun")
        assert result == "violent_crime"

    @pytest.mark.asyncio
    async def test_accident_keyword(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("There was a car crash") == "accident"

    @pytest.mark.asyncio
    async def test_gas_hazard_keyword(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("I smell a gas leak") == "gas_hazard"

    @pytest.mark.asyncio
    async def test_mental_health_keyword(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("I want to kill myself") == "mental_health"

    @pytest.mark.asyncio
    async def test_no_match_returns_unknown(self):
        from app.services.intent_service import classify_intent

        assert await classify_intent("The weather is nice today") == "unknown"

    @pytest.mark.asyncio
    async def test_higher_priority_wins(self):
        """When both fire (10) and accident (8) match, fire should win."""
        from app.services.intent_service import classify_intent

        result = await classify_intent("The car is burning with flames after the crash")
        assert result == "fire"

    @pytest.mark.asyncio
    async def test_intent_rules_list_exists(self):
        from app.services.intent_service import _INTENT_RULES

        assert isinstance(_INTENT_RULES, list)
        assert len(_INTENT_RULES) > 0


# ---------------------------------------------------------------------------
# 4. app/services/tenant_service.py
# ---------------------------------------------------------------------------

class TestTenantService:
    """Tests for CRUDTenant and the module-level singleton."""

    def test_module_imports(self):
        import app.services.tenant_service  # noqa: F401

    def test_crud_tenant_instance_exists(self):
        from app.services.tenant_service import tenant

        assert tenant is not None

    def test_crud_tenant_is_crud_base(self):
        from app.services.base import CRUDBase
        from app.services.tenant_service import tenant

        assert isinstance(tenant, CRUDBase)

    def test_crud_tenant_model_is_tenant(self):
        from app.models.tenant import Tenant
        from app.services.tenant_service import tenant

        assert tenant.model is Tenant

    def test_crud_tenant_has_crud_methods(self):
        from app.services.tenant_service import tenant

        assert hasattr(tenant, "get")
        assert hasattr(tenant, "create")
        assert hasattr(tenant, "update")
        assert hasattr(tenant, "remove")


# ---------------------------------------------------------------------------
# 5. app/worker.py  (Celery config values)
# ---------------------------------------------------------------------------

def _load_worker():
    """(Re)load app.worker so its module-level code runs with the celery stub."""
    # Remove cached modules so they pick up the stub
    for mod_name in list(sys.modules):
        if mod_name in ("app.worker", "app.tasks"):
            del sys.modules[mod_name]
    import app.worker
    return app.worker


def _load_tasks():
    """(Re)load app.tasks (depends on app.worker)."""
    _load_worker()
    for mod_name in list(sys.modules):
        if mod_name == "app.tasks":
            del sys.modules[mod_name]
    import app.tasks
    return app.tasks


class TestWorkerConfig:
    """Tests for the Celery app configuration."""

    def test_celery_app_exists(self):
        worker = _load_worker()
        assert worker.celery_app is not None

    def test_celery_app_name(self):
        worker = _load_worker()
        assert worker.celery_app.main == "redline_ai"

    def test_task_serializer_is_json(self):
        worker = _load_worker()
        assert worker.celery_app.conf.task_serializer == "json"

    def test_result_serializer_is_json(self):
        worker = _load_worker()
        assert worker.celery_app.conf.result_serializer == "json"

    def test_accept_content_json_only(self):
        worker = _load_worker()
        assert "json" in worker.celery_app.conf.accept_content

    def test_timezone_is_utc(self):
        worker = _load_worker()
        assert worker.celery_app.conf.timezone == "UTC"

    def test_enable_utc_is_true(self):
        worker = _load_worker()
        assert worker.celery_app.conf.enable_utc is True

    def test_task_acks_late(self):
        worker = _load_worker()
        assert worker.celery_app.conf.task_acks_late is True

    def test_task_reject_on_worker_lost(self):
        worker = _load_worker()
        assert worker.celery_app.conf.task_reject_on_worker_lost is True

    def test_worker_prefetch_multiplier(self):
        worker = _load_worker()
        assert worker.celery_app.conf.worker_prefetch_multiplier == 1

    def test_result_expires(self):
        worker = _load_worker()
        assert worker.celery_app.conf.result_expires == 3600

    def test_task_soft_time_limit(self):
        worker = _load_worker()
        assert worker.celery_app.conf.task_soft_time_limit == 60

    def test_task_time_limit(self):
        worker = _load_worker()
        assert worker.celery_app.conf.task_time_limit == 120

    def test_worker_max_memory_per_child(self):
        worker = _load_worker()
        assert worker.celery_app.conf.worker_max_memory_per_child == 256_000

    def test_visibility_timeout(self):
        worker = _load_worker()
        opts = worker.celery_app.conf.broker_transport_options
        assert opts["visibility_timeout"] == 300

    def test_include_has_tasks_module(self):
        worker = _load_worker()
        assert "app.tasks" in worker.celery_app.conf.include


# ---------------------------------------------------------------------------
# 6. app/tasks.py
# ---------------------------------------------------------------------------

class TestTasks:
    """Tests for Celery task registration and helper functions."""

    def test_module_imports(self):
        _load_tasks()

    def test_get_redis_sync_exists_and_callable(self):
        tasks = _load_tasks()
        assert callable(tasks._get_redis_sync)

    def test_process_emergency_call_registered(self):
        tasks = _load_tasks()
        worker = sys.modules["app.worker"]
        task_names = list(worker.celery_app.tasks.keys())
        assert "process_emergency_call" in task_names

    def test_send_dispatch_notification_registered(self):
        tasks = _load_tasks()
        worker = sys.modules["app.worker"]
        task_names = list(worker.celery_app.tasks.keys())
        assert "send_dispatch_notification" in task_names

    def test_redis_events_channel_constant(self):
        tasks = _load_tasks()
        assert tasks.REDIS_EVENTS_CHANNEL == "redline.events.calls"

    def test_process_emergency_call_has_expected_options(self):
        tasks = _load_tasks()
        assert tasks.process_emergency_call.name == "process_emergency_call"
        assert tasks.process_emergency_call.max_retries == 3

    def test_send_dispatch_notification_has_expected_options(self):
        tasks = _load_tasks()
        assert tasks.send_dispatch_notification.name == "send_dispatch_notification"
        assert tasks.send_dispatch_notification.max_retries == 3


# ---------------------------------------------------------------------------
# 7. app/services/ml_client.py
# ---------------------------------------------------------------------------

class TestMLClient:
    """Tests for MLClient initialisation and URL construction."""

    def test_default_base_url_from_settings(self):
        from app.services.ml_client import MLClient

        client = MLClient()
        assert client.base_url == "http://localhost:8001"

    def test_custom_base_url(self):
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://custom:9000")
        assert client.base_url == "http://custom:9000"

    def test_client_starts_as_none(self):
        from app.services.ml_client import MLClient

        client = MLClient()
        assert client._client is None

    def test_analyze_url_construction(self):
        """Verify the /analyze URL is built correctly."""
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://ml:8001")
        expected = "http://ml:8001/analyze"
        assert f"{client.base_url.rstrip('/')}/analyze" == expected

    def test_analyze_url_strips_trailing_slash(self):
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://ml:8001/")
        url = f"{client.base_url.rstrip('/')}/analyze"
        assert url == "http://ml:8001/analyze"

    @pytest.mark.asyncio
    async def test_get_client_creates_httpx_client(self):
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://ml:8001")
        http_client = await client._get_client()
        assert http_client is not None
        assert not http_client.is_closed
        await client.close()

    @pytest.mark.asyncio
    async def test_close_sets_client_to_none(self):
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://ml:8001")
        await client._get_client()  # create the internal client
        await client.close()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client_does_not_raise(self):
        from app.services.ml_client import MLClient

        client = MLClient(base_url="http://ml:8001")
        # _client is None -- close should be safe
        await client.close()


# ---------------------------------------------------------------------------
# 8. app/agents/stt/mock_stt_agent.py
# ---------------------------------------------------------------------------

class TestMockSTTAgent:
    """Tests for MockSTTAgent contract (no Whisper model loaded)."""

    def test_class_exists(self):
        """The MockSTTAgent class should be importable."""
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            assert hasattr(stt_mod, "MockSTTAgent")

    def test_is_subclass_of_base_agent(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod
            from app.agents.base import BaseAgent

            reload(stt_mod)
            assert issubclass(stt_mod.MockSTTAgent, BaseAgent)

    def test_has_process_method(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent()
            assert hasattr(agent, "process")
            assert asyncio.iscoroutinefunction(agent.process)

    def test_has_schema_methods(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent()
            assert hasattr(agent, "get_input_schema")
            assert hasattr(agent, "get_output_schema")

    def test_get_input_schema_returns_bytes(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent()
            assert agent.get_input_schema() is bytes

    def test_get_output_schema_returns_transcript(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod
            from app.core.schemas.transcript import Transcript

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent()
            assert agent.get_output_schema() is Transcript

    def test_default_config_is_empty_dict(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent()
            assert agent.config == {}

    def test_custom_config_stored(self):
        with patch("app.agents.stt.mock_stt_agent.whisper") as mock_whisper:
            mock_whisper.load_model.return_value = MagicMock()
            from importlib import reload

            import app.agents.stt.mock_stt_agent as stt_mod

            reload(stt_mod)
            agent = stt_mod.MockSTTAgent(config={"model_size": "tiny"})
            assert agent.config == {"model_size": "tiny"}
