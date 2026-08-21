from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from hy3_algotrace.contracts import (
    ErrorTaxonomy,
    JudgeEvidence,
    JudgeStatus,
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReasoningStep,
    ReviewerVerdict,
    SolutionTrace,
    StepReview,
    StepStatus,
    Topic,
)
from hy3_algotrace.evaluator import (
    DIMENSION_WEIGHTS,
    EvidenceFusion,
    InfrastructureEvidenceError,
    ReviewOrchestrator,
    ReviewOutcome,
    is_paradox,
    localize_root_error,
    score_process,
)
from hy3_algotrace.hy3_client import Hy3Client, Hy3Config, JsonResponseCache
from hy3_algotrace.rules import RuleEngine, RuleSignal


def problem() -> ProblemRecord:
    return ProblemRecord(
        problem_id="problem-1",
        title="Maximum",
        statement_en="Print the maximum of two integers.",
        source_url="https://codeforces.com/problemset/problem/1/A",
        attribution="Codeforces",
        cf_contest_id=1,
        cf_index="A",
        cf_tags=("implementation",),
        source_split="validation",
        topic=Topic.CONSTRUCTION_SIMULATION,
        rating=1200,
        time_limit_ms=1000,
        memory_limit_mb=256,
        content_hash="a" * 64,
    )


def oracle() -> ProblemOracle:
    return ProblemOracle(
        problem_id="problem-1",
        accepted_algorithm_families=("comparison",),
        key_invariants=("the printed value is at least each input",),
        complexity_ceiling="O(1)",
        known_traps=("equal inputs",),
        adversarial_cases=("5 5",),
        decisive_facts=("std::max returns the larger argument",),
        reference_solution_hash="b" * 64,
    )


def trace() -> SolutionTrace:
    stages = tuple(ReasoningStage)
    steps = tuple(
        ReasoningStep(
            step_id=f"step-{index}",
            step_number=index,
            stage=stage,
            claim=f"Claim for {stage.value}.",
            rationale=f"Rationale for {stage.value}.",
            depends_on=() if index == 1 else (f"step-{index - 1}",),
        )
        for index, stage in enumerate(stages, start=1)
    )
    return SolutionTrace(
        trace_id="trace-1",
        problem_id="problem-1",
        steps=steps,
        problem_understanding="Read two integers.",
        algorithm="Compare them.",
        correctness_argument="The comparison returns the maximum.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("Equal inputs.",),
        code="int main() { return 0; }",
    )


def verdict(
    reviewer_id: str,
    *,
    error_step_ids: tuple[str, ...] = (),
    taxonomy: ErrorTaxonomy = ErrorTaxonomy.ALGORITHM_LOGIC,
) -> ReviewerVerdict:
    if not error_step_ids:
        review = StepReview(
            step_id="step-1",
            status=StepStatus.CORRECT,
            material=False,
            evidence="The checked reasoning is consistent.",
            confidence=0.9,
        )
        return ReviewerVerdict(
            reviewer_id=reviewer_id,
            trace_id="trace-1",
            material_error=False,
            explanation="No material error found.",
            per_step_reviews=(review,),
            confidence=0.9,
        )
    reviews = tuple(
        StepReview(
            step_id=step_id,
            status=StepStatus.INCORRECT,
            material=True,
            taxonomy=taxonomy,
            evidence=f"{step_id} is materially wrong.",
            confidence=0.9,
        )
        for step_id in error_step_ids
    )
    return ReviewerVerdict(
        reviewer_id=reviewer_id,
        trace_id="trace-1",
        material_error=True,
        error_taxonomy=taxonomy,
        first_error_step_id=error_step_ids[0],
        explanation="A material error was found.",
        per_step_reviews=reviews,
        confidence=0.9,
    )


def completion(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]},
    )


