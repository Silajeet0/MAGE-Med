"""Typed environment configuration for the backend."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime settings loaded from `MAGE_MED_` variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MAGE_MED_",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "ci", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    database_url: str = "sqlite:///./var/mage_med.db"
    fhir_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    clinical_text_import_root: Path | None = None
    clinical_text_max_upload_bytes: int = Field(
        default=2 * 1024 * 1024, ge=1024, le=20 * 1024 * 1024
    )
    clinical_text_max_note_bytes: int = Field(default=256 * 1024, ge=256, le=5 * 1024 * 1024)
    clinical_text_max_notes: int = Field(default=1000, ge=1, le=10_000)
    clinical_text_chunk_characters: int = Field(default=1000, ge=100, le=10_000)
    clinical_text_chunk_overlap: int = Field(default=100, ge=0, le=1000)
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: str = "mage-med-local"
    neo4j_database: str = "neo4j"
    neo4j_timeout_seconds: float = Field(default=3.0, gt=0.0, le=30.0)


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide immutable settings instance."""

    return Settings()
