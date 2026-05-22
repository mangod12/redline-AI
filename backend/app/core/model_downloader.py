"""Download ONNX models from GCS if not present locally.

Used in Cloud Run where the container image doesn't include model files.
Models are cached in /tmp/models/ to survive within a single instance lifecycle.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger("redline_ai.model_downloader")


def download_models_from_gcs(bucket_name: str, local_dir: str = "/tmp/models") -> dict[str, str]:
    """Download intent and emotion ONNX models from GCS.

    Returns dict of model_name -> local_path for successfully downloaded models.
    Skips download if file already exists locally (cached from previous request).
    """
    if not bucket_name:
        log.info("GCS_MODEL_BUCKET not set — skipping model download")
        return {}

    os.makedirs(local_dir, exist_ok=True)

    models = {
        "intent_model.onnx": "models/intent_model.onnx",
        "emotion_model.onnx": "models/emotion_model.onnx",
    }

    downloaded = {}

    for filename, gcs_path in models.items():
        local_path = os.path.join(local_dir, filename)

        if os.path.exists(local_path):
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            log.info("Model already cached: %s (%.1f MB)", local_path, size_mb)
            downloaded[filename] = local_path
            continue

        try:
            from google.cloud import storage

            client = storage.Client()
            bucket = client.bucket(bucket_name)
            blob = bucket.blob(gcs_path)

            if not blob.exists():
                log.warning("Model not found in GCS: gs://%s/%s", bucket_name, gcs_path)
                continue

            log.info("Downloading gs://%s/%s -> %s", bucket_name, gcs_path, local_path)
            blob.download_to_filename(local_path)
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            log.info("Downloaded %s (%.1f MB)", filename, size_mb)
            downloaded[filename] = local_path

        except ImportError:
            log.warning("google-cloud-storage not installed — skipping GCS download")
            return downloaded
        except Exception as exc:
            log.warning("Failed to download %s from GCS: %s", filename, exc)

    return downloaded
