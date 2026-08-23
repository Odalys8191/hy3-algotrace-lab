"""Versioned FastAPI routes for the personal Hy3 AlgoTrace Lab activity project."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

from .api_models import (
    ProblemDetailResponse,
    ProblemListResponse,
    RunAcceptedResponse,
    RunCreateRequest,
    RunReadResponse,
)
from .catalog import ProblemCatalog
from .run_service import ProblemNotFoundError, RunNotFoundError, RunService


def create_app(*, catalog: ProblemCatalog, run_service: RunService) -> FastAPI:
    """Build an app exclusively from injected catalog and orchestration interfaces."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        run_service.reconcile_abandoned_runs()
        yield

    app = FastAPI(
        title="Hy3 AlgoTrace Lab",
        description=(
            "Personal activity project for local algorithm-solution auditing; "
            "not an official Tencent release."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.get("/api/v1/problems", response_model=ProblemListResponse)
    def list_problems() -> ProblemListResponse:
        return ProblemListResponse(problems=run_service.list_public_problems())

    @app.get("/api/v1/problems/{problem_id}", response_model=ProblemDetailResponse)
    def get_problem(problem_id: str) -> ProblemDetailResponse:
        try:
            return ProblemDetailResponse.model_validate(run_service.get_public_problem(problem_id))
        except ProblemNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="problem not found",
            ) from error

    @app.post(
        "/api/v1/runs",
        response_model=RunAcceptedResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_run(request: RunCreateRequest) -> RunAcceptedResponse:
        try:
            return run_service.submit(request)
        except ProblemNotFoundError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="problem not found",
            ) from error

    @app.get("/api/v1/runs/{run_id}", response_model=RunReadResponse)
    def get_run(run_id: str) -> RunReadResponse:
        try:
            return run_service.get_run(run_id)
        except (RunNotFoundError, ValueError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="run not found",
            ) from error

    return app
