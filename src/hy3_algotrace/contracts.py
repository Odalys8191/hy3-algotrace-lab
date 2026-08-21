"""Stable, versioned data contracts shared by every application layer."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

type SchemaVersion = Literal["1.1"]
SCHEMA_VERSION: SchemaVersion = "1.1"
SHA256_HEX_LENGTH = 64


class ContractModel(BaseModel):
    """Base configuration for JSON artifacts crossing application boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def validate_schema_version(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and (
            value.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported schema version; expected {SCHEMA_VERSION}")
        return value


class Topic(StrEnum):
    CONSTRUCTION_SIMULATION = "construction_simulation"
    GREEDY = "greedy"
    BINARY_SEARCH = "binary_search"
    DYNAMIC_PROGRAMMING = "dynamic_programming"
    GRAPH = "graph"


class RatingBand(StrEnum):
    FOUNDATION = "1200-1500"
    INTERMEDIATE = "1600-1900"
    ADVANCED = "2000-2400"


class ReasoningStage(StrEnum):
    PROBLEM_UNDERSTANDING = "problem_understanding"
    ALGORITHM_DESIGN = "algorithm_design"
    CORRECTNESS_ARGUMENT = "correctness_argument"
    COMPLEXITY_ANALYSIS = "complexity_analysis"
    IMPLEMENTATION = "implementation"
    TESTING = "testing"


class StepStatus(StrEnum):
    PENDING = "pending"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    NOT_APPLICABLE = "not_applicable"


class ErrorTaxonomy(StrEnum):
    MISREAD_PROBLEM = "misread_problem"
    CONCEPT_ERROR = "concept_error"
    ALGORITHM_ERROR = "algorithm_error"
    PROOF_GAP = "proof_gap"
    COMPLEXITY_ERROR = "complexity_error"
    BOUNDARY_OMISSION = "boundary_omission"
    IMPLEMENTATION_ERROR = "implementation_error"
    FORMAT_SCHEMA = "format_schema"
    INFRASTRUCTURE = "infrastructure"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JudgeStatus(StrEnum):
    NOT_RUN = "not_run"
    AC = "ac"
    WA = "wa"
    COMPILE_ERROR = "compile_error"
    RUNTIME_ERROR = "runtime_error"
    TLE = "tle"
    MLE = "mle"
    OUTPUT_LIMIT = "output_limit"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class TestCase(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    test_id: str = Field(min_length=1)
    input_data: str
    expected_output: str


class ProblemRecord(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    problem_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    statement_en: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    topic: Topic
    rating: int
    language: Literal["cpp17"] = "cpp17"
    time_limit_ms: int = Field(gt=0)
    memory_limit_mb: int = Field(gt=0)
    public_tests: tuple[TestCase, ...] = ()
    hidden_tests: tuple[TestCase, ...] = ()

    @field_validator("rating")
    @classmethod
    def validate_rating_band(cls, rating: int) -> int:
        rating_bands = ((1200, 1500), (1600, 1900), (2000, 2400))
        if not any(lower <= rating <= upper for lower, upper in rating_bands):
            raise ValueError("rating must fall in a formal rating band")
        return rating

    @property
    def rating_band(self) -> RatingBand:
        if 1200 <= self.rating <= 1500:
            return RatingBand.FOUNDATION
        if 1600 <= self.rating <= 1900:
            return RatingBand.INTERMEDIATE
        return RatingBand.ADVANCED


class ProblemOracle(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    problem_id: str = Field(min_length=1)
    decisive_facts: tuple[str, ...] = Field(min_length=1)
    reference_solution_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)

    @field_validator("reference_solution_hash")
    @classmethod
    def validate_reference_hash(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("reference_solution_hash must be a lowercase SHA-256 hex digest")
        return value


class ReasoningStep(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    step_id: str = Field(min_length=1)
    stage: ReasoningStage
    claim: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    status: StepStatus = StepStatus.PENDING


class SolutionTrace(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    trace_id: str = Field(min_length=1)
    problem_id: str = Field(min_length=1)
    language: Literal["cpp17"] = "cpp17"
    steps: tuple[ReasoningStep, ...] = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    time_complexity: str = Field(min_length=1)
    space_complexity: str = Field(min_length=1)
    code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step_graph(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique")
        known_steps = set(step_ids)
        for step in self.steps:
            unknown_dependencies = set(step.depends_on) - known_steps
            if unknown_dependencies:
                raise ValueError("step dependencies cannot reference unknown step IDs")
        adjacency = {step.step_id: step.depends_on for step in self.steps}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise ValueError("step dependencies must be acyclic")
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in adjacency[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in adjacency:
            visit(step_id)
        return self


class PerTestEvidence(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    test_id: str = Field(min_length=1)
    status: JudgeStatus
    time_ms: int | None = Field(default=None, ge=0)
    memory_kb: int | None = Field(default=None, ge=0)
    diagnostics: str = ""
    counterexample_input: str | None = None


class JudgeEvidence(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    compile_status: JudgeStatus
    verdict: JudgeStatus
    tests: tuple[PerTestEvidence, ...] = ()
    diagnostics: str = ""
    first_counterexample_input: str | None = None


class ReviewerVerdict(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    reviewer_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    material_error: bool
    error_taxonomy: ErrorTaxonomy | None = None
    first_error_step_id: str | None = Field(default=None, min_length=1)
    explanation: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_material_error_semantics(self) -> Self:
        has_evidence = self.error_taxonomy is not None and self.first_error_step_id is not None
        if self.material_error and not has_evidence:
            raise ValueError("a material error requires taxonomy and first error step evidence")
        if not self.material_error and (
            self.error_taxonomy is not None or self.first_error_step_id is not None
        ):
            raise ValueError(
                "a non-material verdict cannot identify an error taxonomy or first step"
            )
        return self


class AuditReport(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    problem_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    judge_evidence: JudgeEvidence
    reviewer_verdicts: tuple[ReviewerVerdict, ...]
    process_valid: bool
    final_error_taxonomy: ErrorTaxonomy | None = None
    first_material_error_step_id: str | None = Field(default=None, min_length=1)
    needs_human_review: bool = False

    @model_validator(mode="after")
    def validate_process_error_semantics(self) -> Self:
        has_error_evidence = (
            self.final_error_taxonomy is not None
            and self.first_material_error_step_id is not None
        )
        if self.process_valid and (
            self.final_error_taxonomy is not None or self.first_material_error_step_id
        ):
            raise ValueError("process_valid reports cannot identify a material error")
        if not self.process_valid and not has_error_evidence:
            raise ValueError("process_valid=False requires taxonomy and first material error step")
        return self


class RunManifest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    status: RunStatus
    created_at: datetime
    config_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    problem_ids: tuple[str, ...] = Field(min_length=1)
    artifact_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    artifact_hashes: Mapping[str, str] = Field(min_length=1)

    @field_validator("config_hash", "artifact_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("hash values must be lowercase SHA-256 hex digests")
        return value

    @field_validator("artifact_hashes")
    @classmethod
    def validate_artifact_hashes(cls, artifact_hashes: Mapping[str, str]) -> Mapping[str, str]:
        if any(not artifact_id for artifact_id in artifact_hashes):
            raise ValueError("artifact hash IDs must be non-empty")
        if any(not _is_sha256(content_hash) for content_hash in artifact_hashes.values()):
            raise ValueError("artifact hash values must be lowercase SHA-256 hex digests")
        return MappingProxyType(dict(sorted(artifact_hashes.items())))

    @field_serializer("artifact_hashes")
    def serialize_artifact_hashes(self, artifact_hashes: Mapping[str, str]) -> dict[str, str]:
        return dict(artifact_hashes)

    @field_validator("problem_ids")
    @classmethod
    def validate_problem_ids(cls, problem_ids: tuple[str, ...]) -> tuple[str, ...]:
        if len(problem_ids) != len(set(problem_ids)):
            raise ValueError("problem IDs must be unique in a run manifest")
        return problem_ids

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


def _is_sha256(value: str) -> bool:
    return len(value) == SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )
