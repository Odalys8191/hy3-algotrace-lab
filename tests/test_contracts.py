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

    assert record.schema_version == "1.0"
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

    assert trace.schema_version == "1.0"
    assert trace.steps[1].depends_on == ["understand"]

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
    )

    assert oracle.schema_version == report.schema_version == manifest.schema_version == "1.0"
    assert report.judge_evidence.verdict is JudgeStatus.AC
    assert manifest.model_validate_json(manifest.model_dump_json()) == manifest
