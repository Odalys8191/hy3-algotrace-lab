"""Strict, frozen Task-5 API and immutable run-transition models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    AuditReport,
    ErrorTaxonomy,
    JudgeStatus,
    ReasoningStage,
    RunManifest,
    RunStatus,
    SolutionTrace,
    StepStatus,
)

type ApiSchemaVersion = Literal["1.2"]
API_SCHEMA_VERSION: ApiSchemaVersion = "1.2"


class ApiModel(BaseModel):
    """Closed and immutable model for the versioned local API boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


class RunMode(StrEnum):
    SOLVE_AND_AUDIT = "solve_and_audit"
    AUDIT = "audit"


class RunTransitionEvent(StrEnum):
    REQUEST = "request"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunFailureCode(StrEnum):
    GENERATION_FAILED = "generation_failed"
    JUDGE_INFRASTRUCTURE = "judge_infrastructure"
    REVIEW_FAILED = "review_failed"
    ARTIFACT_FAILURE = "artifact_failure"
    ABANDONED_ON_RESTART = "abandoned_on_restart"
    EXECUTOR_FAILURE = "executor_failure"
    INTERNAL_FAILURE = "internal_failure"


class RunCreateRequest(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    mode: RunMode
    problem_id: str = Field(min_length=1, strict=True)
    trace: SolutionTrace | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self) -> Self:
        if self.mode is RunMode.AUDIT and self.trace is None:
            raise ValueError("audit mode requires a SolutionTrace")
        if self.mode is RunMode.SOLVE_AND_AUDIT and self.trace is not None:
            raise ValueError("solve_and_audit mode does not accept a supplied trace")
        if self.trace is not None and self.trace.problem_id != self.problem_id:
            raise ValueError("trace problem identity must match the requested problem")
        return self


