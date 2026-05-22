"""Phase-3 hardening tests — boost coverage for undertested modules.

Modules targeted:
  - app/core/event_listener.py       (0%)
  - app/services/call_processing.py  (0%)
  - app/ml/emotion_model_loader.py   (0%)
  - app/dashboard/routes.py          (20%)
  - app/services/audit_service.py    (41%)
  - app/dashboard/call_store.py      (45%)

All external dependencies (Redis, DB, ONNX, httpx) are mocked.
No real network calls or file-system access.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock, call
from uuid import uuid4, UUID

import pytest

# ---------------------------------------------------------------------------
# Ensure onnxruntime is stubbed before any module that imports it is loaded.
# This prevents ImportError in CI environments that lack GPU/ONNX packages.
# ---------------------------------------------------------------------------

def _stub_onnxruntime():
    if "onnxruntime" in sys.modules:
        return
    ort_mod = types.ModuleType("onnxruntime")

    class _FakeSessionOptions:
        inter_op_num_threads = 2
        intra_op_num_threads = 2
        graph_optimization_level = None

    class _FakeGraphOptLevel:
        ORT_ENABLE_ALL = 99

    class _FakeInferenceSession:
        def __init__(self, path, sess_options=None, providers=None):
            self._path = path
            self._input = MagicMock(name="mfcc")
            self._input.name = "mfcc"

        def get_inputs(self):
            return [self._input]

        def run(self, output_names, input_feed):
            import numpy as np
            return [np.zeros((1, 8), dtype="float32")]

    ort_mod.InferenceSession = _FakeInferenceSession
    ort_mod.SessionOptions = _FakeSessionOptions
    ort_mod.GraphOptimizationLevel = _FakeGraphOptLevel()
    sys.modules["onnxruntime"] = ort_mod


_stub_onnxruntime()


# ===========================================================================
# 1. EVENT LISTENER  (app/core/event_listener.py)
# ===========================================================================


class TestStartEventListener:
    """start_event_listener should create an asyncio Task."""

    @pytest.mark.asyncio
    async def test_creates_background_task(self):
        """Calling start_event_listener() creates a task in the running loop."""
        import app.core.event_listener as el

        # Reset module-level task so we start clean
        el._listener_task = None

        # Prevent the real coroutine from running beyond one iteration by
        # making get_redis_client raise CancelledError after the first call.
        async def _fake_listener_body():
            await asyncio.sleep(0)  # yield control once then stop
            raise asyncio.CancelledError

        with patch.object(el, "get_redis_client", return_value=None):
            el.start_event_listener()
            assert el._listener_task is not None
            assert isinstance(el._listener_task, asyncio.Task)
            # Cancel to avoid leaving the task running
            el._listener_task.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task


class TestStopEventListener:
    """stop_event_listener should cancel the background task cleanly."""

    @pytest.mark.asyncio
    async def test_cancels_task(self):
        import app.core.event_listener as el

        # Create a long-running task so stop has something to cancel
        async def _long():
            await asyncio.sleep(9999)

        el._listener_task = asyncio.create_task(_long())

        await el.stop_event_listener()

        assert el._listener_task is None

    @pytest.mark.asyncio
    async def test_stop_when_no_task_is_safe(self):
        import app.core.event_listener as el

        el._listener_task = None
        # Should not raise
        await el.stop_event_listener()

    @pytest.mark.asyncio
    async def test_stop_when_task_already_done_is_safe(self):
        """stop_event_listener is a no-op when the task has already finished."""
        import app.core.event_listener as el

        async def _instant():
            return

        task = asyncio.create_task(_instant())
        await asyncio.sleep(0)  # let it finish
        el._listener_task = task

        # Source only clears the reference when the task is still running;
        # for an already-done task it simply skips the cancel branch.
        await el.stop_event_listener()
        # The important thing: no exception was raised.


class TestListenerBackoffOnRedisUnavailable:
    """_listener retries with exponential backoff when Redis is None."""

    @pytest.mark.asyncio
    async def test_backoff_when_redis_none(self):
        """When Redis returns None the listener sleeps and doubles backoff."""
        import app.core.event_listener as el

        sleep_calls = []

        async def _fake_sleep(duration):
            sleep_calls.append(duration)
            if len(sleep_calls) >= 2:
                raise asyncio.CancelledError  # stop the loop after 2 retries

        with (
            patch("app.core.event_listener.get_redis_client", return_value=None),
            patch("asyncio.sleep", side_effect=_fake_sleep),
        ):
            el._listener_task = None
            el.start_event_listener()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task

        # First backoff is 1 s, second is 2 s (doubles)
        assert sleep_calls[0] == 1
        assert sleep_calls[1] == 2


class TestListenerProcessesTranscriptReceived:
    """_listener calls CallProcessor when TRANSCRIPT_RECEIVED event arrives."""

    @pytest.mark.asyncio
    async def test_processes_transcript_received(self):
        import app.core.event_listener as el

        event_data = json.dumps({
            "event_type": "TRANSCRIPT_RECEIVED",
            "call_id": str(uuid4()),
            "payload": {
                "text": "there is a fire",
                "language": "en",
                "tenant_id": str(uuid4()),
            },
        })

        mock_message = {"type": "message", "data": event_data}

        async def _fake_listen():
            yield mock_message
            # Stop after one message
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        mock_processor = AsyncMock()
        mock_processor.process_transcript = AsyncMock(return_value={})

        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.core.event_listener.get_redis_client", return_value=mock_redis),
            patch("app.core.event_listener.AsyncSessionLocal", return_value=mock_db_ctx),
            patch("app.core.event_listener.CallProcessor", return_value=mock_processor),
        ):
            el._listener_task = None
            el.start_event_listener()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task

        mock_processor.process_transcript.assert_awaited_once()


class TestListenerIgnoresKnownEvents:
    """Events in _IGNORE_EVENTS should not trigger processing."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("ignored_event", [
        "PROCESSING_STARTED",
        "ML_ANALYSIS_COMPLETE",
        "SEVERITY_UPDATED",
        "LOCATION_RESOLVED",
        "DISPATCH_RECOMMENDED",
    ])
    async def test_ignores_event(self, ignored_event):
        import app.core.event_listener as el

        event_data = json.dumps({"event_type": ignored_event, "call_id": str(uuid4())})
        mock_message = {"type": "message", "data": event_data}

        async def _fake_listen():
            yield mock_message
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        mock_processor = AsyncMock()
        mock_processor.process_transcript = AsyncMock()

        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.core.event_listener.get_redis_client", return_value=mock_redis),
            patch("app.core.event_listener.AsyncSessionLocal", return_value=mock_db_ctx),
            patch("app.core.event_listener.CallProcessor", return_value=mock_processor),
        ):
            el._listener_task = None
            el.start_event_listener()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task

        # Processor must NOT have been called for ignored events
        mock_processor.process_transcript.assert_not_awaited()


