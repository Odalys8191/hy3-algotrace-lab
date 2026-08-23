"""Zero-argument local FastAPI composition for the Docker release wiring."""

from __future__ import annotations

import os

from fastapi import FastAPI

from .app import create_app as create_api_app
from .artifacts import ArtifactStore
from .catalog import ProblemCatalog
from .config import AppConfig
from .docker_judge import DockerJudge
from .evaluator import ReviewOrchestrator
from .executor import InProcessBackgroundExecutor
from .hy3_client import Hy3Client, Hy3Config, JsonResponseCache
from .run_service import RunService


def create_app() -> FastAPI:
    """Compose the existing API only from local environment-backed dependencies.

    The function intentionally has no arguments so ``uvicorn --factory`` is a real
    deployment entry point. Missing Hy3 credentials, catalog data, judge image, or
    Docker socket fail before a run can become a misleading formal result.
    """

    app_config = AppConfig.from_env()
    hy3_config = Hy3Config.from_env()
    catalog = ProblemCatalog.from_directory(app_config.catalog_root)
    artifacts = ArtifactStore(app_config.artifact_root)
    client = Hy3Client(
        hy3_config,
        cache=JsonResponseCache(app_config.artifact_root / "hy3-response-cache"),
    )
    run_service = RunService(
        catalog=catalog,
        artifacts=artifacts,
        generator=client,
        judge=DockerJudge(),
        reviews=ReviewOrchestrator(client),
        executor=InProcessBackgroundExecutor(max_workers=app_config.background_workers),
        model_name=hy3_config.model,
        code_revision=os.environ.get("HY3_CODE_REVISION", "unknown"),
        container_image_digest=os.environ.get("HY3_JUDGE_IMAGE", ""),
    )
    return create_api_app(catalog=catalog, run_service=run_service)
