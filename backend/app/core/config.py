from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Redline AI"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = "development"

    # ---- Security -------------------------------------------------------
    # No insecure default – app logs a warning at startup if the default
    # placeholder is still present (see app/main.py lifespan).
    SECRET_KEY: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120  # 2 hours
    TWILIO_AUTH_TOKEN: str = ""

    # DB - Set USE_SQLITE=false in .env to use PostgreSQL in production
    USE_SQLITE: bool = True
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_DB: str = "redline_db"
    # Cloud SQL unix socket (set CLOUD_SQL_CONNECTION_NAME for Cloud Run)
    CLOUD_SQL_CONNECTION_NAME: str = ""

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.USE_SQLITE:
            if self.APP_ENV.lower() == "production":
                raise RuntimeError(
                    "SQLite is not supported in production. "
                    "Set USE_SQLITE=false and configure PostgreSQL."
                )
            return "sqlite+aiosqlite:///./redline.db"
        # Cloud SQL socket path (Cloud Run mounts proxy at /cloudsql/)
        if self.CLOUD_SQL_CONNECTION_NAME:
            socket_path = f"/cloudsql/{self.CLOUD_SQL_CONNECTION_NAME}"
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@/{self.POSTGRES_DB}?host={socket_path}"
            )
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # External services
    ML_SERVICE_URL: str = "http://localhost:8001"
    TRANSLATION_SERVICE_URL: str = "https://libretranslate.de/translate"
    GEOCODER_BASE_URL: str = "https://nominatim.openstreetmap.org/search"
    GROQ_API_KEY: str | None = None

    INTENT_MODEL_NAME: str = "distilbert-base-uncased"
    INTENT_ONNX_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "intent_model.onnx"
    )
    EMOTION_ONNX_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "emotion_model.onnx"
    )
    EMOTION_PT_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "emotion_model.pt"
    )

    # ---- INT8-quantized model paths (edge deployment) --------------------
    # Fall back to the regular (FP32) paths when the INT8 variants are absent.
    INTENT_ONNX_INT8_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "intent_model_int8.onnx"
    )
    EMOTION_ONNX_INT8_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "emotion_model_int8.onnx"
    )

    @property
    def intent_onnx_effective_path(self) -> str:
        """Return INT8 path if the file exists, otherwise fall back to FP32."""
        int8 = Path(self.INTENT_ONNX_INT8_PATH)
        return str(int8) if int8.exists() else self.INTENT_ONNX_PATH

    @property
    def emotion_onnx_effective_path(self) -> str:
        """Return INT8 path if the file exists, otherwise fall back to FP32."""
        int8 = Path(self.EMOTION_ONNX_INT8_PATH)
        return str(int8) if int8.exists() else self.EMOTION_ONNX_PATH

    # ---- GCS model download (Cloud Run) ------------------------------------
    GCS_MODEL_BUCKET: str = ""

    # ---- Whisper STT (local, no paid API) ---------------------------------
    # Model size: tiny | base | small | medium | large
    # "small" balances accuracy + speed on CPU.  Override via WHISPER_MODEL_SIZE env.
    WHISPER_MODEL_SIZE: str = "small"

    # ---- Upload limits ------------------------------------------------
    MAX_AUDIO_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ALLOWED_AUDIO_TYPES: list[str] = [
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp4",
        "audio/webm",
        "audio/ogg",
        "audio/flac",
    ]
    MAX_TRANSCRIPT_LENGTH: int = 10_000  # characters

    # ---- CORS -----------------------------------------------------------
    # Comma-separated list of allowed origins, e.g.:
    #   ALLOWED_ORIGINS=https://app.redline.ai,https://admin.redline.ai
    # Set to "*" only in local development (handled by the lifespan check).
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"
    ALLOWED_ORIGIN: str = ""  # Cloud Run compat (singular)

    @property
    def allowed_origins_list(self) -> list[str]:
        raw = self.ALLOWED_ORIGINS
        # Cloud Run sets ALLOWED_ORIGIN (singular) — merge both
        if self.ALLOWED_ORIGIN and self.ALLOWED_ORIGIN not in raw:
            raw = f"{raw},{self.ALLOWED_ORIGIN}" if raw else self.ALLOWED_ORIGIN
        return [s.strip() for s in raw.split(",") if s.strip()]

    # ---- Docs -----------------------------------------------------------
    # Disable Swagger / ReDoc in production
    ENABLE_DOCS: bool = True

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
