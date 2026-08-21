from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hy3_algotrace import RatingBand, StepReview, Topic
from hy3_algotrace import TestCase as ContractTestCase
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
    migrate_v1_1_to_v1_2,
)


def sample_case(test_id: str = "public-1") -> ContractTestCase:
    return ContractTestCase(test_id=test_id, input_data="1 2", expected_output="2")


def problem() -> ProblemRecord:
    return ProblemRecord(
        problem_id="cf-1000-a",
        title="Example",
        statement_en="Choose the larger integer.",
        source_url="https://codeforces.com/problemset/problem/1000/A",
        attribution="Codeforces Round",
        topic=Topic.GREEDY,
        rating=1400,
        time_limit_ms=1000,
        memory_limit_mb=256,
        cf_contest_id=1000,
        cf_index="A",
        cf_tags=("greedy",),
        source_split="validation",
        generated_tests=(sample_case("generated-1"),),
        content_hash="a" * 64,
    )


def trace() -> SolutionTrace:
    understanding = ReasoningStep(
        step_id="understand",
        step_number=1,
        stage=ReasoningStage.PROBLEM_UNDERSTANDING,
        claim="The input contains two integers.",
        rationale="The statement explicitly defines two values.",
        status=StepStatus.CORRECT,
    )
    algorithm = ReasoningStep(
        step_id="algorithm",
        step_number=2,
        stage=ReasoningStage.ALGORITHM_DESIGN,
        claim="Compare the values.",
        rationale="A single comparison chooses the larger value.",
        depends_on=("understand",),
        status=StepStatus.CORRECT,
    )
    return SolutionTrace(
        trace_id="trace-1",
        problem_id="cf-1000-a",
        steps=(understanding, algorithm),
        problem_understanding="Two input values are compared.",
        algorithm="Compare the two values.",
        correctness_argument="The maximum comparison returns the required value.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("Equal values.",),
        code="int main() {}",
    )


def judge_evidence(verdict: JudgeStatus = JudgeStatus.AC) -> JudgeEvidence:
    return JudgeEvidence(
        compile_status=JudgeStatus.AC,
        verdict=verdict,
        tests=(PerTestEvidence(test_id="public-1", status=verdict, time_ms=4),),
    )


def reviewer_verdict() -> ReviewerVerdict:
    review = StepReview(
        step_id="algorithm",
        status=StepStatus.INCORRECT,
        material=True,
        taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
        evidence="Comparing only two values ignores the stated objective.",
        confidence=0.9,
    )
    return ReviewerVerdict(
        reviewer_id="reviewer-a",
        trace_id="trace-1",
        material_error=True,
        error_taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
        first_error_step_id="algorithm",
        explanation="The algorithm step is materially wrong.",
        per_step_reviews=(review,),
    )


def manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        status=RunStatus.COMPLETED,
        created_at=datetime(2026, 8, 21, tzinfo=UTC),
        updated_at=datetime(2026, 8, 21, 1, tzinfo=UTC),
        config_hash="b" * 64,
        problem_ids=("cf-1000-a",),
        artifact_hash="c" * 64,
        artifact_hashes={"audit/run-1.json": "2" * 64},
        model_name="hy3",
        prompt_version="solve-audit-v1",
        model_parameters={"temperature": 0.2},
        input_hash="d" * 64,
        code_revision="c74ce98",
        container_image_digest="sha256:" + "e" * 64,
    )


def test_schema_v1_2_enums_and_problem_provenance_are_frozen() -> None:
    record = problem()

    assert record.schema_version == "1.2"
    assert {status.value for status in StepStatus} == {
        "correct",
        "acceptable_omission",
        "unsupported",
        "incorrect",
    }
    assert {stage.value for stage in ReasoningStage} == {
        "problem_understanding",
        "algorithm_design",
        "correctness_argument",
        "complexity_analysis",
        "edge_cases",
        "implementation",
    }
    assert {taxonomy.value for taxonomy in ErrorTaxonomy} == {
        "problem_misread",
        "constraint_omission",
        "algorithm_logic",
        "proof_gap_circularity",
        "complexity_error",
        "boundary_error",
        "implementation_error",
        "hallucination",
        "format_schema",
    }
    assert record.source == "codeforces"
    assert record.rating_band is RatingBand.FOUNDATION
    assert record.cf_tags == ("greedy",)
    assert record.generated_tests[0].test_id == "generated-1"
    assert record.model_dump(mode="json")["cf_tags"] == ["greedy"]

    with pytest.raises(ValidationError):
        record.rating = 1550
    with pytest.raises(AttributeError):
        record.generated_tests.append(sample_case("generated-2"))
    with pytest.raises(ValidationError):
        ProblemRecord.model_validate({**record.model_dump(), "source_split": "pilot"})
    with pytest.raises(ValidationError):
        ProblemRecord.model_validate({**record.model_dump(), "input_file": "input.txt"})
    with pytest.raises(ValidationError, match="hash"):
        ProblemRecord.model_validate({**record.model_dump(), "content_hash": "not-a-hash"})


