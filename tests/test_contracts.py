from __future__ import annotations

import json
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
        public_tests=(sample_case("public-1"),),
        hidden_tests=(sample_case("hidden-1"),),
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


def audit_report() -> AuditReport:
    return AuditReport(
        run_id="run-1",
        problem_id="cf-1000-a",
        trace_id="trace-1",
        judge_evidence=judge_evidence(),
        reviewer_verdicts=(reviewer_verdict(),),
        final_correct=True,
        process_score=72,
        process_valid=False,
        final_error_taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
        first_material_error_step_id="algorithm",
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


def mark_contract_versions(value: object, version: str) -> None:
    if isinstance(value, dict):
        if "schema_version" in value:
            value["schema_version"] = version
        for nested_value in value.values():
            mark_contract_versions(nested_value, version)
    elif isinstance(value, list):
        for nested_value in value:
            mark_contract_versions(nested_value, version)


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


def test_solution_trace_rejects_duplicate_step_ids_unknown_dependencies_and_cycles() -> None:
    solution = trace()
    first, second = (step.model_dump(mode="json") for step in solution.steps)

    with pytest.raises(ValidationError, match="step IDs must be unique"):
        SolutionTrace.model_validate(
            {
                **solution.model_dump(mode="json"),
                "steps": [first, {**second, "step_id": first["step_id"]}],
            }
        )
    with pytest.raises(ValidationError, match="unknown step IDs"):
        SolutionTrace.model_validate(
            {
                **solution.model_dump(mode="json"),
                "steps": [first, {**second, "depends_on": ["missing"]}],
            }
        )
    with pytest.raises(ValidationError, match="acyclic"):
        SolutionTrace.model_validate(
            {
                **solution.model_dump(mode="json"),
                "steps": [{**first, "depends_on": [second["step_id"]]}, second],
            }
        )


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
        ReviewerVerdict.model_validate({**verdict.model_dump(), "first_error_step_id": "missing"})


def test_non_material_reviewer_verdict_rejects_material_erroneous_step_review() -> None:
    verdict = reviewer_verdict()

    with pytest.raises(ValidationError, match="non-material verdict"):
        ReviewerVerdict.model_validate(
            {
                **verdict.model_dump(mode="json"),
                "material_error": False,
                "error_taxonomy": None,
                "first_error_step_id": None,
            }
        )


def test_reviewer_verdict_taxonomy_matches_linked_step_review() -> None:
    verdict = reviewer_verdict()

    with pytest.raises(ValidationError, match="taxonomy must match"):
        ReviewerVerdict.model_validate(
            {
                **verdict.model_dump(mode="json"),
                "error_taxonomy": ErrorTaxonomy.BOUNDARY_ERROR,
            }
        )


def test_reviewer_verdict_links_first_material_error_in_evidence_order() -> None:
    verdict = reviewer_verdict()
    earlier_review = StepReview(
        step_id="understand",
        status=StepStatus.UNSUPPORTED,
        material=True,
        taxonomy=ErrorTaxonomy.PROBLEM_MISREAD,
        evidence="The input interpretation is not supported by the statement.",
        confidence=0.95,
    )

    with pytest.raises(ValidationError, match="first material erroneous step review"):
        ReviewerVerdict.model_validate(
            {
                **verdict.model_dump(mode="json"),
                "per_step_reviews": [
                    earlier_review.model_dump(mode="json"),
                    verdict.per_step_reviews[0].model_dump(mode="json"),
                ],
            }
        )


def test_audit_requires_reviewer_evidence_and_matches_execution_correctness() -> None:
    report = audit_report()

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


def test_audit_report_enforces_both_sides_of_taxonomy_first_step_pairing() -> None:
    report = audit_report()
    payload = report.model_dump(mode="json")

    for invalid_valid_process in (
        {
            **payload,
            "process_valid": True,
            "final_error_taxonomy": ErrorTaxonomy.ALGORITHM_LOGIC,
            "first_material_error_step_id": None,
        },
        {
            **payload,
            "process_valid": True,
            "final_error_taxonomy": None,
            "first_material_error_step_id": "algorithm",
        },
    ):
        with pytest.raises(ValidationError, match="process_valid"):
            AuditReport.model_validate(invalid_valid_process)

    for invalid_invalid_process in (
        {**payload, "final_error_taxonomy": None},
        {**payload, "first_material_error_step_id": None},
    ):
        with pytest.raises(ValidationError, match="process_valid=False"):
            AuditReport.model_validate(invalid_invalid_process)


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


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("missing_per_step_reviews", "per_step_reviews"),
        ("old_step_status", "supported"),
        ("old_taxonomy", "algorithm_error"),
    ],
)
def test_v1_1_audit_migration_validates_nested_v1_2_contracts(
    mutation: str, expected_error: str
) -> None:
    payload = audit_report().model_dump(mode="json")
    mark_contract_versions(payload, "1.1")
    nested_verdict = payload["reviewer_verdicts"][0]
    if mutation == "missing_per_step_reviews":
        del nested_verdict["per_step_reviews"]
    elif mutation == "old_step_status":
        nested_verdict["per_step_reviews"][0]["status"] = "supported"
    else:
        nested_verdict["per_step_reviews"][0]["taxonomy"] = "algorithm_error"

    with pytest.raises(ValueError, match=rf"cannot safely migrate.*{expected_error}"):
        migrate_v1_1_to_v1_2(payload, artifact_type="audit_report")


