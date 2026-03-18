"""Download ML models from Google Cloud Storage at startup.

On Cloud Run the ONNX models are stored in a GCS bucket instead of being
baked into the Docker image (which would bloat it by ~300 MB).  This module
downloads them on first boot if they are not already present locally.

Set the ``GCS_MODEL_BUCKET`` environment variable to enable GCS downloads.
When unset the application falls back to local model files (dev workflow).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("redline_ai.ml.gcs_model_store")

GCS_MODEL_BUCKET = os.getenv("GCS_MODEL_BUCKET", "")

# Map of local destination path -> GCS blob name
_DEFAULT_MODELS: dict[str, str] = {
    "ml/intent_model.onnx": "models/intent_model.onnx",
    "ml/emotion_model.onnx": "models/emotion_model.onnx",
}


def download_models_from_gcs(model_dir: str = "/app") -> None:
    """Download models from GCS if ``GCS_MODEL_BUCKET`` is set.

    Skips models that already exist locally.  Called synchronously during
    application startup (before the async event-loop is running).
    """
    if not GCS_MODEL_BUCKET:
        log.info("GCS_MODEL_BUCKET not set — using local model files")
        return

    try:
        from google.cloud import storage  # type: ignore[import-untyped]
    except ImportError:
        log.warning("google-cloud-storage not installed — skipping GCS download")
        return

    client = storage.Client()
    bucket = client.bucket(GCS_MODEL_BUCKET)

    for local_rel, blob_name in _DEFAULT_MODELS.items():
        local_path = Path(model_dir) / local_rel
        if local_path.exists():
            log.info("Model already exists locally: %s", local_path)
            continue

        log.info("Downloading %s from gs://%s/%s", local_path, GCS_MODEL_BUCKET, blob_name)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob = bucket.blob(blob_name)

        try:
            blob.download_to_filename(str(local_path))
            size_mb = local_path.stat().st_size / (1024 * 1024)
            log.info("Downloaded %s (%.1f MB)", local_path, size_mb)
        except Exception:
            log.exception("Failed to download %s from GCS", blob_name)
            # Remove partial file
            if local_path.exists():
                local_path.unlink()
