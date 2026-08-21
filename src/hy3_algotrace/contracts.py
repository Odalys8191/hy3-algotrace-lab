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

type SchemaVersion = Literal["1.2"]
type ModelParameter = str | int | float | bool | None
SCHEMA_VERSION: SchemaVersion = "1.2"
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
    EDGE_CASES = "edge_cases"


class StepStatus(StrEnum):
    CORRECT = "correct"
    ACCEPTABLE_OMISSION = "acceptable_omission"
    UNSUPPORTED = "unsupported"
    INCORRECT = "incorrect"


class ErrorTaxonomy(StrEnum):
    PROBLEM_MISREAD = "problem_misread"
    CONSTRAINT_OMISSION = "constraint_omission"
    ALGORITHM_LOGIC = "algorithm_logic"
    PROOF_GAP_CIRCULARITY = "proof_gap_circularity"
    COMPLEXITY_ERROR = "complexity_error"
    BOUNDARY_ERROR = "boundary_error"
    IMPLEMENTATION_ERROR = "implementation_error"
    HALLUCINATION = "hallucination"
    FORMAT_SCHEMA = "format_schema"


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
    source: Literal["codeforces"] = "codeforces"
    cf_contest_id: int = Field(gt=0)
    cf_index: str = Field(min_length=1)
    cf_tags: tuple[str, ...] = Field(min_length=1)
    source_split: Literal["validation", "test"]
    is_description_translated: Literal[False] = False
    input_file: Literal[""] = ""
    output_file: Literal[""] = ""
    topic: Topic
    rating: int
    language: Literal["cpp17"] = "cpp17"
    time_limit_ms: int = Field(gt=0)
    memory_limit_mb: int = Field(gt=0)
    public_tests: tuple[TestCase, ...] = ()
    hidden_tests: tuple[TestCase, ...] = ()
    generated_tests: tuple[TestCase, ...] = ()
    content_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)

    @field_validator("rating")
    @classmethod
    def validate_rating_band(cls, rating: int) -> int:
        rating_bands = ((1200, 1500), (1600, 1900), (2000, 2400))
        if not any(lower <= rating <= upper for lower, upper in rating_bands):
            raise ValueError("rating must fall in a formal rating band")
        return rating

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if not _is_sha256(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

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
    accepted_algorithm_families: tuple[str, ...] = Field(min_length=1)
    key_invariants: tuple[str, ...] = Field(min_length=1)
    complexity_ceiling: str = Field(min_length=1)
    known_traps: tuple[str, ...] = Field(min_length=1)
    adversarial_cases: tuple[str, ...] = Field(min_length=1)
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
    step_number: int = Field(gt=0)
    stage: ReasoningStage
    claim: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    depends_on: tuple[str, ...] = ()
    status: StepStatus = StepStatus.CORRECT


class SolutionTrace(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    trace_id: str = Field(min_length=1)
    problem_id: str = Field(min_length=1)
    language: Literal["cpp17"] = "cpp17"
    steps: tuple[ReasoningStep, ...] = Field(min_length=1)
    problem_understanding: str = Field(min_length=1)
    algorithm: str = Field(min_length=1)
    correctness_argument: str = Field(min_length=1)
    time_complexity: str = Field(min_length=1)
    space_complexity: str = Field(min_length=1)
    edge_cases: tuple[str, ...] = Field(min_length=1)
    code: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step_graph(self) -> Self:
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique")
        step_numbers = [step.step_number for step in self.steps]
        if len(step_numbers) != len(set(step_numbers)):
            raise ValueError("step numbers must be unique")
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


class StepReview(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    step_id: str = Field(min_length=1)
    status: StepStatus
    material: bool
    taxonomy: ErrorTaxonomy | None = None
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_error_semantics(self) -> Self:
        erroneous_statuses = {StepStatus.UNSUPPORTED, StepStatus.INCORRECT}
        if self.material and self.status in erroneous_statuses and self.taxonomy is None:
            raise ValueError("material unsupported or incorrect reviews require a taxonomy")
        if self.status in {StepStatus.CORRECT, StepStatus.ACCEPTABLE_OMISSION} and self.taxonomy:
            raise ValueError("correct or acceptable reviews cannot claim an error taxonomy")
        return self


class ReviewerVerdict(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    reviewer_id: str = Field(min_length=1)
    trace_id: str = Field(min_length=1)
    material_error: bool
    error_taxonomy: ErrorTaxonomy | None = None
    first_error_step_id: str | None = Field(default=None, min_length=1)
    explanation: str = Field(min_length=1)
    per_step_reviews: tuple[StepReview, ...] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_material_error_semantics(self) -> Self:
        has_evidence = self.error_taxonomy is not None and self.first_error_step_id is not None
        material_erroneous_steps = {
            review.step_id
            for review in self.per_step_reviews
            if review.material and review.status in {StepStatus.UNSUPPORTED, StepStatus.INCORRECT}
        }
        if self.material_error and not has_evidence:
            raise ValueError("a material error requires taxonomy and first error step evidence")
        if self.material_error and self.first_error_step_id not in material_erroneous_steps:
            raise ValueError("first error step must reference a material erroneous step review")
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
    reviewer_verdicts: tuple[ReviewerVerdict, ...] = Field(min_length=1)
    final_correct: bool
    process_score: float = Field(ge=0.0, le=100.0)
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
        if self.final_correct != (self.judge_evidence.verdict is JudgeStatus.AC):
            raise ValueError("final_correct must match JudgeEvidence verdict == AC")
        return self


class RunManifest(ContractModel):
    schema_version: SchemaVersion = SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    config_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    problem_ids: tuple[str, ...] = Field(min_length=1)
    artifact_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    artifact_hashes: Mapping[str, str] = Field(min_length=1)
    model_name: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    model_parameters: Mapping[str, ModelParameter]
    input_hash: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    code_revision: str = Field(min_length=1)
    container_image_digest: str = Field(min_length=SHA256_HEX_LENGTH + 7)

    @field_validator("config_hash", "artifact_hash", "input_hash")
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

    @field_validator("model_parameters")
    @classmethod
    def validate_model_parameters(
        cls, model_parameters: Mapping[str, ModelParameter]
    ) -> Mapping[str, ModelParameter]:
        if any(not parameter_name for parameter_name in model_parameters):
            raise ValueError("model parameter names must be non-empty")
        return MappingProxyType(dict(sorted(model_parameters.items())))

    @field_serializer("artifact_hashes", "model_parameters")
    def serialize_mappings(
        self, value: Mapping[str, str] | Mapping[str, ModelParameter]
    ) -> dict[str, ModelParameter]:
        return dict(value)

    @field_validator("problem_ids")
    @classmethod
    def validate_problem_ids(cls, problem_ids: tuple[str, ...]) -> tuple[str, ...]:
        if len(problem_ids) != len(set(problem_ids)):
            raise ValueError("problem IDs must be unique in a run manifest")
        return problem_ids

    @field_validator("container_image_digest")
    @classmethod
    def validate_container_image_digest(cls, value: str) -> str:
        if not value.startswith("sha256:") or not _is_sha256(value.removeprefix("sha256:")):
            raise ValueError("container_image_digest must be a sha256 digest")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


def _is_sha256(value: str) -> bool:
    return len(value) == SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


V1_2_REQUIRED_FIELDS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "problem_record": frozenset(
            {
                "cf_contest_id",
                "cf_index",
                "cf_tags",
                "source_split",
                "generated_tests",
                "content_hash",
            }
        ),
        "problem_oracle": frozenset(
            {
                "accepted_algorithm_families",
                "key_invariants",
                "complexity_ceiling",
                "known_traps",
                "adversarial_cases",
            }
        ),
        "solution_trace": frozenset(
            {"problem_understanding", "correctness_argument", "edge_cases"}
        ),
        "reviewer_verdict": frozenset({"per_step_reviews"}),
        "audit_report": frozenset({"final_correct", "process_score"}),
        "run_manifest": frozenset(
            {
                "updated_at",
                "model_name",
                "prompt_version",
                "model_parameters",
                "input_hash",
                "code_revision",
                "container_image_digest",
            }
        ),
    }
)


def migrate_v1_1_to_v1_2(
    payload: Mapping[str, Any], *, artifact_type: str
) -> dict[str, Any]:
    """Upgrade an already-complete 1.1 mapping without inventing audit semantics."""

    if payload.get("schema_version") != "1.1":
        raise ValueError("migration accepts only schema version 1.1 payloads")
    try:
        required_fields = V1_2_REQUIRED_FIELDS[artifact_type]
    except KeyError as error:
        raise ValueError(f"unsupported artifact type for migration: {artifact_type}") from error
    missing_fields = {field for field in required_fields if field not in payload}
    if artifact_type == "solution_trace":
        steps = payload.get("steps")
        if not isinstance(steps, (list, tuple)) or any(
            not isinstance(step, Mapping) or "step_number" not in step for step in steps
        ):
            missing_fields.add("steps[].step_number")
    if missing_fields:
        fields = ", ".join(sorted(missing_fields))
        raise ValueError(
            f"cannot safely migrate {artifact_type}: "
            f"required 1.2 fields lack inferable values: {fields}"
        )
    migrated = dict(payload)
    migrated["schema_version"] = SCHEMA_VERSION
    return migrated