@pytest.mark.parametrize(
    ("artifact_type", "artifact_factory"),
    [
        ("problem_record", problem),
        ("solution_trace", trace),
        ("reviewer_verdict", reviewer_verdict),
        ("audit_report", audit_report),
    ],
)
def test_v1_1_migration_retags_every_known_nested_contract(
    artifact_type: str, artifact_factory: object
) -> None:
    artifact = artifact_factory()
    expected = artifact.model_dump(mode="json")
    payload = artifact.model_dump(mode="json")
    mark_contract_versions(payload, "1.1")

    migrated = migrate_v1_1_to_v1_2(payload, artifact_type=artifact_type)

    assert migrated == expected


@pytest.mark.parametrize(
    ("artifact_type", "artifact_factory", "nested_contract_path", "nested_version"),
    [
        ("audit_report", audit_report, ("judge_evidence",), "1.2"),
        ("solution_trace", trace, ("steps", 0), "9.9"),
    ],
)
def test_v1_1_migration_rejects_mixed_or_unknown_nested_contract_versions(
    artifact_type: str,
    artifact_factory: object,
    nested_contract_path: tuple[str | int, ...],
    nested_version: str,
) -> None:
    payload = artifact_factory().model_dump(mode="json")
    mark_contract_versions(payload, "1.1")
    nested_contract = payload
    for path_component in nested_contract_path:
        nested_contract = nested_contract[path_component]
    nested_contract["schema_version"] = nested_version

    with pytest.raises(ValueError, match=r"cannot safely migrate.*nested contract schema version"):
        migrate_v1_1_to_v1_2(payload, artifact_type=artifact_type)


def test_v1_1_migration_returns_validated_canonical_json_data() -> None:
    payload = manifest().model_dump()
    payload["schema_version"] = "1.1"
    payload["model_parameters"]["schema_version"] = "1.1"

    migrated = migrate_v1_1_to_v1_2(payload, artifact_type="run_manifest")

    expected = manifest().model_dump(mode="json")
    expected["model_parameters"]["schema_version"] = "1.1"
    assert migrated == expected
    assert json.loads(json.dumps(migrated)) == migrated


def test_v1_1_migration_rejects_unknown_artifact_types() -> None:
    with pytest.raises(ValueError, match="unsupported artifact type"):
        migrate_v1_1_to_v1_2({"schema_version": "1.1"}, artifact_type="unrecognized_artifact")


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


@pytest.mark.parametrize("hash_field", ["config_hash", "artifact_hash", "input_hash"])
def test_run_manifest_rejects_malformed_run_hashes(hash_field: str) -> None:
    run = manifest()

    with pytest.raises(ValidationError, match="SHA-256"):
        RunManifest.model_validate({**run.model_dump(), hash_field: "g" * 64})

    with pytest.raises(ValidationError, match="SHA-256"):
        RunManifest.model_validate(
            {**run.model_dump(), "artifact_hashes": {"audit/run-1.json": "not-a-hash"}}
        )


def test_run_manifest_rejects_duplicate_problem_ids() -> None:
    run = manifest()

    with pytest.raises(ValidationError, match="problem IDs must be unique"):
        RunManifest.model_validate({**run.model_dump(), "problem_ids": ["cf-1000-a", "cf-1000-a"]})


@pytest.mark.parametrize("timestamp_field", ["created_at", "updated_at"])
def test_run_manifest_rejects_naive_timestamps_with_actual_field_name(
    timestamp_field: str,
) -> None:
    run = manifest()

    with pytest.raises(ValidationError, match=rf"{timestamp_field} must include a timezone"):
        RunManifest.model_validate({**run.model_dump(), timestamp_field: datetime(2026, 8, 21)})


def test_contracts_remain_deeply_immutable_after_validation() -> None:
    record = problem()
    solution = trace()
    run = manifest()

    with pytest.raises(ValidationError):
        record.generated_tests[0].test_id = "mutated"
    with pytest.raises(AttributeError):
        solution.steps.append(solution.steps[0])
    with pytest.raises(TypeError):
        run.artifact_hashes["audit/run-1.json"] = "0" * 64
    with pytest.raises(TypeError):
        run.model_parameters["temperature"] = 0.9
