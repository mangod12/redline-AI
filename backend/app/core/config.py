from __future__ import annotations

import os
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Redline AI"
    API_V1_STR: str = "/api/v1"
    APP_ENV: str = os.getenv("APP_ENV", "development")

    # ---- Security -------------------------------------------------------
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # 30 minutes
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    TWILIO_AUTH_TOKEN: str = os.getenv("TWILIO_AUTH_TOKEN", "")

    # DB - Set USE_SQLITE=false in .env to use PostgreSQL in production
    USE_SQLITE: bool = os.getenv("USE_SQLITE", "true").lower() == "true"
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "localhost")
    POSTGRES_PORT: str = os.getenv("POSTGRES_PORT", "5432")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "redline_db")
    # Cloud SQL unix socket path (e.g. /cloudsql/project:region:instance)
    CLOUD_SQL_CONNECTION_NAME: str = os.getenv("CLOUD_SQL_CONNECTION_NAME", "")

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        if self.USE_SQLITE:
            return "sqlite+aiosqlite:///./redline.db"
        if self.CLOUD_SQL_CONNECTION_NAME:
            # Cloud Run connects via unix socket through Cloud SQL Auth Proxy
            socket_path = f"/cloudsql/{self.CLOUD_SQL_CONNECTION_NAME}"
            return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@/{self.POSTGRES_DB}?host={socket_path}"
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # External services
    ML_SERVICE_URL: str = os.getenv("ML_SERVICE_URL", "http://localhost:8001")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GROQ_API_KEY: str | None = os.getenv("GROQ_API_KEY")

    INTENT_MODEL_NAME: str = "distilbert-base-uncased"
    INTENT_ONNX_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "intent_model.onnx"
    )

    # ---- Emotion CNN (ONNX / PyTorch checkpoint) ----------------------------
    EMOTION_ONNX_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "emotion_model.onnx"
    )
    EMOTION_PT_PATH: str = str(
        Path(__file__).resolve().parents[2] / "ml" / "emotion_model.pt"
    )

    # ---- Whisper STT (local, no paid API) ---------------------------------
    WHISPER_MODEL_SIZE: str = "small"

    # ---- CORS -----------------------------------------------------------
    ALLOWED_ORIGINS: list[str] = [
        origin for origin in [
            "http://localhost:3000",
            "http://localhost:5173",
            os.getenv("ALLOWED_ORIGIN", ""),
        ] if origin
    ]

    # ---- MCP (Model Context Protocol) ------------------------------------
    ENABLE_MCP: bool = os.getenv("ENABLE_MCP", "true").lower() == "true"

    # ---- Docs -----------------------------------------------------------
    ENABLE_DOCS: bool = os.getenv("ENABLE_DOCS", "true").lower() == "true"

    # ---- Production guards ----------------------------------------------
    @model_validator(mode="after")
    def validate_production_settings(self) -> Settings:
        if self.APP_ENV.lower() == "production":
            if self.USE_SQLITE:
                raise ValueError("USE_SQLITE must be false in production")
            if self.POSTGRES_PASSWORD in ("postgres", "password", ""):
                raise ValueError("POSTGRES_PASSWORD must be changed from default in production")
            if not self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if not self.TWILIO_AUTH_TOKEN:
                raise ValueError("TWILIO_AUTH_TOKEN must be set in production")
            # Docs can be enabled in production via ENABLE_DOCS env var
        return self

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()
