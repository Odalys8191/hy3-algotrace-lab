"""Injected Judge validation and deterministic differential-testing interfaces."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, model_validator

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import JudgeStatus, ProblemRecord
from hy3_algotrace.corpus import (
    CorpusManifest,
    CorpusSampleKind,
    ProjectBundleManifest,
    validate_corpus_bundle_links,
)
from hy3_algotrace.dataset_models import (
    DATASET_SCHEMA_VERSION,
    DatasetModel,
    FrozenSelectionManifest,
)
from hy3_algotrace.judge import Judge


class DifferentialDataError(ValueError):
    """Raised when judging or differential evidence cannot support formal data."""


class JudgeCaseKind(StrEnum):
    GOLD = "gold"
    MUTANT = "mutant"
    PARADOX = "paradox"


class DifferentialExecutionStatus(StrEnum):
    COMPLETED = "completed"
    RUNTIME_ERROR = "runtime_error"
    TLE = "tle"
    MLE = "mle"
    OUTPUT_LIMIT = "output_limit"
    INFRASTRUCTURE_ERROR = "infrastructure_error"


class DifferentialStatus(StrEnum):
    PASSED = "passed"
    MISMATCH = "mismatch"


class JudgeSourceCase(DatasetModel):
    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,255}$")
    kind: JudgeCaseKind
    problem: ProblemRecord
    cpp_source: str = Field(min_length=1, max_length=1_000_000)


class JudgeCaseResult(DatasetModel):
    case_id: str = Field(min_length=1)
    problem_id: str = Field(min_length=1)
    kind: JudgeCaseKind
    compile_status: JudgeStatus
    verdict: JudgeStatus
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class JudgeValidationReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["authored_source_judge_validation"] = "authored_source_judge_validation"
    results: tuple[JudgeCaseResult, ...] = Field(min_length=1)
    counts: dict[str, int]

    @model_validator(mode="after")
    def validate_counts(self) -> JudgeValidationReport:
        expected = Counter(result.kind.value for result in self.results)
        if self.counts != {kind.value: expected[kind.value] for kind in JudgeCaseKind}:
            raise ValueError("judge validation counts must match results")
        return self


class FormalCorpusJudgeValidationReport(DatasetModel):
    """Evidence that every controlled frozen corpus source passed its policy."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["formal_corpus_judge_validation"] = "formal_corpus_judge_validation"
    corpus_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    validation: JudgeValidationReport
    formal_eligibility: Literal[True] = True
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_formal_evidence(self) -> FormalCorpusJudgeValidationReport:
        if self.validation.counts != {"gold": 30, "mutant": 60, "paradox": 15}:
            raise ValueError("formal judge evidence must be exactly 30/60/15")
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        if self.content_hash != sha256_json(payload):
            raise ValueError("formal judge validation content_hash does not match")
        return self


class DifferentialCase(DatasetModel):
    test_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,255}$")
    input_data: str = Field(max_length=1_000_000)
    expected_output: str = Field(max_length=1_000_000)


class DifferentialExecution(DatasetModel):
    status: DifferentialExecutionStatus
    stdout: str = Field(max_length=1_000_000)
    diagnostics: str = Field(default="", max_length=2_000)


@runtime_checkable
class DifferentialRunner(Protocol):
    """Bounded external executor supplied by the caller."""

    def run(
        self,
        cpp_source: str,
        input_data: str,
        *,
        time_limit_ms: int,
        memory_limit_mb: int,
    ) -> DifferentialExecution:
        """Execute one authored source without exposing raw outputs to the report."""


class DifferentialCaseResult(DatasetModel):
    test_id: str = Field(min_length=1)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    matched: bool


class DifferentialReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["authored_reference_differential_report"] = (
        "authored_reference_differential_report"
    )
    problem_id: str = Field(min_length=1)
    reference_cpp_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: DifferentialStatus
    results: tuple[DifferentialCaseResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status(self) -> DifferentialReport:
        expected = (
            DifferentialStatus.PASSED
            if all(result.matched for result in self.results)
            else DifferentialStatus.MISMATCH
        )
        if self.status is not expected:
            raise ValueError("differential status must match case results")
        return self


def validate_judge_cases(
    cases: Iterable[JudgeSourceCase],
    *,
    judge: Judge,
) -> JudgeValidationReport:
    """Require gold/paradox AC and a compiled semantic failure for every mutant."""

    materialized = tuple(cases)
    if not materialized:
        raise DifferentialDataError("at least one authored judge case is required")
    ids = [case.case_id for case in materialized]
    if len(ids) != len(set(ids)):
        raise DifferentialDataError("authored judge case IDs must be unique")
    results: list[JudgeCaseResult] = []
    semantic_failures = {
        JudgeStatus.WA,
        JudgeStatus.RUNTIME_ERROR,
        JudgeStatus.TLE,
        JudgeStatus.MLE,
        JudgeStatus.OUTPUT_LIMIT,
    }
    for case in materialized:
        try:
            evidence = judge.judge(case.problem, case.cpp_source)
        except Exception as error:
            raise DifferentialDataError(
                f"judge infrastructure raised for {case.case_id}"
            ) from error
        if evidence.verdict in {JudgeStatus.NOT_RUN, JudgeStatus.INFRASTRUCTURE_ERROR} or (
            evidence.compile_status
            in {
                JudgeStatus.NOT_RUN,
                JudgeStatus.INFRASTRUCTURE_ERROR,
            }
        ):
            raise DifferentialDataError(
                f"judge infrastructure evidence is unavailable for {case.case_id}"
            )
        if evidence.compile_status is not JudgeStatus.AC:
            raise DifferentialDataError(
                f"compile failure is not valid authored source evidence: {case.case_id}"
            )
        if case.kind in {JudgeCaseKind.GOLD, JudgeCaseKind.PARADOX}:
            if evidence.verdict is not JudgeStatus.AC:
                raise DifferentialDataError(
                    f"{case.kind.value} source must receive AC: {case.case_id}"
                )
        elif evidence.verdict not in semantic_failures:
            raise DifferentialDataError(f"mutant source must fail after compiling: {case.case_id}")
        results.append(
            JudgeCaseResult(
                case_id=case.case_id,
                problem_id=case.problem.problem_id,
                kind=case.kind,
                compile_status=evidence.compile_status,
                verdict=evidence.verdict,
                evidence_hash=sha256_json(evidence.model_dump(mode="json")),
            )
        )
    counts = Counter(result.kind.value for result in results)
    return JudgeValidationReport(
        results=tuple(results),
        counts={kind.value: counts[kind.value] for kind in JudgeCaseKind},
    )


def validate_formal_corpus_judge_cases(
    *,
    corpus: CorpusManifest,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
    cases: Iterable[JudgeSourceCase],
    judge: Judge,
) -> FormalCorpusJudgeValidationReport:
    """Judge the exact 30 gold, 60 mutant, and 15 paradox frozen sources."""

    if corpus.selection_manifest_hash != selection.content_hash:
        raise DifferentialDataError("corpus does not match frozen selection")
    try:
        validate_corpus_bundle_links(corpus, bundle_manifest)
    except ValueError as error:
        raise DifferentialDataError("corpus does not match authored bundles") from error
    controlled = tuple(
        sample for sample in corpus.samples if sample.kind is not CorpusSampleKind.NATURAL
    )
    expected_by_id = {sample.sample_id: sample for sample in controlled}
    materialized = tuple(cases)
    case_ids = [case.case_id for case in materialized]
    if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(expected_by_id):
        raise DifferentialDataError(
            "judge case IDs must exactly match all controlled corpus samples"
        )
    selected_by_id = {entry.problem_id: entry for entry in selection.entries}
    expected_kinds = {
        CorpusSampleKind.GOLD: JudgeCaseKind.GOLD,
        CorpusSampleKind.CONTROLLED_WRONG: JudgeCaseKind.MUTANT,
        CorpusSampleKind.PARADOX: JudgeCaseKind.PARADOX,
    }
    for case in materialized:
        sample = expected_by_id[case.case_id]
        if case.problem.problem_id != sample.problem_id:
            raise DifferentialDataError(
                f"judge problem does not match corpus sample: {case.case_id}"
            )
        selected = selected_by_id.get(case.problem.problem_id)
        if selected is None or selected.record_hash != sha256_json(
            case.problem.model_dump(mode="json")
        ):
            raise DifferentialDataError(
                f"judge problem does not match frozen record: {case.case_id}"
            )
        if case.kind is not expected_kinds[sample.kind]:
            raise DifferentialDataError(f"judge kind does not match corpus sample: {case.case_id}")
        source_hash = hashlib.sha256(case.cpp_source.encode("utf-8")).hexdigest()
        if source_hash != sample.cpp_source.sha256:
            raise DifferentialDataError(
                f"judge source does not match corpus artifact: {case.case_id}"
            )
    validation = validate_judge_cases(materialized, judge=judge)
    if validation.counts != {"gold": 30, "mutant": 60, "paradox": 15}:
        raise DifferentialDataError("formal judge evidence must be exactly 30/60/15")
    payload = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "formal_corpus_judge_validation",
        "corpus_manifest_hash": corpus.content_hash,
        "selection_manifest_hash": selection.content_hash,
        "validation": validation.model_dump(mode="json"),
        "formal_eligibility": True,
    }
    return FormalCorpusJudgeValidationReport(
        corpus_manifest_hash=corpus.content_hash,
        selection_manifest_hash=selection.content_hash,
        validation=validation,
        content_hash=sha256_json(payload),
    )


