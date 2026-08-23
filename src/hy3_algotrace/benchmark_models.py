"""Strict, frozen Task-6 benchmark, metric, and report models."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    ErrorTaxonomy,
    JudgeStatus,
    RatingBand,
    ReasoningStage,
    RunStatus,
    SolutionTrace,
    StepStatus,
    Topic,
)

type BenchmarkSchemaVersion = Literal["1.2"]
BENCHMARK_SCHEMA_VERSION: BenchmarkSchemaVersion = "1.2"


class BenchmarkModel(BaseModel):
    """Closed immutable boundary for Task-6 artifacts."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_assignment=True)


class SampleKind(StrEnum):
    NATURAL = "natural"
    GOLD = "gold"
    CONTROLLED_WRONG = "controlled_wrong"
    PARADOX = "paradox"


class MetricObservation(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    sample_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    sample_kind: SampleKind
    topic: Topic
    rating_band: RatingBand
    gold_final_correct: bool | None = None
    gold_process_valid: bool | None = None
    gold_first_error_step: int | None = Field(default=None, gt=0, strict=True)
    gold_taxonomy: ErrorTaxonomy | None = None
    predicted_final_correct: bool = Field(strict=True)
    predicted_process_valid: bool = Field(strict=True)
    predicted_first_error_step: int | None = Field(default=None, gt=0, strict=True)
    predicted_taxonomy: ErrorTaxonomy | None = None
    needs_human_review: bool = Field(strict=True)
    primary_review_agreement: bool | None = None
    arbitration_used: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_gold_process_label(self) -> Self:
        if self.gold_process_valid is False and (
            self.gold_first_error_step is None or self.gold_taxonomy is None
        ):
            raise ValueError(
                "gold invalid process requires first-error and taxonomy labels"
            )
        if self.gold_process_valid is True and (
            self.gold_first_error_step is not None or self.gold_taxonomy is not None
        ):
            raise ValueError("gold valid process cannot carry error labels")
        return self


class MetricResult(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    name: str = Field(min_length=1, strict=True)
    numerator: float = Field(ge=0.0)
    denominator: int = Field(ge=0, strict=True)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    not_evaluable: bool = Field(strict=True)
    included_sample_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_evaluability(self) -> Self:
        if self.denominator == 0:
            if self.value is not None or not self.not_evaluable:
                raise ValueError("zero-denominator metric must be not_evaluable")
        elif self.value is None or self.not_evaluable:
            raise ValueError("nonzero-denominator metric must have a value")
        if (
            self.name != "taxonomy_macro_f1"
            and len(self.included_sample_ids) != self.denominator
        ):
            raise ValueError("metric denominator must equal included sample count")
        return self


class MetricBreakdown(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    key: str = Field(min_length=1, strict=True)
    metrics: tuple[MetricResult, ...]


class MetricsReport(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    overall: tuple[MetricResult, ...]
    by_topic: tuple[MetricBreakdown, ...]
    by_rating_band: tuple[MetricBreakdown, ...]


class ConfidenceInterval(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    metric_name: str = Field(min_length=1, strict=True)
    confidence: float = Field(default=0.95, ge=0.95, le=0.95, strict=True)
    lower: float | None = None
    upper: float | None = None
    available: bool = Field(strict=True)
    seed: int = Field(strict=True)
    requested_replicates: int = Field(gt=0, strict=True)
    valid_replicates: int = Field(ge=0, strict=True)
    included_sample_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_availability(self) -> Self:
        if self.available:
            if self.lower is None or self.upper is None or self.valid_replicates == 0:
                raise ValueError("available interval requires bounds and replicates")
        elif self.lower is not None or self.upper is not None or self.valid_replicates != 0:
            raise ValueError("unavailable interval cannot publish bounds")
        return self


class BreakpointResult(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    stable: bool = Field(strict=True)
    not_evaluable: bool = Field(strict=True)
    lower_band: RatingBand | None = None
    upper_band: RatingBand | None = None
    decline: float | None = None
    drop_ci_lower: float | None = None
    drop_ci_upper: float | None = None
    seed: int = Field(strict=True)
    replicates: int = Field(gt=0, strict=True)

    @model_validator(mode="after")
    def validate_breakpoint(self) -> Self:
        fields = (
            self.lower_band,
            self.upper_band,
            self.decline,
            self.drop_ci_lower,
            self.drop_ci_upper,
        )
        if self.stable and (self.not_evaluable or any(item is None for item in fields)):
            raise ValueError("stable breakpoint requires complete evaluable evidence")
        if not self.stable and any(item is not None for item in fields):
            raise ValueError("absent breakpoint cannot publish a selected transition")
        return self


class ChartPoint(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    metric: str = Field(min_length=1, strict=True)
    stratum: str = Field(min_length=1, strict=True)
    value: float | None = None
    numerator: float = Field(ge=0.0)
    denominator: int = Field(ge=0, strict=True)


class ChartSpec(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    chart_version: Literal["task6-chart-v1"] = "task6-chart-v1"
    chart_id: str = Field(min_length=1, strict=True)
    title: str = Field(min_length=1, strict=True)
    mark: Literal["bar", "line"]
    x_field: Literal["metric", "stratum"]
    y_field: Literal["value"] = "value"
    points: tuple[ChartPoint, ...]


type BenchmarkParameterValue = str | int | float | bool | None


class BenchmarkParameter(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    name: str = Field(min_length=1, strict=True)
    value: BenchmarkParameterValue


class BenchmarkSampleSpec(BenchmarkModel):
    """Frozen expected identity and strata for one benchmark observation."""

    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    sample_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    problem_id: str = Field(min_length=1, strict=True)
    sample_kind: SampleKind
    topic: Topic
    rating_band: RatingBand


class VerifiedDataEvidence(BenchmarkModel):
    """Hash-bound link that still requires verification by a trusted caller."""

    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    evidence_kind: Literal["verified-task7-replay"]
    artifact_path: str = Field(min_length=1, strict=True)
    artifact_hash: str = Field(min_length=64, max_length=64, strict=True)
    selection_hash: str = Field(min_length=64, max_length=64, strict=True)
    corpus_hash: str = Field(min_length=64, max_length=64, strict=True)

    @model_validator(mode="after")
    def validate_hashes_and_relative_link(self) -> Self:
        for digest in (self.artifact_hash, self.selection_hash, self.corpus_hash):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("verified evidence hashes must be lowercase SHA-256")
        path = PurePosixPath(self.artifact_path)
        if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
            raise ValueError("verified evidence path must be a safe relative link")
        return self


class BenchmarkConfig(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    benchmark_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    selection_hash: str = Field(min_length=64, max_length=64, strict=True)
    corpus_hash: str = Field(min_length=64, max_length=64, strict=True)
    ordered_sample_ids: tuple[str, ...] = Field(min_length=1)
    sample_specs: tuple[BenchmarkSampleSpec, ...] = Field(min_length=1)
    generation_sample_ids: tuple[str, ...]
    audit_sample_ids: tuple[str, ...]
    model: str = Field(min_length=1, strict=True)
    endpoint_identity: str = Field(min_length=1, strict=True)
    generator_prompt_version: str = Field(min_length=1, strict=True)
    logic_review_prompt_version: str = Field(min_length=1, strict=True)
    adversarial_review_prompt_version: str = Field(min_length=1, strict=True)
    arbiter_prompt_version: str = Field(min_length=1, strict=True)
    model_parameters: tuple[BenchmarkParameter, ...]
    code_revision: str = Field(min_length=1, strict=True)
    judge_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    metric_version: Literal["task6-metrics-v1"]
    chart_version: Literal["task6-chart-v1"]
    seed: int = Field(strict=True)
    bootstrap_replicates: int = Field(default=10_000, gt=0, strict=True)
    remote_attempt_budget: int = Field(gt=0, le=500, strict=True)
    formal: bool = Field(strict=True)
    verified_data_evidence: VerifiedDataEvidence | None = None

    @property
    def static_attempt_lower_bound(self) -> int:
        return len(self.generation_sample_ids) + 2 * len(self.audit_sample_ids)

    @model_validator(mode="after")
    def validate_frozen_identity_and_budget(self) -> Self:
        if not re.fullmatch(r"[0-9a-f]{64}", self.selection_hash) or not re.fullmatch(
            r"[0-9a-f]{64}", self.corpus_hash
        ):
            raise ValueError("selection and corpus hashes must be lowercase SHA-256")
        if len(set(self.ordered_sample_ids)) != len(self.ordered_sample_ids):
            raise ValueError("ordered sample IDs must be unique")
        if tuple(item.sample_id for item in self.sample_specs) != self.ordered_sample_ids:
            raise ValueError("sample specs must match ordered sample IDs exactly")
        known = set(self.ordered_sample_ids)
        if not set(self.generation_sample_ids) <= known or not set(
            self.audit_sample_ids
        ) <= known:
            raise ValueError("generation and audit IDs must belong to ordered samples")
        if self.remote_attempt_budget < self.static_attempt_lower_bound:
            raise ValueError("remote budget is below the static remote-attempt lower bound")
        if len({item.name for item in self.model_parameters}) != len(
            self.model_parameters
        ):
            raise ValueError("model parameter names must be unique")
        parsed = urlsplit(self.endpoint_identity)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint identity must be credential-free and absolute")
        evidence = self.verified_data_evidence
        if evidence is not None and (
            evidence.selection_hash != self.selection_hash
            or evidence.corpus_hash != self.corpus_hash
        ):
            raise ValueError("verified evidence must bind the frozen selection and corpus")
        if self.formal:
            self._validate_formal_profile()
        return self

    def _validate_formal_profile(self) -> None:
        expected_counts = {
            SampleKind.GOLD: 30,
            SampleKind.CONTROLLED_WRONG: 60,
            SampleKind.PARADOX: 15,
            SampleKind.NATURAL: 60,
        }
        actual_counts = {
            kind: sum(spec.sample_kind is kind for spec in self.sample_specs)
            for kind in SampleKind
        }
        natural_ids = tuple(
            spec.sample_id
            for spec in self.sample_specs
            if spec.sample_kind is SampleKind.NATURAL
        )
        if (
            actual_counts != expected_counts
            or self.generation_sample_ids != natural_ids
            or self.audit_sample_ids != self.ordered_sample_ids
        ):
            raise ValueError(
                "formal profile requires 30 gold, 60 controlled_wrong, 15 paradox, "
                "60 natural, natural-only generation, and all 165 audit samples"
            )
        problem_strata: dict[str, tuple[Topic, RatingBand]] = {}
        for spec in self.sample_specs:
            stratum = (spec.topic, spec.rating_band)
            existing = problem_strata.setdefault(spec.problem_id, stratum)
            if existing != stratum:
                raise ValueError("one formal problem cannot cross frozen strata")
        if len(problem_strata) != 30:
            raise ValueError("formal profile requires exactly 30 problem identities")
        for topic in Topic:
            for band in RatingBand:
                count = sum(
                    stratum == (topic, band) for stratum in problem_strata.values()
                )
                if count != 2:
                    raise ValueError(
                        "formal profile requires two problems in every 5x3 topic/rating cell"
                    )
        if self.verified_data_evidence is None:
            raise ValueError("formal profile requires hash-bound verified-data evidence")


class BenchmarkStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class BenchmarkExecutionKind(StrEnum):
    LIVE = "live"
    ARTIFACT_REPLAY = "artifact_replay"


class ObservationReplayInput(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    observations: tuple[MetricObservation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_observations(self) -> Self:
        sample_ids = tuple(row.sample_id for row in self.observations)
        if len(set(sample_ids)) != len(sample_ids):
            raise ValueError("replay observation sample IDs must be unique")
        return self


class LedgerEvent(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    benchmark_id: str = Field(min_length=1, strict=True)
    sequence: int = Field(gt=0, strict=True)
    sample_id: str = Field(min_length=1, strict=True)
    operation: str = Field(min_length=1, strict=True)
    phase: str = Field(min_length=1, strict=True)
    retry_number: int = Field(gt=0, strict=True)


class LedgerIndex(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    benchmark_id: str = Field(min_length=1, strict=True)
    event_paths: tuple[str, ...]
    event_hashes: tuple[str, ...]

    @model_validator(mode="after")
    def validate_parallel_entries(self) -> Self:
        if len(self.event_paths) != len(self.event_hashes):
            raise ValueError("ledger paths and hashes must be parallel")
        return self


class ArtifactHashEntry(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    name: str = Field(min_length=1, strict=True)
    path: str = Field(min_length=1, strict=True)
    content_hash: str = Field(min_length=64, max_length=64, strict=True)


class BenchmarkRunReport(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    benchmark_id: str = Field(min_length=1, strict=True)
    execution_kind: BenchmarkExecutionKind
    status: BenchmarkStatus
    complete: bool = Field(strict=True)
    formal_eligible: bool = Field(strict=True)
    formal_evidence_verified: bool = Field(strict=True)
    completed_sample_ids: tuple[str, ...]
    remote_attempts_used: int = Field(ge=0, strict=True)
    artifacts: tuple[ArtifactHashEntry, ...]

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        if self.complete is not (self.status is BenchmarkStatus.COMPLETE):
            raise ValueError("complete flag must match benchmark status")
        if self.formal_eligible and (
            not self.complete or not self.formal_evidence_verified
        ):
            raise ValueError(
                "formal eligibility requires a complete run and verified external evidence"
            )
        if self.formal_evidence_verified and not self.complete:
            raise ValueError("partial benchmark cannot verify formal evidence")
        return self


class BlindPublicExample(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    input_data: str = Field(strict=True)
    output_data: str = Field(strict=True)


class HumanReviewCandidate(BenchmarkModel):
    """Private input used to construct separately blinded artifacts."""

    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    sample_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    trace_id: str = Field(min_length=1, strict=True)
    statement: str = Field(min_length=1, strict=True)
    public_examples: tuple[BlindPublicExample, ...]
    trace: SolutionTrace

    @model_validator(mode="after")
    def validate_trace_identity(self) -> Self:
        if self.trace.problem_id != self.problem_id:
            raise ValueError("candidate trace problem identity must match")
        if self.trace.trace_id != self.trace_id:
            raise ValueError("candidate trace identity must match")
        return self


class BlindReasoningStep(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    step_number: int = Field(gt=0, strict=True)
    claim: str = Field(min_length=1, strict=True)
    rationale: str = Field(min_length=1, strict=True)


class BlindReviewItem(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    blind_id: str = Field(min_length=1, strict=True)
    statement: str = Field(min_length=1, strict=True)
    public_examples: tuple[BlindPublicExample, ...]
    steps: tuple[BlindReasoningStep, ...] = Field(min_length=1)
    problem_understanding: str = Field(min_length=1, strict=True)
    algorithm: str = Field(min_length=1, strict=True)
    correctness_argument: str = Field(min_length=1, strict=True)
    time_complexity: str = Field(min_length=1, strict=True)
    space_complexity: str = Field(min_length=1, strict=True)
    edge_cases: tuple[str, ...] = Field(min_length=1)
    code: str = Field(min_length=1, strict=True)


class HumanReviewExport(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    batch_id: str = Field(min_length=1, strict=True)
    items: tuple[BlindReviewItem, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_blind_ids(self) -> Self:
        if len({item.blind_id for item in self.items}) != len(self.items):
            raise ValueError("blind IDs must be unique")
        return self


class HumanReviewMappingEntry(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    blind_id: str = Field(min_length=1, strict=True)
    sample_id: str = Field(min_length=1, strict=True)
    problem_id: str = Field(min_length=1, strict=True)
    trace_id: str = Field(min_length=1, strict=True)


class HumanReviewMapping(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    batch_id: str = Field(min_length=1, strict=True)
    entries: tuple[HumanReviewMappingEntry, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_mapping(self) -> Self:
        if len({entry.blind_id for entry in self.entries}) != len(self.entries):
            raise ValueError("mapping blind IDs must be unique")
        if len({entry.sample_id for entry in self.entries}) != len(self.entries):
            raise ValueError("mapping sample IDs must be unique")
        return self


class HumanDecision(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    blind_id: str = Field(min_length=1, strict=True)
    process_valid: bool = Field(strict=True)
    first_error_step: int | None = Field(default=None, gt=0, strict=True)
    taxonomy: ErrorTaxonomy | None = None

    @model_validator(mode="after")
    def validate_process_decision(self) -> Self:
        if self.process_valid and (
            self.first_error_step is not None or self.taxonomy is not None
        ):
            raise ValueError("valid process cannot carry an error decision")
        if not self.process_valid and (
            self.first_error_step is None or self.taxonomy is None
        ):
            raise ValueError("invalid process requires localization and taxonomy")
        return self


class HumanDecisionSet(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    batch_id: str = Field(min_length=1, strict=True)
    decision_set_id: str = Field(min_length=1, strict=True)
    decisions: tuple[HumanDecision, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_decisions(self) -> Self:
        if len({item.blind_id for item in self.decisions}) != len(self.decisions):
            raise ValueError("a blind item may be decided only once")
        return self


class HumanReviewReplay(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    replay_id: str = Field(min_length=1, strict=True)
    batch_id: str = Field(min_length=1, strict=True)
    source_decision_set_id: str = Field(min_length=1, strict=True)
    observations: tuple[MetricObservation, ...]


class UiTimelineStep(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    step_id: str = Field(min_length=1, strict=True)
    step_number: int = Field(gt=0, strict=True)
    stage: ReasoningStage
    claim: str = Field(strict=True)
    rationale: str = Field(strict=True)
    status: StepStatus


class UiJudgeTest(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    test_number: int = Field(gt=0, strict=True)
    status: JudgeStatus
    time_ms: int | None = Field(default=None, ge=0, strict=True)
    memory_kb: int | None = Field(default=None, ge=0, strict=True)


class UiRunView(BenchmarkModel):
    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    run_id: str = Field(min_length=1, strict=True)
    status: RunStatus
    timeline: tuple[UiTimelineStep, ...]
    code: str | None = None
    judge_verdict: JudgeStatus | None = None
    judge_tests: tuple[UiJudgeTest, ...]
    first_error_step_id: str | None = None
    taxonomy: ErrorTaxonomy | None = None
    process_score: float | None = Field(default=None, ge=0.0, le=100.0)
    needs_human_review: bool | None = None
    failure_message: str | None = None
