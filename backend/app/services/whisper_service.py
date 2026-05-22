"""Async Whisper STT service — runs local inference in a thread executor.

Uses openai-whisper (small model by default) which is entirely free and
runs on CPU.  Audio bytes are written to a NamedTemporaryFile so Whisper
can seek/read the file; the temp file is deleted immediately after.

Concurrency is bounded by a semaphore to prevent thread pool starvation
when multiple transcription requests arrive simultaneously.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from prometheus_client import Histogram, Gauge
import time

log = logging.getLogger("redline_ai.services.whisper")

WHISPER_LATENCY = Histogram(
    "whisper_transcription_seconds",
    "Whisper STT transcription latency",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

WHISPER_ACTIVE = Gauge(
    "whisper_active_transcriptions",
    "Number of Whisper transcriptions currently in progress",
)

# Max concurrent transcriptions — prevents thread pool starvation
_MAX_CONCURRENT = 4


class WhisperService:
    """Wrapper around openai-whisper that exposes an async transcribe()."""

    def __init__(self, model_size: str = "small") -> None:
        self._model_size = model_size
        self._model = None
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        self._executor = ThreadPoolExecutor(
            max_workers=_MAX_CONCURRENT,
            thread_name_prefix="whisper",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Load the Whisper model (blocking -- call from thread or lifespan)."""
        import whisper  # type: ignore[import]

        try:
            from filelock import FileLock
        except ImportError:
            log.warning("filelock not installed; loading Whisper without lock")
            log.info("Loading Whisper model '%s' ...", self._model_size)
            self._model = whisper.load_model(self._model_size)
            log.info("Whisper model '%s' loaded.", self._model_size)
            return

        log.info("Loading Whisper model '%s' ...", self._model_size)
        lock_path = os.path.join(tempfile.gettempdir(), ".whisper_download.lock")
        lock = FileLock(lock_path, timeout=300)
        with lock:
            self._model = whisper.load_model(self._model_size)
        log.info("Whisper model '%s' loaded.", self._model_size)

    def is_ready(self) -> bool:
        return self._model is not None

    def shutdown(self) -> None:
        self._model = None
        self._executor.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Core
    # ------------------------------------------------------------------

    async def transcribe(self, audio_bytes: bytes) -> str:
        """Return transcribed text for raw audio bytes.

        Bounded by semaphore to prevent thread starvation.
        """
        if not self.is_ready():
            raise RuntimeError("WhisperService not initialised")

        async with self._semaphore:
            WHISPER_ACTIVE.inc()
            start = time.perf_counter()
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    functools.partial(self._sync_transcribe, audio_bytes),
                )
                return result
            finally:
                WHISPER_LATENCY.observe(time.perf_counter() - start)
                WHISPER_ACTIVE.dec()

    # ------------------------------------------------------------------
    # Internals (sync – run in executor)
    # ------------------------------------------------------------------

    def _sync_transcribe(self, audio_bytes: bytes) -> str:
        suffix = ".wav"
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False
            ) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            result = self._model.transcribe(tmp_path, fp16=False)  # type: ignore[union-attr]
            text: str = (result.get("text") or "").strip()
            return text
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
