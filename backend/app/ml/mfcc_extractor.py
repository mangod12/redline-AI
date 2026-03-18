"""Extract MFCC features from raw audio bytes for emotion inference.

Converts raw audio (WAV, MP3, etc.) to the exact MFCC tensor shape
expected by the emotion CNN: (1, 1, 40, 94) float32.

Parameters match the training pipeline in ml/train_emotion_cnn_multidataset.py:
  - sample_rate: 16000
  - n_mfcc: 40
  - n_fft: 1024
  - hop_length: 512
  - n_mels: 64
  - duration: 3 seconds (48000 samples)
  - max_time_steps: 94
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

log = logging.getLogger("redline_ai.ml.mfcc_extractor")

# Training-time constants (must match ml/train_emotion_cnn_multidataset.py)
_SAMPLE_RATE = 16000
_DURATION_S = 3
_MAX_LENGTH = _SAMPLE_RATE * _DURATION_S  # 48000 samples
_N_MFCC = 40
_N_FFT = 1024
_HOP_LENGTH = 512
_N_MELS = 64
_MAX_TIME_STEPS = 94

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mfcc-extract")


def _extract_mfcc_sync(audio_bytes: bytes) -> np.ndarray:
    """Synchronous MFCC extraction from raw audio bytes.

    Returns ndarray of shape (1, 1, 40, 94) matching the ONNX model input.
    """
    import soundfile as sf
    import torch
    import torchaudio.transforms as T

    # Read audio from bytes
    audio_buf = io.BytesIO(audio_bytes)
    try:
        waveform_np, sr = sf.read(audio_buf)
    except Exception:
        # If soundfile can't read directly, write to temp file
        # (handles formats like MP3 that need seeking)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            waveform_np, sr = sf.read(tmp_path)
        finally:
            if tmp_path and Path(tmp_path).exists():
                Path(tmp_path).unlink()

    audio = torch.tensor(waveform_np, dtype=torch.float32)

    # Convert to mono if stereo
    if audio.ndim > 1:
        audio = audio.mean(dim=1)

    # Add channel dimension: (samples,) -> (1, samples)
    audio = audio.unsqueeze(0)

    # Resample to 16kHz if needed
    if sr != _SAMPLE_RATE:
        resampler = T.Resample(orig_freq=sr, new_freq=_SAMPLE_RATE)
        audio = resampler(audio)

    # Pad or truncate to exactly 3 seconds
    if audio.shape[1] > _MAX_LENGTH:
        audio = audio[:, :_MAX_LENGTH]
    elif audio.shape[1] < _MAX_LENGTH:
        pad = _MAX_LENGTH - audio.shape[1]
        audio = torch.nn.functional.pad(audio, (0, pad))

    # Extract MFCCs
    mfcc_transform = T.MFCC(
        sample_rate=_SAMPLE_RATE,
        n_mfcc=_N_MFCC,
        melkwargs={
            "n_fft": _N_FFT,
            "hop_length": _HOP_LENGTH,
            "n_mels": _N_MELS,
        },
    )
    mfcc = mfcc_transform(audio)  # shape: (1, 40, time_steps)

    # Pad or truncate time dimension to 94 steps
    if mfcc.shape[2] > _MAX_TIME_STEPS:
        mfcc = mfcc[:, :, :_MAX_TIME_STEPS]
    elif mfcc.shape[2] < _MAX_TIME_STEPS:
        pad_steps = _MAX_TIME_STEPS - mfcc.shape[2]
        mfcc = torch.nn.functional.pad(mfcc, (0, pad_steps))

    # Add batch dimension: (1, 40, 94) -> (1, 1, 40, 94)
    mfcc = mfcc.unsqueeze(0)

    return mfcc.numpy().astype(np.float32)


async def extract_mfcc(audio_bytes: bytes) -> np.ndarray:
    """Async MFCC extraction — offloads to thread pool.

    Args:
        audio_bytes: Raw audio file bytes (WAV, MP3, etc.)

    Returns:
        ndarray of shape (1, 1, 40, 94), dtype float32
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _extract_mfcc_sync, audio_bytes)


def zero_mfcc() -> np.ndarray:
    """Return a zeroed MFCC placeholder for text-only inference."""
    return np.zeros((1, 1, _N_MFCC, _MAX_TIME_STEPS), dtype=np.float32)
