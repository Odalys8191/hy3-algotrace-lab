from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hy3_algotrace.contracts import (
    AuditReport,
    ErrorTaxonomy,
    JudgeEvidence,
    JudgeStatus,
    PerTestEvidence,
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReasoningStep,
    ReviewerVerdict,
    RunManifest,
    RunStatus,
    SolutionTrace,
    StepStatus,
)
from hy3_algotrace.contracts import (
    TestCase as ContractTestCase,
)


def problem() -> ProblemRecord:
    return ProblemRecord(
        problem_id="cf-1000-a",
        title="Example",
        statement_en="Choose the larger integer.",
        source_url="https://example.test/problem",
        attribution="Example contest",
        topic="greedy",
        rating=1400,
        time_limit_ms=1000,
        memory_limit_mb=256,
    )


def test_problem_record_accepts_only_formal_topic_rating_bands_and_cpp17() -> None:
    record = problem()

    assert record.schema_version == "1.1"
    assert record.topic.value == "greedy"
    assert record.language == "cpp17"
    assert record.rating_band.value == "1200-1500"

    with pytest.raises(ValidationError, match="rating must fall"):
        ProblemRecord.model_validate({**record.model_dump(), "rating": 1550})
    with pytest.raises(ValidationError):
        ProblemRecord.model_validate({**record.model_dump(), "topic": "math"})
    with pytest.raises(ValidationError):
        ProblemRecord.model_validate({**record.model_dump(), "language": "python"})


def test_solution_trace_rejects_duplicate_unknown_and_cyclic_step_dependencies() -> None:
    first = ReasoningStep(
        step_id="understand",
        stage=ReasoningStage.PROBLEM_UNDERSTANDING,
        claim="The input contains two integers.",
        rationale="The statement explicitly defines two values.",
        status=StepStatus.SUPPORTED,
    )
    second = ReasoningStep(
        step_id="algorithm",
        stage=ReasoningStage.ALGORITHM_DESIGN,
        claim="Compare the values.",
        rationale="A single comparison chooses the larger value.",
        depends_on=["understand"],
        status=StepStatus.SUPPORTED,
    )
    trace = SolutionTrace(
        trace_id="trace-1",
        problem_id="cf-1000-a",
        steps=[first, second],
        algorithm="Compare the two values.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        code="int main() {}",
    )

    assert trace.schema_version == "1.1"
    assert trace.steps[1].depends_on == ("understand",)

    with pytest.raises(ValidationError, match="unique"):
        SolutionTrace.model_validate(
            {**trace.model_dump(), "steps": [first.model_dump(), first.model_dump()]}
        )
    with pytest.raises(ValidationError, match="unknown"):
        SolutionTrace.model_validate(
            {
                **trace.model_dump(),
                "steps": [{**first.model_dump(), "depends_on": ["missing"]}],
            }
        )
    with pytest.raises(ValidationError, match="acyclic"):
        SolutionTrace.model_validate(
            {
                **trace.model_dump(),
                "steps": [
                    {**first.model_dump(), "depends_on": ["algorithm"]},
                    second.model_dump(),
                ],
            }
        )


def test_reviewer_material_error_requires_taxonomy_and_first_error_step() -> None:
    verdict = ReviewerVerdict(
        reviewer_id="reviewer-a",
        trace_id="trace-1",
        material_error=True,
        error_taxonomy=ErrorTaxonomy.ALGORITHM_ERROR,
        first_error_step_id="algorithm",
        explanation="The proposed comparison does not solve the real optimization problem.",
    )

    assert verdict.material_error is True
    with pytest.raises(ValidationError, match="material error"):
        ReviewerVerdict(
            reviewer_id="reviewer-a",
            trace_id="trace-1",
            material_error=True,
            explanation="A material error needs evidence.",
        )
    with pytest.raises(ValidationError, match="first_error_step_id"):
        ReviewerVerdict(
            reviewer_id="reviewer-a",
            trace_id="trace-1",
            material_error=True,
            error_taxonomy=ErrorTaxonomy.ALGORITHM_ERROR,
            first_error_step_id="",
            explanation="An empty error step cannot locate a material error.",
        )
    with pytest.raises(ValidationError, match="non-material"):
        ReviewerVerdict(
            reviewer_id="reviewer-a",
            trace_id="trace-1",
            material_error=False,
            error_taxonomy=ErrorTaxonomy.ALGORITHM_ERROR,
            first_error_step_id="algorithm",
            explanation="No error exists.",
        )