def test_trace_requires_numbered_steps_and_user_visible_explanation_sections() -> None:
    solution = trace()

    assert solution.steps[1].depends_on == ("understand",)
    assert solution.edge_cases == ("Equal values.",)
    with pytest.raises(ValidationError, match="unique"):
        SolutionTrace.model_validate(
            {
                **solution.model_dump(),
                "steps": [
                    {**solution.steps[0].model_dump(), "step_number": 2},
                    solution.steps[1].model_dump(),
                ],
            }
        )
    with pytest.raises(ValidationError):
        SolutionTrace.model_validate({**solution.model_dump(), "edge_cases": []})
    with pytest.raises(ValidationError):
        SolutionTrace.model_validate({**solution.model_dump(), "correctness_argument": ""})


def test_step_reviews_link_material_errors_to_reviewer_candidates() -> None:
    verdict = reviewer_verdict()

    assert verdict.per_step_reviews[0].taxonomy is ErrorTaxonomy.ALGORITHM_LOGIC
    with pytest.raises(ValidationError, match="taxonomy"):
        StepReview(
            step_id="algorithm",
            status=StepStatus.INCORRECT,
            material=True,
            evidence="The operation is invalid.",
            confidence=0.8,
        )
    with pytest.raises(ValidationError, match="cannot claim an error"):
        StepReview(
            step_id="understand",
            status=StepStatus.CORRECT,
            material=False,
            taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
            evidence="The statement is read correctly.",
            confidence=0.8,
        )
    with pytest.raises(ValidationError, match="material erroneous"):
        ReviewerVerdict.model_validate(
            {**verdict.model_dump(), "first_error_step_id": "missing"}
        )


def test_audit_requires_reviewer_evidence_and_matches_execution_correctness() -> None:
    verdict = reviewer_verdict()
    report = AuditReport(
        run_id="run-1",
        problem_id="cf-1000-a",
        trace_id="trace-1",
        judge_evidence=judge_evidence(),
        reviewer_verdicts=(verdict,),
        final_correct=True,
        process_score=72,
        process_valid=False,
        final_error_taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
        first_material_error_step_id="algorithm",
    )

    assert report.process_score == 72
    with pytest.raises(ValidationError, match="final_correct"):
        AuditReport.model_validate({**report.model_dump(), "final_correct": False})
    with pytest.raises(ValidationError):
        AuditReport.model_validate({**report.model_dump(), "process_score": 101})
    with pytest.raises(ValidationError):
        AuditReport.model_validate({**report.model_dump(), "reviewer_verdicts": []})
    with pytest.raises(ValidationError, match="process_valid"):
        AuditReport.model_validate(
            {
                **report.model_dump(),
                "process_valid": True,
                "final_error_taxonomy": ErrorTaxonomy.ALGORITHM_LOGIC,
            }
        )


def test_oracle_manifest_provenance_reexports_and_v1_1_migration_strategy() -> None:
    oracle = ProblemOracle(
        problem_id="cf-1000-a",
        accepted_algorithm_families=("greedy",),
        key_invariants=("The chosen value remains feasible.",),
        complexity_ceiling="O(n log n)",
        known_traps=("Equal values.",),
        adversarial_cases=("All values equal.",),
        decisive_facts=("The maximum feasible value is required.",),
        reference_solution_hash="a" * 64,
    )
    run = manifest()

    assert oracle.accepted_algorithm_families == ("greedy",)
    assert list(run.artifact_hashes) == ["audit/run-1.json"]
    assert run.model_dump(mode="json")["model_parameters"] == {"temperature": 0.2}
    with pytest.raises(TypeError):
        run.model_parameters["temperature"] = 0.9
    with pytest.raises(ValidationError, match="timezone"):
        RunManifest.model_validate({**run.model_dump(), "updated_at": datetime(2026, 8, 21)})
    with pytest.raises(ValidationError, match="digest"):
        RunManifest.model_validate({**run.model_dump(), "container_image_digest": "latest"})

    v1_1_problem = {
        key: value
        for key, value in problem().model_dump().items()
        if key
        not in {
            "cf_contest_id",
            "cf_index",
            "cf_tags",
            "source_split",
            "generated_tests",
            "content_hash",
        }
    } | {"schema_version": "1.1"}
    with pytest.raises(ValidationError, match="unsupported schema version"):
        ProblemRecord.model_validate(v1_1_problem)
    with pytest.raises(ValueError, match="cannot safely migrate"):
        migrate_v1_1_to_v1_2(v1_1_problem, artifact_type="problem_record")


def test_v1_1_migration_refuses_non_inferable_nested_step_numbers() -> None:
    v1_1_trace = {
        "schema_version": "1.1",
        "problem_understanding": "The input is a pair.",
        "correctness_argument": "Comparison chooses the greater value.",
        "edge_cases": ["Equal values."],
        "steps": [{"step_id": "understand"}],
    }

    with pytest.raises(ValueError, match=r"steps\[\].step_number"):
        migrate_v1_1_to_v1_2(v1_1_trace, artifact_type="solution_trace")