def run_differential_tests(
    *,
    problem_id: str,
    reference_cpp: str,
    cases: Iterable[DifferentialCase],
    runner: DifferentialRunner,
    time_limit_ms: int,
    memory_limit_mb: int,
) -> DifferentialReport:
    """Run authored adversarial cases and persist hashes, never raw case material."""

    materialized = tuple(cases)
    if not reference_cpp.strip():
        raise DifferentialDataError("reference C++ cannot be empty")
    if not materialized:
        raise DifferentialDataError("at least one differential case is required")
    ids = [case.test_id for case in materialized]
    if len(ids) != len(set(ids)):
        raise DifferentialDataError("differential case IDs must be unique")
    if not 0 < time_limit_ms <= 10_000 or not 0 < memory_limit_mb <= 1_024:
        raise DifferentialDataError("differential resource limits are invalid")
    results: list[DifferentialCaseResult] = []
    for case in materialized:
        try:
            execution = runner.run(
                reference_cpp,
                case.input_data,
                time_limit_ms=time_limit_ms,
                memory_limit_mb=memory_limit_mb,
            )
        except Exception as error:
            raise DifferentialDataError(f"differential runner raised for {case.test_id}") from error
        if execution.status is not DifferentialExecutionStatus.COMPLETED:
            detail = execution.diagnostics or execution.status.value
            raise DifferentialDataError(f"differential runner failed for {case.test_id}: {detail}")
        matched = execution.stdout.split() == case.expected_output.split()
        results.append(
            DifferentialCaseResult(
                test_id=case.test_id,
                input_hash=sha256_json(case.input_data),
                expected_output_hash=sha256_json(case.expected_output),
                actual_output_hash=sha256_json(execution.stdout),
                matched=matched,
            )
        )
    status = (
        DifferentialStatus.PASSED
        if all(result.matched for result in results)
        else DifferentialStatus.MISMATCH
    )
    return DifferentialReport(
        problem_id=problem_id,
        reference_cpp_hash=sha256_json(reference_cpp),
        status=status,
        results=tuple(results),
    )