class RunAcceptedResponse(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    status: Literal[RunStatus.QUEUED] = RunStatus.QUEUED


class RunFailure(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    code: RunFailureCode
    message: str = Field(min_length=1, strict=True)


class PublicReasoningStep(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    step_id: str = Field(min_length=1, strict=True)
    step_number: int = Field(gt=0, strict=True)
    stage: ReasoningStage
    claim: str = Field(strict=True)
    rationale: str = Field(strict=True)
    depends_on: tuple[str, ...]
    status: StepStatus


class PublicSolutionTrace(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    trace_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    language: Literal["cpp17"]
    steps: tuple[PublicReasoningStep, ...]
    problem_understanding: str = Field(strict=True)
    algorithm: str = Field(strict=True)
    correctness_argument: str = Field(strict=True)
    time_complexity: str = Field(strict=True)
    space_complexity: str = Field(strict=True)
    edge_cases: tuple[str, ...]
    code: str = Field(strict=True)


class PublicJudgeTestResult(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    test_number: int = Field(gt=0, strict=True)
    status: JudgeStatus
    time_ms: int | None = Field(default=None, ge=0, strict=True)
    memory_kb: int | None = Field(default=None, ge=0, strict=True)


class PublicJudgeReport(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    compile_status: JudgeStatus
    verdict: JudgeStatus
    tests: tuple[PublicJudgeTestResult, ...]


class PublicAuditReport(ApiModel):
    """Explicit allowlist of structured audit facts safe for the local UI."""

    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    trace_id: str = Field(min_length=1, strict=True)
    judge: PublicJudgeReport
    final_correct: bool = Field(strict=True)
    process_score: float = Field(ge=0.0, le=100.0, strict=True)
    process_valid: bool = Field(strict=True)
    final_error_taxonomy: ErrorTaxonomy | None = None
    first_material_error_step_id: str | None = Field(default=None, min_length=1)
    needs_human_review: bool = Field(strict=True)


class PublicRunReport(ApiModel):
    """A separately persisted, allowlisted report for API consumers."""

    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    mode: RunMode
    trace: PublicSolutionTrace
    audit: PublicAuditReport


class RunReadResponse(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    status: RunStatus
    report: PublicRunReport | None = None
    failure: RunFailure | None = None
    degraded_failure: RunFailure | None = None

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> Self:
        if self.status is RunStatus.COMPLETED and self.report is None:
            raise ValueError("completed run requires a public report")
        if self.status is RunStatus.FAILED and self.failure is None:
            raise ValueError("failed run requires a safe failure")
        if self.status is not RunStatus.COMPLETED and self.report is not None:
            raise ValueError("only completed runs expose a report")
        if self.status is not RunStatus.FAILED and self.failure is not None:
            raise ValueError("only failed runs expose a failure")
        if self.degraded_failure is not None and (
            self.status is not RunStatus.RUNNING
            or self.degraded_failure.code is not RunFailureCode.INTERNAL_FAILURE
        ):
            raise ValueError("only a running run may expose an internal degraded failure")
        return self


class InternalRunReport(ApiModel):
    """Complete local audit evidence; this model is never an API response."""

    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    mode: RunMode
    trace: SolutionTrace
    audit_report: AuditReport


class RunTransition(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    sequence: int = Field(ge=0, strict=True)
    event: RunTransitionEvent
    occurred_at: datetime
    previous_transition_hash: str | None = Field(default=None, min_length=64, max_length=64)
    request_artifact_hash: str = Field(min_length=64, max_length=64, strict=True)
    manifest: RunManifest
    public_report_path: str | None = None
    internal_report_path: str | None = None
    failure: RunFailure | None = None

    @model_validator(mode="after")
    def validate_event_payload(self) -> Self:
        if (self.sequence == 0) != (self.previous_transition_hash is None):
            raise ValueError("only the first transition omits previous_transition_hash")
        if self.sequence == 0 and self.event is not RunTransitionEvent.REQUEST:
            raise ValueError("the first transition must be request")
        if self.manifest.artifact_hash != self.request_artifact_hash:
            raise ValueError("manifest artifact_hash must identify the request artifact")
        if self.event is RunTransitionEvent.FAILED and self.failure is None:
            raise ValueError("failed transition requires a safe failure")
        if self.event is not RunTransitionEvent.FAILED and self.failure is not None:
            raise ValueError("only failed transitions may contain a failure")
        if self.event is RunTransitionEvent.COMPLETED and (
            self.public_report_path is None or self.internal_report_path is None
        ):
            raise ValueError("completed transition requires both report artifacts")
        return self


class StoredRunTransition(ApiModel):
    transition: RunTransition
    content_hash: str = Field(min_length=64, max_length=64, strict=True)


class ProblemSummaryResponse(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    problem_id: str = Field(min_length=1, strict=True)
    title: str = Field(min_length=1, strict=True)
    topic: str = Field(min_length=1, strict=True)
    rating: int = Field(gt=0, strict=True)


class ProblemListResponse(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    problems: tuple[ProblemSummaryResponse, ...]


class PublicTestInput(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    test_id: str = Field(min_length=1, strict=True)
    input_data: str = Field(strict=True)


class ProblemDetailResponse(ApiModel):
    schema_version: ApiSchemaVersion = API_SCHEMA_VERSION
    problem_id: str = Field(min_length=1, strict=True)
    title: str = Field(min_length=1, strict=True)
    statement_en: str = Field(min_length=1, strict=True)
    source_url: str = Field(min_length=1, strict=True)
    attribution: str = Field(min_length=1, strict=True)
    source: Literal["codeforces"]
    cf_contest_id: int = Field(gt=0, strict=True)
    cf_index: str = Field(min_length=1, strict=True)
    cf_tags: tuple[str, ...]
    source_split: Literal["validation", "test"]
    is_description_translated: Literal[False]
    input_file: Literal[""]
    output_file: Literal[""]
    topic: str = Field(min_length=1, strict=True)
    rating: int = Field(gt=0, strict=True)
    language: Literal["cpp17"]
    time_limit_ms: int = Field(gt=0, strict=True)
    memory_limit_mb: int = Field(gt=0, strict=True)
    public_tests: tuple[PublicTestInput, ...]
    content_hash: str = Field(min_length=64, max_length=64, strict=True)
