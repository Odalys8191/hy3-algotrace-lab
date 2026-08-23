"""Environment-backed, credential-free application configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_root: Path
    catalog_root: Path
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    background_workers: int = Field(default=2, ge=1, le=32)

    @classmethod
    def from_env(cls) -> AppConfig:
        return cls(
            artifact_root=Path(os.environ.get("HY3_ARTIFACT_ROOT", "artifacts/runs")),
            catalog_root=Path(os.environ.get("HY3_CATALOG_ROOT", "data/problems")),
            host=os.environ.get("HY3_HOST", "127.0.0.1"),
            port=int(os.environ.get("HY3_PORT", "8000")),
            background_workers=int(os.environ.get("HY3_BACKGROUND_WORKERS", "2")),
        )