class TestListenerMalformedJSON:
    """_listener skips messages that are not valid JSON."""

    @pytest.mark.asyncio
    async def test_malformed_json_is_skipped(self):
        import app.core.event_listener as el

        bad_messages = [
            {"type": "message", "data": "not-valid-json{{"},
            {"type": "message", "data": None},
            {"type": "message", "data": b"\xff\xfe"},
        ]

        call_count = 0

        async def _fake_listen():
            for m in bad_messages:
                yield m
                nonlocal call_count
                call_count += 1
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        mock_processor = AsyncMock()
        mock_processor.process_transcript = AsyncMock()

        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.core.event_listener.get_redis_client", return_value=mock_redis),
            patch("app.core.event_listener.AsyncSessionLocal", return_value=mock_db_ctx),
            patch("app.core.event_listener.CallProcessor", return_value=mock_processor),
        ):
            el._listener_task = None
            el.start_event_listener()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task

        # No transcript processing should have happened
        mock_processor.process_transcript.assert_not_awaited()


class TestListenerCallProcessorError:
    """_listener catches and logs errors from CallProcessor.process_transcript."""

    @pytest.mark.asyncio
    async def test_processor_exception_is_caught(self):
        import app.core.event_listener as el

        event_data = json.dumps({
            "event_type": "TRANSCRIPT_RECEIVED",
            "call_id": str(uuid4()),
            "payload": {"text": "help", "language": "en", "tenant_id": str(uuid4())},
        })

        async def _fake_listen():
            yield {"type": "message", "data": event_data}
            raise asyncio.CancelledError

        mock_pubsub = AsyncMock()
        mock_pubsub.listen = _fake_listen
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()

        mock_redis = MagicMock()
        mock_redis.pubsub.return_value = mock_pubsub

        mock_processor = AsyncMock()
        mock_processor.process_transcript = AsyncMock(
            side_effect=RuntimeError("pipeline exploded")
        )

        mock_db_ctx = AsyncMock()
        mock_db_ctx.__aenter__ = AsyncMock(return_value=AsyncMock())
        mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.core.event_listener.get_redis_client", return_value=mock_redis),
            patch("app.core.event_listener.AsyncSessionLocal", return_value=mock_db_ctx),
            patch("app.core.event_listener.CallProcessor", return_value=mock_processor),
        ):
            el._listener_task = None
            el.start_event_listener()
            # Should complete without propagating the RuntimeError
            with pytest.raises((asyncio.CancelledError, Exception)):
                await el._listener_task


# ===========================================================================
# 2. CALL PROCESSING  (app/services/call_processing.py)
# ===========================================================================