def test_frozen_contracts_round_trip_judge_oracle_report_and_manifest() -> None:
    judged_at = datetime(2026, 8, 21, tzinfo=UTC)
    evidence = JudgeEvidence(
        compile_status=JudgeStatus.AC,
        verdict=JudgeStatus.AC,
        tests=[
            PerTestEvidence(
                test_id="public-1",
                status=JudgeStatus.AC,
                time_ms=4,
                memory_kb=1024,
            )
        ],
        diagnostics="",
    )
    oracle = ProblemOracle(
        problem_id="cf-1000-a",
        decisive_facts=["The larger integer is the output."],
        reference_solution_hash="a" * 64,
    )
    report = AuditReport(
        run_id="run-1",
        problem_id="cf-1000-a",
        trace_id="trace-1",
        judge_evidence=evidence,
        reviewer_verdicts=[],
        process_valid=True,
        final_error_taxonomy=None,
        first_material_error_step_id=None,
        needs_human_review=False,
    )
    manifest = RunManifest(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        created_at=judged_at,
        config_hash="b" * 64,
        problem_ids=["cf-1000-a"],
        artifact_hash="c" * 64,
        artifact_hashes={
            "problem/cf-1000-a.json": "d" * 64,
            "oracle/cf-1000-a.json": "e" * 64,
            "trace/trace-1.json": "f" * 64,
            "judge/run-1.json": "1" * 64,
            "audit/run-1.json": "2" * 64,
        },
    )

    assert oracle.schema_version == report.schema_version == manifest.schema_version == "1.1"
    assert report.judge_evidence.verdict is JudgeStatus.AC
    assert manifest.model_validate_json(manifest.model_dump_json()) == manifest


def test_contracts_are_deeply_immutable_after_validation() -> None:
    record = problem()
    test_case = PerTestEvidence(test_id="public-1", status=JudgeStatus.AC)

    with pytest.raises(ValidationError):
        record.rating = 1550
    with pytest.raises(AttributeError):
        record.public_tests.append(
            ContractTestCase(test_id="public-1", input_data="1 2", expected_output="2")
        )
    with pytest.raises(ValidationError):
        test_case.test_id = "mutated"


def test_audit_report_requires_taxonomy_and_first_step_to_match_process_valid() -> None:
    evidence = JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC)
    valid_kwargs = {
        "run_id": "run-1",
        "problem_id": "cf-1000-a",
        "trace_id": "trace-1",
        "judge_evidence": evidence,
        "reviewer_verdicts": [],
        "needs_human_review": False,
    }

    with pytest.raises(ValidationError, match="process_valid"):
        AuditReport(
            **valid_kwargs,
            process_valid=True,
            final_error_taxonomy=ErrorTaxonomy.ALGORITHM_ERROR,
            first_material_error_step_id=None,
        )
    with pytest.raises(ValidationError, match="process_valid"):
        AuditReport(
            **valid_kwargs,
            process_valid=False,
            final_error_taxonomy=None,
            first_material_error_step_id="algorithm",
        )
    with pytest.raises(ValidationError, match="first_material_error_step_id"):
        AuditReport(
            **valid_kwargs,
            process_valid=False,
            final_error_taxonomy=ErrorTaxonomy.ALGORITHM_ERROR,
            first_material_error_step_id="",
        )


def test_run_manifest_tracks_immutable_per_artifact_hashes_and_validates_metadata() -> None:
    manifest = RunManifest(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        config_hash="b" * 64,
        problem_ids=["cf-1000-a"],
        artifact_hash="c" * 64,
        artifact_hashes={
            "trace/trace-1.json": "f" * 64,
            "audit/run-1.json": "2" * 64,
        },
    )

    assert list(manifest.artifact_hashes) == ["audit/run-1.json", "trace/trace-1.json"]
    with pytest.raises(TypeError):
        manifest.artifact_hashes["audit/run-1.json"] = "0" * 64
    with pytest.raises(ValidationError, match="hash"):
        RunManifest.model_validate({**manifest.model_dump(), "artifact_hash": "not-a-hash"})
    with pytest.raises(ValidationError, match="unique"):
        RunManifest.model_validate(
            {**manifest.model_dump(), "problem_ids": ["cf-1000-a", "cf-1000-a"]}
        )
    with pytest.raises(ValidationError, match="timezone"):
        RunManifest.model_validate(
            {**manifest.model_dump(), "created_at": datetime(2026, 8, 21)}
        )


def test_contract_version_1_1_rejects_pre_release_1_0_report_and_manifest_payloads() -> None:
    evidence = JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC)
    report = AuditReport(
        run_id="run-1",
        problem_id="cf-1000-a",
        trace_id="trace-1",
        judge_evidence=evidence,
        reviewer_verdicts=[],
        process_valid=True,
    )
    manifest = RunManifest(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        config_hash="b" * 64,
        problem_ids=["cf-1000-a"],
        artifact_hash="c" * 64,
        artifact_hashes={"audit/run-1.json": "2" * 64},
    )
    pre_release_report = report.model_dump(exclude={"process_valid"}) | {"schema_version": "1.0"}
    pre_release_manifest = manifest.model_dump(exclude={"artifact_hashes"}) | {
        "schema_version": "1.0"
    }

    assert report.schema_version == manifest.schema_version == "1.1"
    with pytest.raises(ValidationError, match="unsupported schema version"):
        AuditReport.model_validate(pre_release_report)
    with pytest.raises(ValidationError, match="unsupported schema version"):
        RunManifest.model_validate(pre_release_manifest)
