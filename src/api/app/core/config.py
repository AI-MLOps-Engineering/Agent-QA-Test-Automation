# src/api/app/core/config.py
"""
Configuration module for Agent QA & Test Automation.

Provides a pydantic-based Settings object that centralizes all configuration
values (env vars, defaults). Designed to be imported by application modules
and tests. Loads environment variables from .env when present.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from pydantic import BaseSettings, AnyHttpUrl, Field, validator


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Agent QA & Test Automation"
    ENV: str = Field("development", description="Environment: development|staging|production")
    DEBUG: bool = False

    # Network / CORS
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ALLOW_ORIGINS: List[str] = Field(
        default_factory=lambda: ["http://localhost:7860", "http://127.0.0.1:7860"],
        description="List of allowed CORS origins for the frontend",
    )

    # Uploads / storage
    UPLOAD_ROOT: Path = Field(default=Path("/tmp/agent_qa_repos"), description="Root path for uploaded repos")
    ARTIFACTS_ROOT: Path = Field(default=Path("/tmp/agent_qa_artifacts"), description="Path to store run artifacts")

    # Vector store
    VECTORSTORE_URL: Optional[AnyHttpUrl] = Field(
        default=None, description="URL for vector store (ChromaDB HTTP server) e.g. http://vectorstore:8001"
    )
    VECTORSTORE_API_KEY: Optional[str] = Field(default=None, description="Optional API key for vector store")

    # Model server
    MODEL_SERVER_URL: Optional[AnyHttpUrl] = Field(
        default=None, description="URL for model server (Ollama / TGI) e.g. http://model-server:5100"
    )
    MODEL_DEFAULT_NAME: str = Field(default="code-model", description="Default model name to call on model server")

    # Sandbox / runner
    SANDBOX_IMAGE: str = Field(default="agent-qa-sandbox:latest", description="Docker image used for sandbox runs")
    SANDBOX_TIMEOUT: int = Field(default=120, description="Default timeout (seconds) for test runs in sandbox")
    SANDBOX_CPU_LIMIT: str = Field(default="0.5", description="CPU limit for sandbox container (docker-compose format)")
    SANDBOX_MEM_LIMIT: str = Field(default="512m", description="Memory limit for sandbox container")

    # Security
    SECRET_KEY: Optional[str] = Field(default=None, description="Secret key for signing tokens (if used)")
    ALLOW_SANDBOX_NETWORK: bool = Field(default=False, description="Allow outbound network from sandbox (dangerous)")

    # Persistence / DB (optional)
    STORAGE_BACKEND: str = Field(default="filesystem", description="storage backend: filesystem|s3|gcs")
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT: Optional[str] = None

    # Logging / telemetry
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")
    ENABLE_PROMETHEUS: bool = Field(default=False, description="Expose Prometheus metrics endpoint")

    # GitHub / CI integration (optional)
    GITHUB_TOKEN: Optional[str] = None
    GITHUB_REPO: Optional[str] = None

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    # Validators to coerce types and ensure directories exist
    @validator("UPLOAD_ROOT", pre=True)
    def _ensure_upload_root(cls, v):
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @validator("ARTIFACTS_ROOT", pre=True)
    def _ensure_artifacts_root(cls, v):
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @validator("CORS_ALLOW_ORIGINS", pre=True)
    def _normalize_cors(cls, v):
        if isinstance(v, str):
            # allow comma-separated env var
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @validator("VECTORSTORE_URL", "MODEL_SERVER_URL", pre=True)
    def empty_to_none(cls, v):
        if v == "":
            return None
        return v


# Singleton settings instance for import convenience
def get_settings() -> Settings:
    """
    Return a cached Settings instance. Import this function where settings are needed.
    """
    # Pydantic BaseSettings caches values internally; creating multiple instances is cheap,
    # but returning a single instance avoids repeated env parsing in tests and runtime.
    global _SETTINGS_INSTANCE  # type: ignore
    try:
        return _SETTINGS_INSTANCE  # type: ignore
    except NameError:
        _SETTINGS_INSTANCE = Settings()
        return _SETTINGS_INSTANCE  # type: ignore


settings = get_settings()