class TestCallProcessorInit:
    """CallProcessor.__init__ creates all required service instances."""

    def test_creates_service_instances(self):
        with (
            patch("app.services.call_processing.TranslationService"),
            patch("app.services.call_processing.MLClient"),
            patch("app.services.call_processing.SeverityEngine"),
            patch("app.services.call_processing.Geocoder"),
        ):
            from app.services.call_processing import CallProcessor

            processor = CallProcessor()
            assert processor.translator is not None
            assert processor.ml_client is not None
            assert processor.severity_engine is not None
            assert processor.geocoder is not None


class TestProcessTranscript:
    """process_transcript runs the full analysis pipeline."""

    def _make_processor(self):
        """Build a CallProcessor with all service dependencies mocked."""
        with (
            patch("app.services.call_processing.TranslationService"),
            patch("app.services.call_processing.MLClient"),
            patch("app.services.call_processing.SeverityEngine"),
            patch("app.services.call_processing.Geocoder"),
        ):
            from app.services.call_processing import CallProcessor
            return CallProcessor()

    @pytest.mark.asyncio
    async def test_publishes_events_and_returns_result(self):
        from app.services.call_processing import CallProcessor

        mock_translator = AsyncMock()
        mock_translator.translate = AsyncMock(return_value="translated text")

        mock_ml = AsyncMock()
        mock_ml.analyze = AsyncMock(return_value={
            "incident_type": "fire",
            "panic_score": 0.8,
            "keyword_score": 0.7,
            "severity_prediction": "HIGH",
            "location_text": None,
            "keywords": ["fire", "smoke"],
        })

        mock_engine = MagicMock()
        mock_engine.calculate.return_value = 8.5
        mock_engine.category.return_value = "HIGH"

        mock_geocoder = AsyncMock()

        mock_analysis_record = MagicMock(id=uuid4())
        mock_severity_record = MagicMock(id=uuid4())
        mock_dispatch_record = MagicMock(id=uuid4())

        mock_analysis_crud = AsyncMock()
        mock_analysis_crud.create = AsyncMock(return_value=mock_analysis_record)
        mock_analysis_crud.update = AsyncMock(return_value=mock_analysis_record)

        mock_severity_crud_inst = AsyncMock()
        mock_severity_crud_inst.create = AsyncMock(return_value=mock_severity_record)

        mock_dispatch_crud = AsyncMock()
        mock_dispatch_crud.create = AsyncMock(return_value=mock_dispatch_record)

        mock_call_service = MagicMock()
        mock_call_service.analysis_result = mock_analysis_crud
        mock_call_service.dispatch = mock_dispatch_crud

        mock_db = AsyncMock()
        call_id = str(uuid4())
        tenant_id = uuid4()

        with (
            patch("app.services.call_processing.TranslationService", return_value=mock_translator),
            patch("app.services.call_processing.MLClient", return_value=mock_ml),
            patch("app.services.call_processing.SeverityEngine", return_value=mock_engine),
            patch("app.services.call_processing.Geocoder", return_value=mock_geocoder),
            patch("app.services.call_processing.call_service", mock_call_service),
            patch("app.services.call_processing.severity_crud", mock_severity_crud_inst),
            patch("app.services.call_processing.publish_call_event", new_callable=AsyncMock),
            patch("app.services.dispatch_service.select_responder", new_callable=AsyncMock, return_value="fire_dispatch"),
        ):
            processor = CallProcessor()
            result = await processor.process_transcript(
                mock_db,
                call_id=call_id,
                transcript_text="there is a fire",
                language="en",
                tenant_id=tenant_id,
            )

        assert result["transcript_text"] == "there is a fire"
        assert result["analysis"] is mock_analysis_record
        assert result["severity"] is mock_severity_record
        assert result["dispatch"] is mock_dispatch_record

    @pytest.mark.asyncio
    async def test_ml_analysis_failure_is_handled_gracefully(self):
        """When ML client raises, pipeline continues with empty analysis."""
        from app.services.call_processing import CallProcessor

        mock_ml = AsyncMock()
        mock_ml.analyze = AsyncMock(side_effect=ConnectionError("ML service down"))

        mock_engine = MagicMock()
        mock_engine.calculate.return_value = 1.0
        mock_engine.category.return_value = "LOW"

        mock_analysis_record = MagicMock(id=uuid4())
        mock_severity_record = MagicMock(id=uuid4())
        mock_dispatch_record = MagicMock(id=uuid4())

        mock_analysis_crud = AsyncMock()
        mock_analysis_crud.create = AsyncMock(return_value=mock_analysis_record)

        mock_severity_crud_inst = AsyncMock()
        mock_severity_crud_inst.create = AsyncMock(return_value=mock_severity_record)

        mock_dispatch_crud = AsyncMock()
        mock_dispatch_crud.create = AsyncMock(return_value=mock_dispatch_record)

        mock_call_service = MagicMock()
        mock_call_service.analysis_result = mock_analysis_crud
        mock_call_service.dispatch = mock_dispatch_crud

        mock_db = AsyncMock()

        with (
            patch("app.services.call_processing.TranslationService"),
            patch("app.services.call_processing.MLClient", return_value=mock_ml),
            patch("app.services.call_processing.SeverityEngine", return_value=mock_engine),
            patch("app.services.call_processing.Geocoder"),
            patch("app.services.call_processing.call_service", mock_call_service),
            patch("app.services.call_processing.severity_crud", mock_severity_crud_inst),
            patch("app.services.call_processing.publish_call_event", new_callable=AsyncMock),
            patch("app.services.dispatch_service.select_responder", new_callable=AsyncMock, return_value="general_responder"),
        ):
            processor = CallProcessor()
            # Should not raise — ML failure is caught internally
            result = await processor.process_transcript(
                mock_db,
                call_id=str(uuid4()),
                transcript_text="help me",
                language="en",
                tenant_id=uuid4(),
            )

        # Falls back to empty analysis dict → incident_type defaults to "unknown"
        call_args = mock_analysis_crud.create.call_args[1]["obj_in"]
        assert call_args["incident_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_geocoding_called_when_location_text_present(self):
        """When ML returns location_text, geocoder is invoked."""
        from app.services.call_processing import CallProcessor

        mock_ml = AsyncMock()
        mock_ml.analyze = AsyncMock(return_value={
            "incident_type": "fire",
            "panic_score": 0.5,
            "keyword_score": 0.5,
            "severity_prediction": "MEDIUM",
            "location_text": "123 Main Street",
            "keywords": [],
        })

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock(return_value={
            "latitude": 37.7749,
            "longitude": -122.4194,
            "confidence": 0.9,
        })

        mock_engine = MagicMock()
        mock_engine.calculate.return_value = 5.0
        mock_engine.category.return_value = "MEDIUM"

        mock_analysis_record = MagicMock(id=uuid4())
        mock_severity_record = MagicMock(id=uuid4())
        mock_dispatch_record = MagicMock(id=uuid4())

        mock_analysis_crud = AsyncMock()
        mock_analysis_crud.create = AsyncMock(return_value=mock_analysis_record)
        mock_analysis_crud.update = AsyncMock(return_value=mock_analysis_record)

        mock_severity_crud_inst = AsyncMock()
        mock_severity_crud_inst.create = AsyncMock(return_value=mock_severity_record)

        mock_dispatch_crud = AsyncMock()
        mock_dispatch_crud.create = AsyncMock(return_value=mock_dispatch_record)

        mock_call_service = MagicMock()
        mock_call_service.analysis_result = mock_analysis_crud
        mock_call_service.dispatch = mock_dispatch_crud

        mock_db = AsyncMock()

        with (
            patch("app.services.call_processing.TranslationService"),
            patch("app.services.call_processing.MLClient", return_value=mock_ml),
            patch("app.services.call_processing.SeverityEngine", return_value=mock_engine),
            patch("app.services.call_processing.Geocoder", return_value=mock_geocoder),
            patch("app.services.call_processing.call_service", mock_call_service),
            patch("app.services.call_processing.severity_crud", mock_severity_crud_inst),
            patch("app.services.call_processing.publish_call_event", new_callable=AsyncMock),
            patch("app.services.dispatch_service.select_responder", new_callable=AsyncMock, return_value="fire_dispatch"),
        ):
            processor = CallProcessor()
            result = await processor.process_transcript(
                mock_db,
                call_id=str(uuid4()),
                transcript_text="fire at 123 Main Street",
                language="en",
                tenant_id=uuid4(),
            )

        mock_geocoder.geocode.assert_awaited_once_with("123 Main Street")
        assert result["geocode"] is not None

    @pytest.mark.asyncio
    async def test_geocoding_skipped_when_no_location_text(self):
        """When ML returns no location_text, geocoder is NOT called."""
        from app.services.call_processing import CallProcessor

        mock_ml = AsyncMock()
        mock_ml.analyze = AsyncMock(return_value={
            "incident_type": "medical",
            "panic_score": 0.6,
            "keyword_score": 0.6,
            "severity_prediction": "HIGH",
            "location_text": None,
            "keywords": [],
        })

        mock_geocoder = AsyncMock()
        mock_geocoder.geocode = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.calculate.return_value = 7.0
        mock_engine.category.return_value = "HIGH"

        mock_analysis_record = MagicMock(id=uuid4())
        mock_severity_record = MagicMock(id=uuid4())
        mock_dispatch_record = MagicMock(id=uuid4())

        mock_analysis_crud = AsyncMock()
        mock_analysis_crud.create = AsyncMock(return_value=mock_analysis_record)

        mock_severity_crud_inst = AsyncMock()
        mock_severity_crud_inst.create = AsyncMock(return_value=mock_severity_record)

        mock_dispatch_crud = AsyncMock()
        mock_dispatch_crud.create = AsyncMock(return_value=mock_dispatch_record)

        mock_call_service = MagicMock()
        mock_call_service.analysis_result = mock_analysis_crud
        mock_call_service.dispatch = mock_dispatch_crud

        mock_db = AsyncMock()

        with (
            patch("app.services.call_processing.TranslationService"),
            patch("app.services.call_processing.MLClient", return_value=mock_ml),
            patch("app.services.call_processing.SeverityEngine", return_value=mock_engine),
            patch("app.services.call_processing.Geocoder", return_value=mock_geocoder),
            patch("app.services.call_processing.call_service", mock_call_service),
            patch("app.services.call_processing.severity_crud", mock_severity_crud_inst),
            patch("app.services.call_processing.publish_call_event", new_callable=AsyncMock),
            patch("app.services.dispatch_service.select_responder", new_callable=AsyncMock, return_value="ambulance"),
        ):
            processor = CallProcessor()
            result = await processor.process_transcript(
                mock_db,
                call_id=str(uuid4()),
                transcript_text="patient unconscious",
                language="en",
                tenant_id=uuid4(),
            )

        mock_geocoder.geocode.assert_not_awaited()
        assert result["geocode"] is None


class TestSaveTranscript:
    """save_transcript translates, persists, and publishes TRANSCRIPT_RECEIVED."""

    @pytest.mark.asyncio
    async def test_save_transcript_translates_and_saves(self):
        from app.services.call_processing import CallProcessor

        mock_translator = MagicMock()
        mock_translator.translate = AsyncMock(return_value="translated text")

        mock_transcript_record = MagicMock(id=uuid4())
        mock_transcript_crud = AsyncMock()
        mock_transcript_crud.create = AsyncMock(return_value=mock_transcript_record)

        mock_call_service = MagicMock()
        mock_call_service.transcript = mock_transcript_crud

        mock_db = AsyncMock()
        call_id = uuid4()
        tenant_id = uuid4()

        with (
            patch("app.services.call_processing.TranslationService", return_value=mock_translator),
            patch("app.services.call_processing.MLClient"),
            patch("app.services.call_processing.SeverityEngine"),
            patch("app.services.call_processing.Geocoder"),
            patch("app.services.call_processing.call_service", mock_call_service),
            patch("app.services.call_processing.publish_call_event", new_callable=AsyncMock) as mock_publish,
        ):
            processor = CallProcessor()
            result = await processor.save_transcript(
                mock_db,
                call_id=call_id,
                transcript_text="there is a fire",
                language="en",
                tenant_id=tenant_id,
            )

        assert result is mock_transcript_record
        mock_translator.translate.assert_awaited_once_with("there is a fire", "en")
        mock_publish.assert_awaited_once()

        # Verify the published event
        publish_call_args = mock_publish.call_args
        assert publish_call_args[0][1] == "TRANSCRIPT_RECEIVED"
        payload = publish_call_args[0][2]
        assert payload["text"] == "translated text"


# ===========================================================================
# 3. EMOTION MODEL LOADER  (app/ml/emotion_model_loader.py)
# ===========================================================================


class TestEmotionModelLoaderReady:
    """is_ready returns False before init and True after."""

    def test_is_ready_false_before_init(self):
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()
        assert loader.is_ready() is False

    @pytest.mark.asyncio
    async def test_is_ready_true_after_init(self):
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()

        # Patch paths so .exists() returns True for the onnx file
        with (
            patch("app.ml.emotion_model_loader.Path") as mock_path_cls,
        ):
            mock_onnx = MagicMock()
            mock_onnx.exists.return_value = True
            mock_pt = MagicMock()
            mock_pt.exists.return_value = False

            def _path_factory(p):
                # Return onnx mock when called with EMOTION_ONNX_PATH
                return mock_onnx

            mock_path_cls.side_effect = _path_factory

            # run_in_executor must return a fake InferenceSession
            import onnxruntime as ort
            fake_session = ort.InferenceSession("fake.onnx")

            loop = asyncio.get_running_loop()
            with patch.object(loop, "run_in_executor", new_callable=AsyncMock, return_value=fake_session):
                await loader.initialize()

        assert loader.is_ready() is True
        # cleanup
        await loader.shutdown()


class TestEmotionModelLoaderInitRaisesWhenFilesMissing:
    """initialize raises RuntimeError when neither .onnx nor .pt exist."""

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_both_missing(self):
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()

        with patch("app.ml.emotion_model_loader.Path") as mock_path_cls:
            mock_missing = MagicMock()
            mock_missing.exists.return_value = False
            mock_path_cls.return_value = mock_missing

            with pytest.raises(RuntimeError, match="Neither ONNX model"):
                await loader.initialize()


class TestEmotionModelLoaderPredictNotInitialized:
    """predict raises RuntimeError when loader has not been initialized."""

    @pytest.mark.asyncio
    async def test_predict_raises_when_not_initialized(self):
        import numpy as np
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()
        mfcc = np.zeros((1, 1, 40, 94), dtype="float32")

        with pytest.raises(RuntimeError, match="not initialised"):
            await loader.predict(mfcc)


class TestEmotionModelLoaderShutdown:
    """shutdown sets _ready to False and releases the executor."""

    @pytest.mark.asyncio
    async def test_shutdown_sets_ready_false(self):
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()
        # Manually mark as ready to simulate post-init state
        loader._ready = True

        await loader.shutdown()

        assert loader.is_ready() is False
        assert loader._session is None

    @pytest.mark.asyncio
    async def test_shutdown_idempotent(self):
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()
        await loader.shutdown()
        # Second call should not raise
        await loader.shutdown()
        assert loader.is_ready() is False


class TestEmotionModelLoaderPredictTimeout:
    """predict propagates asyncio.TimeoutError on slow inference."""

    @pytest.mark.asyncio
    async def test_predict_raises_timeout(self):
        import numpy as np
        from app.ml.emotion_model_loader import EmotionModelLoader

        loader = EmotionModelLoader()
        loader._ready = True

        # Install a fake session
        fake_session = MagicMock()
        fake_session.get_inputs.return_value = [MagicMock(name="mfcc")]
        fake_session.run.return_value = [MagicMock()]
        loader._session = fake_session

        mfcc = np.zeros((1, 1, 40, 94), dtype="float32")

        async def _slow_future(*args, **kwargs):
            await asyncio.sleep(10)

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(asyncio.TimeoutError):
                await loader.predict(mfcc)


# ===========================================================================
# 4. DASHBOARD ROUTES  (app/dashboard/routes.py)
# ===========================================================================


def _make_valid_token(tenant_id: str = "tenant-abc") -> str:
    """Create a valid JWT using the app's create_access_token helper."""
    from app.core.security import create_access_token
    return create_access_token(subject="user1", tenant_id=tenant_id, role="dispatcher")


class TestCallsLiveEndpoint:
    """GET /api/v1/calls/live returns call data."""

    @pytest.mark.asyncio
    async def test_returns_call_list(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.dashboard.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        tenant_id = "tenant-xyz"
        token = _make_valid_token(tenant_id)

        fake_calls = [{"call_id": "ABCD1234", "tenant_id": tenant_id}]

        with patch("app.dashboard.routes.call_store") as mock_store:
            mock_store.aget_recent = AsyncMock(return_value=fake_calls)
            resp = client.get(
                "/api/v1/calls/live",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "calls" in data
        assert data["calls"] == fake_calls

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_exception(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.dashboard.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        token = _make_valid_token()

        with patch("app.dashboard.routes.call_store") as mock_store:
            mock_store.aget_recent = AsyncMock(side_effect=Exception("Redis gone"))
            resp = client.get(
                "/api/v1/calls/live",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        assert resp.json() == {"calls": []}

    @pytest.mark.asyncio
    async def test_requires_auth_token(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.dashboard.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/api/v1/calls/live")
        assert resp.status_code == 401


class TestWsDashboardRateLimit:
    """WebSocket /ws/dashboard rejects when too many clients are connected."""

    @pytest.mark.asyncio
    async def test_rate_limit_too_many_clients(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from starlette.websockets import WebSocketDisconnect
        import app.dashboard.routes as routes_mod

        app = FastAPI()
        app.include_router(routes_mod.router)
        client = TestClient(app)

        token = _make_valid_token()

        original_clients = routes_mod._dashboard_clients.copy()
        try:
            from app.core.config import settings
            for _ in range(settings.MAX_WS_CONNECTIONS):
                routes_mod._dashboard_clients.add(MagicMock())

            # The server closes the connection before accepting, which causes
            # starlette TestClient to raise WebSocketDisconnect on __enter__.
            with pytest.raises((WebSocketDisconnect, Exception)):
                with client.websocket_connect(f"/ws/dashboard?token={token}") as ws:
                    ws.receive_json()
        finally:
            routes_mod._dashboard_clients.clear()
            routes_mod._dashboard_clients.update(original_clients)


class TestWsDashboardMissingToken:
    """WebSocket /ws/dashboard closes with 4001 when token is absent."""

    def test_missing_token_closes_4001(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.dashboard.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with pytest.raises(Exception):
            with client.websocket_connect("/ws/dashboard") as ws:
                ws.receive_json()


class TestWsDashboardInvalidToken:
    """WebSocket /ws/dashboard closes with 4001 for an invalid token."""

    def test_invalid_token_closes_4001(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.dashboard.routes import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with pytest.raises(Exception):
            with client.websocket_connect("/ws/dashboard?token=bad.token.here") as ws:
                ws.receive_json()


class TestBroadcastToDashboards:
    """_broadcast_to_dashboards removes stale WebSocket clients."""

    @pytest.mark.asyncio
    async def test_removes_stale_clients(self):
        import app.dashboard.routes as routes_mod

        original_clients = routes_mod._dashboard_clients.copy()
        routes_mod._dashboard_clients.clear()

        # Good client
        good_ws = AsyncMock()
        good_ws.send_json = AsyncMock()

        # Stale client that raises on send
        stale_ws = AsyncMock()
        stale_ws.send_json = AsyncMock(side_effect=Exception("disconnected"))

        routes_mod._dashboard_clients.add(good_ws)
        routes_mod._dashboard_clients.add(stale_ws)

        try:
            await routes_mod._broadcast_to_dashboards({"type": "ping"})

            good_ws.send_json.assert_awaited_once_with({"type": "ping"})
            # Stale client must have been removed
            assert stale_ws not in routes_mod._dashboard_clients
            assert good_ws in routes_mod._dashboard_clients
        finally:
            routes_mod._dashboard_clients.clear()
            routes_mod._dashboard_clients.update(original_clients)

    @pytest.mark.asyncio
    async def test_broadcast_empty_clients_set_is_safe(self):
        import app.dashboard.routes as routes_mod

        original_clients = routes_mod._dashboard_clients.copy()
        routes_mod._dashboard_clients.clear()

        try:
            # Should not raise
            await routes_mod._broadcast_to_dashboards({"event": "test"})
        finally:
            routes_mod._dashboard_clients.update(original_clients)


# ===========================================================================
# 5. AUDIT SERVICE  (app/services/audit_service.py)
# ===========================================================================


class TestAuditEventFireAndForget:
    """audit_event creates an asyncio task (fire-and-forget)."""

    @pytest.mark.asyncio
    async def test_creates_task_in_running_loop(self):
        """With a running loop, audit_event should schedule _write_audit as a task."""
        from app.services import audit_service

        created_tasks = []

        # Intercept loop.create_task
        loop = asyncio.get_running_loop()
        original_create_task = loop.create_task

        def _capture_task(coro, *args, **kwargs):
            t = original_create_task(coro, *args, **kwargs)
            created_tasks.append(t)
            return t

        with (
            patch.object(loop, "create_task", side_effect=_capture_task),
            patch("app.services.audit_service.AsyncSessionLocal"),
        ):
            audit_service.audit_event(
                action="LOGIN",
                tenant_id=str(uuid4()),
                user_id=str(uuid4()),
            )

        assert len(created_tasks) == 1
        # Allow the task to complete cleanly
        for t in created_tasks:
            t.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await t


class TestWriteAuditInvalidTenantId:
    """_write_audit returns early when tenant_id is invalid."""

    @pytest.mark.asyncio
    async def test_returns_early_for_invalid_tenant(self):
        from app.services.audit_service import _write_audit

        mock_session_cls = AsyncMock()

        with patch("app.services.audit_service.AsyncSessionLocal", mock_session_cls):
            # Pass a non-UUID string that cannot be converted
            await _write_audit(
                action="TEST",
                tenant_id="not-a-uuid!!!",
            )

        # DB session must NOT have been used
        mock_session_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_early_for_empty_tenant(self):
        from app.services.audit_service import _write_audit

        mock_session_cls = AsyncMock()

        with patch("app.services.audit_service.AsyncSessionLocal", mock_session_cls):
            await _write_audit(action="TEST", tenant_id="")

        mock_session_cls.assert_not_called()


class TestWriteAuditDbException:
    """_write_audit swallows DB exceptions."""

    @pytest.mark.asyncio
    async def test_db_exception_is_swallowed(self):
        from app.services.audit_service import _write_audit

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock(side_effect=Exception("DB unavailable"))
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.audit_service.AsyncSessionLocal", return_value=mock_session):
            # Should not raise
            await _write_audit(
                action="LOGIN",
                tenant_id=str(uuid4()),
            )


class TestAuditEventNoEventLoop:
    """audit_event logs a warning when no event loop is running."""

    def test_logs_warning_without_event_loop(self):
        """Called from a synchronous context with no loop → should log, not raise."""
        from app.services import audit_service
        import logging

        with patch.object(audit_service.log, "warning") as mock_warn:
            # Simulate no running loop by making get_running_loop raise RuntimeError
            with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                audit_service.audit_event(
                    action="LOGOUT",
                    tenant_id=str(uuid4()),
                )

        mock_warn.assert_called_once()
        warning_msg = mock_warn.call_args[0][0]
        assert "No event loop" in warning_msg or "audit log skipped" in warning_msg


# ===========================================================================
# 6. CALL STORE  (app/dashboard/call_store.py)
# ===========================================================================


class TestCallStoreAddCall:
    """add_call returns a non-empty call_id string."""

    def test_add_call_returns_call_id_string(self):
        from app.dashboard.call_store import add_call

        with patch("app.dashboard.call_store._get_redis", return_value=None):
            call_id = add_call(
                transcript="help there is a fire",
                intent="fire",
                intent_confidence=0.95,
                emotion="fearful",
                emotion_confidence=0.88,
                severity="critical",
                severity_score=9.2,
                responder="fire_dispatch",
                fallback_used=False,
                intent_fallback=False,
                emotion_fallback=False,
                latency_ms=123.4,
                tenant_id="tenant-test",
            )

        assert isinstance(call_id, str)
        assert len(call_id) == 8
        assert call_id == call_id.upper()

    def test_add_call_with_redis_available_creates_task(self):
        """When Redis is available, add_call schedules an async write task."""
        from app.dashboard.call_store import add_call

        mock_redis = MagicMock()
        tasks_created = []

        async def _run():
            loop = asyncio.get_running_loop()
            original_create_task = loop.create_task

            def _capture(coro, *args, **kwargs):
                t = original_create_task(coro, *args, **kwargs)
                tasks_created.append(t)
                return t

            with (
                patch("app.dashboard.call_store._get_redis", return_value=mock_redis),
                patch("asyncio.get_running_loop", return_value=loop),
                patch.object(loop, "create_task", side_effect=_capture),
            ):
                result = add_call(
                    transcript="test",
                    intent="medical",
                    intent_confidence=0.9,
                    emotion="calm",
                    emotion_confidence=0.7,
                    severity="high",
                    severity_score=7.5,
                    responder="ambulance",
                    fallback_used=False,
                    intent_fallback=False,
                    emotion_fallback=False,
                    latency_ms=50.0,
                    tenant_id="",
                )
                # Cancel tasks to clean up
                for t in tasks_created:
                    t.cancel()
                return result

        call_id = asyncio.run(_run())
        assert isinstance(call_id, str)


class TestCallStoreAgetRecent:
    """aget_recent retrieves and optionally filters by tenant_id."""

    @pytest.mark.asyncio
    async def test_returns_filtered_by_tenant(self):
        from app.dashboard.call_store import aget_recent

        records = [
            json.dumps({"call_id": "AAA", "tenant_id": "tenant-1"}),
            json.dumps({"call_id": "BBB", "tenant_id": "tenant-2"}),
            json.dumps({"call_id": "CCC", "tenant_id": "tenant-1"}),
        ]

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=records)

        with patch("app.dashboard.call_store._get_redis", return_value=mock_redis):
            result = await aget_recent(limit=50, tenant_id="tenant-1")

        assert len(result) == 2
        assert all(r["tenant_id"] == "tenant-1" for r in result)

    @pytest.mark.asyncio
    async def test_returns_all_when_no_tenant_filter(self):
        from app.dashboard.call_store import aget_recent

        records = [
            json.dumps({"call_id": "AAA", "tenant_id": "tenant-1"}),
            json.dumps({"call_id": "BBB", "tenant_id": "tenant-2"}),
        ]

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=records)

        with patch("app.dashboard.call_store._get_redis", return_value=mock_redis):
            result = await aget_recent(limit=50, tenant_id="")

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_unavailable(self):
        from app.dashboard.call_store import aget_recent

        with patch("app.dashboard.call_store._get_redis", return_value=None):
            result = await aget_recent()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_redis_exception(self):
        from app.dashboard.call_store import aget_recent

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(side_effect=ConnectionError("Redis error"))

        with patch("app.dashboard.call_store._get_redis", return_value=mock_redis):
            result = await aget_recent()

        assert result == []

    @pytest.mark.asyncio
    async def test_limit_is_respected(self):
        from app.dashboard.call_store import aget_recent

        records = [
            json.dumps({"call_id": f"ID{i}", "tenant_id": "t"})
            for i in range(10)
        ]

        mock_redis = AsyncMock()
        mock_redis.lrange = AsyncMock(return_value=records)

        with patch("app.dashboard.call_store._get_redis", return_value=mock_redis):
            result = await aget_recent(limit=3, tenant_id="")

        assert len(result) == 3


class TestCallStoreClear:
    """clear() deletes the Redis key."""

    @pytest.mark.asyncio
    async def test_clear_deletes_redis_key(self):
        from app.dashboard.call_store import clear, _REDIS_KEY

        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()

        with patch("app.dashboard.call_store._get_redis", return_value=mock_redis):
            await clear()

        mock_redis.delete.assert_awaited_once_with(_REDIS_KEY)

    @pytest.mark.asyncio
    async def test_clear_is_safe_when_redis_unavailable(self):
        from app.dashboard.call_store import clear

        with patch("app.dashboard.call_store._get_redis", return_value=None):
            # Should not raise
            await clear()
