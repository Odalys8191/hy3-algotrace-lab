"""Injected Judge validation and deterministic differential-testing interfaces."""

from __future__ import annotations

import hashlib
import json
import weakref
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, Literal, Never, Protocol, SupportsIndex, runtime_checkable

from pydantic import Field, ValidationError, field_validator, model_validator

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import JudgeEvidence, JudgeStatus, ProblemRecord
from hy3_algotrace.corpus import (
    CorpusManifest,
    CorpusSampleKind,
    ProjectBundleManifest,
    validate_corpus_bundle_links,
)
from hy3_algotrace.dataset_models import (
    DATASET_SCHEMA_VERSION,
    DatasetModel,
    VerifiedSelectionChain,
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


class PersistedJudgeCaseEvidence(DatasetModel):
    """Replayable hashes for one controlled source and its raw JudgeEvidence."""

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,255}$")
    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    kind: JudgeCaseKind
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    problem_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("source_sha256", "problem_hash", "judge_evidence_hash")
    @classmethod
    def reject_zero_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("formal evidence hashes cannot be all-zero")
        return value


class FormalCorpusJudgeValidationReport(DatasetModel):
    """Persisted hashes only; parsing this artifact never grants eligibility."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["formal_corpus_judge_evidence"] = "formal_corpus_judge_evidence"
    corpus_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: tuple[PersistedJudgeCaseEvidence, ...] = Field(min_length=105, max_length=105)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator(
        "corpus_manifest_hash",
        "selection_manifest_hash",
        "bundle_manifest_hash",
        "content_hash",
    )
    @classmethod
    def reject_zero_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("formal chain hashes cannot be all-zero")
        return value

    @model_validator(mode="after")
    def validate_formal_evidence(self) -> FormalCorpusJudgeValidationReport:
        ids = [case.case_id for case in self.cases]
        if len(set(ids)) != 105:
            raise ValueError("formal judge evidence case IDs must be unique")
        counts = Counter(case.kind.value for case in self.cases)
        if counts != {"gold": 30, "mutant": 60, "paradox": 15}:
            raise ValueError("formal judge evidence must be exactly 30/60/15")
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        if self.content_hash != sha256_json(payload):
            raise ValueError("formal judge validation content_hash does not match")
        return self


_FORMAL_REPLAY_TOKEN = object()
_FORMAL_REPLAY_CAPABILITIES: weakref.WeakSet[Any] = weakref.WeakSet()


class FormalCorpusJudgeValidationResult:
    """Ephemeral result produced only after raw evidence and chain replay."""

    __slots__ = ("evidence_manifest", "formal_eligibility", "__weakref__")
    evidence_manifest: FormalCorpusJudgeValidationReport
    formal_eligibility: Literal[True]

    def __init__(
        self,
        *,
        evidence_manifest: FormalCorpusJudgeValidationReport,
        _replay_token: object,
    ) -> None:
        if _replay_token is not _FORMAL_REPLAY_TOKEN:
            raise ValueError("formal eligibility requires validated evidence replay")
        object.__setattr__(self, "evidence_manifest", evidence_manifest)
        object.__setattr__(self, "formal_eligibility", True)
        _FORMAL_REPLAY_CAPABILITIES.add(self)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("formal Judge replay capabilities are immutable")

    def __copy__(self) -> Never:
        raise TypeError("formal Judge replay capabilities cannot be copied")

    def __deepcopy__(self, _memo: dict[int, Any]) -> Never:
        raise TypeError("formal Judge replay capabilities cannot be copied")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise TypeError("formal Judge replay capabilities cannot be serialized")

    def _is_verified(self) -> bool:
        return self in _FORMAL_REPLAY_CAPABILITIES


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
    for case in materialized:
        try:
            evidence = judge.judge(case.problem, case.cpp_source)
        except Exception as error:
            raise DifferentialDataError(
                f"judge infrastructure raised for {case.case_id}"
            ) from error
        results.append(_validate_case_evidence(case, evidence))
    counts = Counter(result.kind.value for result in results)
    return JudgeValidationReport(
        results=tuple(results),
        counts={kind.value: counts[kind.value] for kind in JudgeCaseKind},
    )


def validate_formal_corpus_judge_cases(
    *,
    corpus: CorpusManifest,
    selection_chain: VerifiedSelectionChain,
    bundle_manifest: ProjectBundleManifest,
    cases: Iterable[JudgeSourceCase],
    judge: Judge,
) -> FormalCorpusJudgeValidationResult:
    """Judge the exact 30 gold, 60 mutant, and 15 paradox frozen sources."""

    materialized = _validate_formal_case_chain(
        corpus=corpus,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
    )
    raw_evidence: dict[str, JudgeEvidence] = {}
    for case in materialized:
        try:
            raw_evidence[case.case_id] = judge.judge(case.problem, case.cpp_source)
        except Exception as error:
            raise DifferentialDataError(
                f"judge infrastructure raised for {case.case_id}"
            ) from error
    validation = _validate_replayed_evidence(materialized, raw_evidence)
    if validation.counts != {"gold": 30, "mutant": 60, "paradox": 15}:
        raise DifferentialDataError("formal judge evidence must be exactly 30/60/15")
    persisted_cases = tuple(
        PersistedJudgeCaseEvidence(
            case_id=case.case_id,
            problem_id=case.problem.problem_id,
            kind=case.kind,
            source_sha256=hashlib.sha256(case.cpp_source.encode("utf-8")).hexdigest(),
            problem_hash=sha256_json(case.problem.model_dump(mode="json")),
            judge_evidence_hash=sha256_json(raw_evidence[case.case_id].model_dump(mode="json")),
        )
        for case in materialized
    )
    payload = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "formal_corpus_judge_evidence",
        "corpus_manifest_hash": corpus.content_hash,
        "selection_manifest_hash": selection_chain.selection.content_hash,
        "bundle_manifest_hash": bundle_manifest.content_hash,
        "cases": [case.model_dump(mode="json") for case in persisted_cases],
    }
    manifest = FormalCorpusJudgeValidationReport(
        corpus_manifest_hash=corpus.content_hash,
        selection_manifest_hash=selection_chain.selection.content_hash,
        bundle_manifest_hash=bundle_manifest.content_hash,
        cases=persisted_cases,
        content_hash=sha256_json(payload),
    )
    return FormalCorpusJudgeValidationResult(
        evidence_manifest=manifest,
        _replay_token=_FORMAL_REPLAY_TOKEN,
    )


def validate_persisted_formal_judge_evidence(
    payload: Mapping[str, Any],
    *,
    corpus: CorpusManifest,
    selection_chain: VerifiedSelectionChain,
    bundle_manifest: ProjectBundleManifest,
    cases: Iterable[JudgeSourceCase],
    raw_evidence: Mapping[str, JudgeEvidence],
) -> FormalCorpusJudgeValidationResult:
    """Replay raw JudgeEvidence and every content link before deriving eligibility."""

    try:
        manifest = FormalCorpusJudgeValidationReport.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise DifferentialDataError("formal judge evidence manifest is invalid") from error
    if (
        manifest.corpus_manifest_hash != corpus.content_hash
        or manifest.selection_manifest_hash != selection_chain.selection.content_hash
        or manifest.bundle_manifest_hash != bundle_manifest.content_hash
    ):
        raise DifferentialDataError("formal judge evidence chain hashes do not match")
    materialized = _validate_formal_case_chain(
        corpus=corpus,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
    )
    validation = _validate_replayed_evidence(materialized, raw_evidence)
    if validation.counts != {"gold": 30, "mutant": 60, "paradox": 15}:
        raise DifferentialDataError("formal judge evidence must be exactly 30/60/15")
    expected_persisted: list[PersistedJudgeCaseEvidence] = []
    for case in materialized:
        evidence = raw_evidence[case.case_id]
        expected = PersistedJudgeCaseEvidence(
            case_id=case.case_id,
            problem_id=case.problem.problem_id,
            kind=case.kind,
            source_sha256=hashlib.sha256(case.cpp_source.encode("utf-8")).hexdigest(),
            problem_hash=sha256_json(case.problem.model_dump(mode="json")),
            judge_evidence_hash=sha256_json(evidence.model_dump(mode="json")),
        )
        expected_persisted.append(expected)
    if tuple(case.case_id for case in manifest.cases) != tuple(
        case.case_id for case in expected_persisted
    ):
        raise DifferentialDataError("persisted judge evidence must match canonical corpus order")
    for observed, expected in zip(manifest.cases, expected_persisted, strict=True):
        if observed != expected:
            raise DifferentialDataError(
                f"persisted judge evidence hash mismatch: {expected.case_id}"
            )
    return FormalCorpusJudgeValidationResult(
        evidence_manifest=manifest,
        _replay_token=_FORMAL_REPLAY_TOKEN,
    )


def _validate_formal_case_chain(
    *,
    corpus: CorpusManifest,
    selection_chain: VerifiedSelectionChain,
    bundle_manifest: ProjectBundleManifest,
    cases: Iterable[JudgeSourceCase],
) -> tuple[JudgeSourceCase, ...]:
    if (
        not isinstance(selection_chain, VerifiedSelectionChain)
        or not selection_chain._is_verified()
    ):
        raise DifferentialDataError("formal judge validation requires verified selection chain")
    selection = selection_chain.selection
    if corpus.selection_manifest_hash != selection.content_hash:
        raise DifferentialDataError("corpus does not match frozen selection")
    if bundle_manifest.selection_manifest_hash != selection.content_hash:
        raise DifferentialDataError("bundle manifest does not match frozen selection")
    if corpus.natural_run_config.selection_manifest_hash != selection.content_hash:
        raise DifferentialDataError("natural run config does not match frozen selection")
    try:
        validate_corpus_bundle_links(corpus, bundle_manifest)
    except ValueError as error:
        raise DifferentialDataError("corpus does not match authored bundles") from error
    controlled = tuple(
        sample for sample in corpus.samples if sample.kind is not CorpusSampleKind.NATURAL
    )
    expected_by_id = {sample.sample_id: sample for sample in controlled}
    expected_case_ids = tuple(sample.sample_id for sample in controlled)
    materialized = tuple(cases)
    case_ids = tuple(case.case_id for case in materialized)
    if case_ids != expected_case_ids:
        raise DifferentialDataError(
            "judge case IDs must exactly match canonical controlled corpus order"
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
    return materialized


def _validate_replayed_evidence(
    cases: tuple[JudgeSourceCase, ...],
    raw_evidence: Mapping[str, JudgeEvidence],
) -> JudgeValidationReport:
    expected_ids = {case.case_id for case in cases}
    if set(raw_evidence) != expected_ids:
        raise DifferentialDataError("raw JudgeEvidence IDs must exactly match cases")
    results: list[JudgeCaseResult] = []
    for case in cases:
        evidence = raw_evidence[case.case_id]
        if not isinstance(evidence, JudgeEvidence):
            raise DifferentialDataError(f"raw JudgeEvidence is invalid for {case.case_id}")
        _validate_formal_test_evidence(case, evidence)
        results.append(_validate_case_evidence(case, evidence))
    counts = Counter(result.kind.value for result in results)
    return JudgeValidationReport(
        results=tuple(results),
        counts={kind.value: counts[kind.value] for kind in JudgeCaseKind},
    )


def _validate_formal_test_evidence(
    case: JudgeSourceCase,
    evidence: JudgeEvidence,
) -> None:
    """Require the exact final-test matrix executed by DockerJudge."""

    final_tests = (*case.problem.hidden_tests, *case.problem.generated_tests)
    expected_ids = tuple(test.test_id for test in final_tests)
    observed_ids = tuple(test.test_id for test in evidence.tests)
    if not expected_ids or observed_ids != expected_ids:
        raise DifferentialDataError(
            f"formal Judge tests must match the canonical final matrix: {case.case_id}"
        )
    unavailable = {JudgeStatus.NOT_RUN, JudgeStatus.INFRASTRUCTURE_ERROR}
    if any(test.status in unavailable for test in evidence.tests):
        raise DifferentialDataError(
            f"formal Judge per-test infrastructure evidence is unavailable: {case.case_id}"
        )
    first_failure_index = next(
        (index for index, test in enumerate(evidence.tests) if test.status is not JudgeStatus.AC),
        None,
    )
    first_failure = evidence.tests[first_failure_index] if first_failure_index is not None else None
    expected_verdict = first_failure.status if first_failure is not None else JudgeStatus.AC
    if evidence.verdict is not expected_verdict:
        raise DifferentialDataError(
            f"formal Judge aggregate verdict does not match per-test evidence: {case.case_id}"
        )
    expected_counterexample = (
        final_tests[first_failure_index].input_data if first_failure_index is not None else None
    )
    if (
        (
            first_failure is not None
            and first_failure.counterexample_input != expected_counterexample
        )
        or evidence.first_counterexample_input != expected_counterexample
        or any(
            test.counterexample_input is not None and test is not first_failure
            for test in evidence.tests
        )
    ):
        raise DifferentialDataError(
            f"formal Judge counterexample exposure is inconsistent: {case.case_id}"
        )


def _validate_case_evidence(
    case: JudgeSourceCase,
    evidence: JudgeEvidence,
) -> JudgeCaseResult:
    semantic_failures = {
        JudgeStatus.WA,
        JudgeStatus.RUNTIME_ERROR,
        JudgeStatus.TLE,
        JudgeStatus.MLE,
        JudgeStatus.OUTPUT_LIMIT,
    }
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
            raise DifferentialDataError(f"{case.kind.value} source must receive AC: {case.case_id}")
    elif evidence.verdict not in semantic_failures:
        raise DifferentialDataError(f"mutant source must fail after compiling: {case.case_id}")
    return JudgeCaseResult(
        case_id=case.case_id,
        problem_id=case.problem.problem_id,
        kind=case.kind,
        compile_status=evidence.compile_status,
        verdict=evidence.verdict,
        evidence_hash=sha256_json(evidence.model_dump(mode="json")),
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
            raise DifferentialDataError(f"differential runner failed for {case.test_id}")
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