def test_two_reviewers_are_isolated_and_agreement_skips_arbiter(tmp_path: Path) -> None:
    bodies: list[dict[str, object]] = []
    payloads = iter(
        [
            verdict("logic-reviewer").model_dump(mode="json"),
            verdict("adversarial-reviewer").model_dump(mode="json"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return completion(next(payloads))

    client = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="test-key"),
        cache=JsonResponseCache(tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
    )

    outcome = ReviewOrchestrator(client).review(problem(), oracle(), trace())

    assert outcome.material_disagreement is False
    assert outcome.arbiter is None
    assert outcome.unresolved is False
    assert len(bodies) == 2
    assert all(len(body["messages"]) == 2 for body in bodies)
    assert "logic-reviewer" not in json.dumps(bodies[1])
    assert "adversarial-reviewer" not in json.dumps(bodies[0])


def test_material_disagreement_calls_arbiter_with_both_verdicts(tmp_path: Path) -> None:
    bodies: list[dict[str, object]] = []
    logic = verdict("logic-reviewer", error_step_ids=("step-2",))
    adversarial = verdict("adversarial-reviewer")
    arbiter = verdict("arbiter", error_step_ids=("step-2",))
    payloads = iter(
        [
            logic.model_dump(mode="json"),
            adversarial.model_dump(mode="json"),
            arbiter.model_dump(mode="json"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return completion(next(payloads))

    client = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="test-key"),
        cache=JsonResponseCache(tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
    )

    outcome = ReviewOrchestrator(client).review(problem(), oracle(), trace())

    assert outcome.material_disagreement is True
    assert outcome.arbiter == arbiter
    assert outcome.unresolved is False
    assert len(bodies) == 3
    arbiter_request = json.dumps(bodies[2])
    assert "logic-reviewer" in arbiter_request
    assert "adversarial-reviewer" in arbiter_request


def test_dimension_weights_and_score_use_exact_required_values() -> None:
    solution = trace()

    assert tuple(DIMENSION_WEIGHTS.values()) == (20, 25, 20, 10, 10, 15)
    assert score_process(solution, ()) == 100.0
    for step, weight in zip(solution.steps, DIMENSION_WEIGHTS.values(), strict=True):
        assert score_process(solution, (step.step_id,)) == 100.0 - weight


def test_root_localization_chooses_earliest_independent_dependency_error() -> None:
    solution = trace()
    logic = verdict(
        "logic-reviewer",
        error_step_ids=("step-1", "step-2", "step-3"),
        taxonomy=ErrorTaxonomy.PROBLEM_MISREAD,
    )

    root = localize_root_error(solution, logic.per_step_reviews)

    assert root == "step-1"


def test_deterministic_rules_override_reviewer_consensus_and_preserve_ac_paradox() -> None:
    solution = trace()
    finding = RuleEngine().classify_signal(
        RuleSignal.PROOF_GAP_CIRCULARITY,
        step_id="step-3",
        evidence="The proof assumes its conclusion.",
    )
    reviews = ReviewOutcome(
        primary=(verdict("logic-reviewer"), verdict("adversarial-reviewer")),
    )

    report = EvidenceFusion().fuse(
        run_id="run-1",
        problem=problem(),
        trace=solution,
        judge=JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC),
        rule_findings=(finding,),
        reviews=reviews,
    )

    assert report.final_correct is True
    assert report.process_valid is False
    assert report.final_error_taxonomy is ErrorTaxonomy.PROOF_GAP_CIRCULARITY
    assert report.first_material_error_step_id == "step-3"
    assert report.process_score == 80.0
    assert report.needs_human_review is False
    assert is_paradox(report) is True


def test_execution_failure_overrides_model_opinion() -> None:
    reviews = ReviewOutcome(
        primary=(verdict("logic-reviewer"), verdict("adversarial-reviewer")),
    )

    report = EvidenceFusion().fuse(
        run_id="run-1",
        problem=problem(),
        trace=trace(),
        judge=JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.WA),
        rule_findings=(),
        reviews=reviews,
    )

    assert report.final_correct is False
    assert report.process_valid is False
    assert report.final_error_taxonomy is ErrorTaxonomy.IMPLEMENTATION_ERROR
    assert report.first_material_error_step_id == "step-5"
    assert report.process_score == 90.0


def test_novel_arbiter_result_is_unresolved_and_needs_human_review() -> None:
    logic = verdict("logic-reviewer", error_step_ids=("step-2",))
    adversarial = verdict(
        "adversarial-reviewer",
        error_step_ids=("step-6",),
        taxonomy=ErrorTaxonomy.BOUNDARY_ERROR,
    )
    arbiter = verdict(
        "arbiter",
        error_step_ids=("step-3",),
        taxonomy=ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
    )
    reviews = ReviewOutcome(
        primary=(logic, adversarial),
        arbiter=arbiter,
        material_disagreement=True,
        unresolved=True,
    )

    report = EvidenceFusion().fuse(
        run_id="run-1",
        problem=problem(),
        trace=trace(),
        judge=JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC),
        rule_findings=(),
        reviews=reviews,
    )

    assert report.needs_human_review is True
    assert report.final_error_taxonomy is ErrorTaxonomy.PROOF_GAP_CIRCULARITY
    assert report.first_material_error_step_id == "step-3"


def test_infrastructure_failure_is_not_mapped_into_process_taxonomy() -> None:
    reviews = ReviewOutcome(
        primary=(verdict("logic-reviewer"), verdict("adversarial-reviewer")),
    )

    with pytest.raises(InfrastructureEvidenceError, match="infrastructure"):
        EvidenceFusion().fuse(
            run_id="run-1",
            problem=problem(),
            trace=trace(),
            judge=JudgeEvidence(
                compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
                verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
            ),
            rule_findings=(),
            reviews=reviews,
        )


def test_task4_interfaces_are_available_from_the_public_package() -> None:
    from hy3_algotrace import EvidenceFusion, Hy3Client, ReviewOrchestrator, RuleEngine

    assert EvidenceFusion.__name__ == "EvidenceFusion"
    assert Hy3Client.__name__ == "Hy3Client"
    assert ReviewOrchestrator.__name__ == "ReviewOrchestrator"
    assert RuleEngine.__name__ == "RuleEngine"
