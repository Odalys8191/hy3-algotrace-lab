from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hy3_algotrace.api_models import (
    RunCreateRequest,
    RunFailureCode,
    RunMode,
    RunTransitionEvent,
)
from hy3_algotrace.artifacts import ArtifactStore, ArtifactStoreError, sha256_json
from hy3_algotrace.catalog import ProblemBundle, ProblemCatalog, problem_content_hash
from hy3_algotrace.contracts import (
    ErrorTaxonomy,
    JudgeEvidence,
    JudgeStatus,
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReasoningStep,
    ReviewerVerdict,
    RunStatus,
    SolutionTrace,
    StepReview,
    StepStatus,
    Topic,
)
from hy3_algotrace.contracts import (
    TestCase as ContractTestCase,
)
from hy3_algotrace.evaluator import EvidenceFusion, ReviewOutcome
from hy3_algotrace.executor import InProcessBackgroundExecutor, SynchronousExecutor
from hy3_algotrace.rules import RuleEngine
from hy3_algotrace.run_service import ProblemNotFoundError, RunService


def formal_bundle(*, problem_id: str = "cf-123-a") -> ProblemBundle:
    reference_cpp = "#include <iostream>\nint main(){std::cout << 2 << '\\n';}\n"
    record = ProblemRecord(
        problem_id=problem_id,
        title="Add One",
        statement_en="Given one integer, print the integer plus one.",
        source_url="https://codeforces.com/problemset/problem/123/A",
        attribution="Codeforces 123A",
        cf_contest_id=123,
        cf_index="A",
        cf_tags=("greedy",),
        source_split="validation",
        topic=Topic.GREEDY,
        rating=1200,
        time_limit_ms=1000,
        memory_limit_mb=256,
        public_tests=(
            ContractTestCase(test_id="public-1", input_data="1\n", expected_output="2\n"),
        ),
        hidden_tests=(
            ContractTestCase(test_id="hidden-1", input_data="41\n", expected_output="42\n"),
        ),
        generated_tests=(
            ContractTestCase(test_id="generated-1", input_data="-1\n", expected_output="0\n"),
        ),
        content_hash="0" * 64,
    )
    record = record.model_copy(update={"content_hash": problem_content_hash(record)})
    trace = valid_trace(problem_id=problem_id)
    oracle = ProblemOracle(
        problem_id=problem_id,
        accepted_algorithm_families=("arithmetic",),
        key_invariants=("answer is x + 1",),
        complexity_ceiling="O(1)",
        known_traps=("integer parsing",),
        adversarial_cases=("negative values",),
        decisive_facts=("one addition is sufficient",),
        reference_solution_hash=sha256_json(reference_cpp),
    )
    return ProblemBundle(record, oracle, reference_cpp, trace)


def valid_trace(*, problem_id: str = "cf-123-a", trace_id: str = "trace-1") -> SolutionTrace:
    return SolutionTrace(
        trace_id=trace_id,
        problem_id=problem_id,
        steps=(
            ReasoningStep(
                step_id="s1",
                step_number=1,
                stage=ReasoningStage.PROBLEM_UNDERSTANDING,
                claim="Read x.",
                rationale="The input contains one integer.",
            ),
            ReasoningStep(
                step_id="s2",
                step_number=2,
                stage=ReasoningStage.IMPLEMENTATION,
                claim="Print x + 1.",
                rationale="This is the requested value.",
                depends_on=("s1",),
            ),
        ),
        problem_understanding="Read one integer.",
        algorithm="Add one and print.",
        correctness_argument="The printed value is exactly one larger.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("negative integers",),
        code="#include <iostream>\nint main(){long long x;std::cin>>x;std::cout<<x+1;}",
    )


def clean_verdict(trace: SolutionTrace, reviewer_id: str) -> ReviewerVerdict:
    return ReviewerVerdict(
        reviewer_id=reviewer_id,
        trace_id=trace.trace_id,
        material_error=False,
        explanation="The reasoning is consistent.",
        per_step_reviews=tuple(
            StepReview(
                step_id=step.step_id,
                status=StepStatus.CORRECT,
                material=False,
                evidence="Supported by the trace.",
                confidence=1.0,
            )
            for step in trace.steps
        ),
    )


class FakeGenerator:
    def __init__(self, trace: SolutionTrace, error: BaseException | None = None) -> None:
        self.trace = trace
        self.error = error
        self.calls = 0

    def generate(self, problem: ProblemRecord) -> SolutionTrace:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.trace


class FakeJudge:
    def __init__(self, verdict: JudgeStatus = JudgeStatus.AC) -> None:
        self.verdict = verdict

    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        compile_status = (
            JudgeStatus.INFRASTRUCTURE_ERROR
            if self.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
            else JudgeStatus.AC
        )
        return JudgeEvidence(compile_status=compile_status, verdict=self.verdict)


class CleanReviews:
    def review(
        self, problem: ProblemRecord, oracle: ProblemOracle, trace: SolutionTrace
    ) -> ReviewOutcome:
        return ReviewOutcome(
            primary=(
                clean_verdict(trace, "logic-reviewer"),
                clean_verdict(trace, "adversarial-reviewer"),
            )
        )


class HoldingExecutor:
    def __init__(self) -> None:
        self.tasks: list[Callable[[], None]] = []

    def submit(self, task: Callable[[], None]) -> None:
        self.tasks.append(task)


class FailInternalReportStore(ArtifactStore):
    def write_json(
        self,
        relative_path: Path | str,
        payload: Any,
        *,
        expected_hash: str | None = None,
    ):  # type: ignore[no-untyped-def]
        if "internal-report" in str(relative_path):
            raise ArtifactStoreError("/private/tmp/secret should not escape")
        return super().write_json(relative_path, payload, expected_hash=expected_hash)


def service(
    tmp_path: Path,
    *,
    generator: FakeGenerator | None = None,
    judge: FakeJudge | None = None,
    executor: Any | None = None,
    store: ArtifactStore | None = None,
    id_factory: Callable[[], str] | None = None,
    reviews: Any | None = None,
) -> tuple[RunService, FakeGenerator, ArtifactStore]:
    bundle = formal_bundle()
    chosen_generator = generator or FakeGenerator(bundle.gold_trace)
    chosen_store = store or ArtifactStore(tmp_path / "artifacts")
    return (
        RunService(
            catalog=ProblemCatalog((bundle,)),
            artifacts=chosen_store,
            generator=chosen_generator,
            judge=judge or FakeJudge(),
            reviews=reviews or CleanReviews(),
            rules=RuleEngine(),
            fusion=EvidenceFusion(),
            executor=executor or SynchronousExecutor(),
            clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
            id_factory=id_factory,
        ),
        chosen_generator,
        chosen_store,
    )


def test_solve_and_audit_calls_generator_once_and_persists_hash_chain(tmp_path: Path) -> None:
    run_service, generator, _ = service(tmp_path, id_factory=lambda: "run-solve")

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)
    history = run_service.get_transition_history(accepted.run_id)

    assert accepted.status is RunStatus.QUEUED
    assert generator.calls == 1
    assert result.status is RunStatus.COMPLETED
    assert result.report is not None
    with pytest.raises(TypeError):
        result.report.audit["final_correct"] = False
    assert [item.transition.event for item in history] == [
        RunTransitionEvent.REQUEST,
        RunTransitionEvent.QUEUED,
        RunTransitionEvent.RUNNING,
        RunTransitionEvent.COMPLETED,
    ]
    assert [item.transition.sequence for item in history] == [0, 1, 2, 3]
    assert history[0].transition.previous_transition_hash is None
    assert all(
        current.transition.previous_transition_hash == previous.content_hash
        for previous, current in zip(history, history[1:])
    )
    request_hash = history[0].transition.request_artifact_hash
    assert all(item.transition.manifest.artifact_hash == request_hash for item in history)


def test_audit_requires_matching_trace_and_never_calls_generator(tmp_path: Path) -> None:
    run_service, generator, _ = service(tmp_path, id_factory=lambda: "run-audit")
    trace = valid_trace()

    result = run_service.submit(
        RunCreateRequest(mode=RunMode.AUDIT, problem_id="cf-123-a", trace=trace)
    )

    assert run_service.get_run(result.run_id).status is RunStatus.COMPLETED
    assert generator.calls == 0
    with pytest.raises(ValueError, match="must match"):
        RunCreateRequest(
            mode=RunMode.AUDIT,
            problem_id="cf-123-a",
            trace=valid_trace(problem_id="cf-999-z"),
        )
    with pytest.raises(ValueError, match="requires"):
        RunCreateRequest(mode=RunMode.AUDIT, problem_id="cf-123-a")


@pytest.mark.parametrize(
    ("generator_error", "judge_status", "expected"),
    [
        (RuntimeError("Bearer super-secret"), JudgeStatus.AC, RunFailureCode.GENERATION_FAILED),
        (None, JudgeStatus.INFRASTRUCTURE_ERROR, RunFailureCode.JUDGE_INFRASTRUCTURE),
    ],
)
def test_infrastructure_failures_end_in_safe_failed_transition(
    tmp_path: Path,
    generator_error: BaseException | None,
    judge_status: JudgeStatus,
    expected: RunFailureCode,
) -> None:
    bundle = formal_bundle()
    run_service, _, _ = service(
        tmp_path,
        generator=FakeGenerator(bundle.gold_trace, generator_error),
        judge=FakeJudge(judge_status),
    )

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is expected
    assert "secret" not in result.model_dump_json().lower()
    assert result.report is None


def test_wa_is_a_completed_audit_not_an_infrastructure_failure(tmp_path: Path) -> None:
    run_service, _, _ = service(tmp_path, judge=FakeJudge(JudgeStatus.WA))

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)

    assert result.status is RunStatus.COMPLETED
    assert result.failure is None
    assert result.report is not None
    assert result.report.audit["final_correct"] is False


def test_artifact_failure_after_queue_is_recorded_as_failed(tmp_path: Path) -> None:
    artifact_store = FailInternalReportStore(tmp_path / "artifacts")
    run_service, _, _ = service(tmp_path, store=artifact_store)

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is RunFailureCode.ARTIFACT_FAILURE
    assert "private/tmp" not in result.model_dump_json()


def test_restart_reconciliation_fails_queued_run_without_resuming_it(tmp_path: Path) -> None:
    holding = HoldingExecutor()
    first, generator, artifacts = service(
        tmp_path,
        executor=holding,
        id_factory=lambda: "run-abandoned",
    )
    accepted = first.submit(RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a"))
    second, _, _ = service(tmp_path, store=artifacts)

    reconciled = second.reconcile_abandoned_runs()
    result = second.get_run(accepted.run_id)

    assert reconciled == ("run-abandoned",)
    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is RunFailureCode.ABANDONED_ON_RESTART
    assert generator.calls == 0
    assert len(holding.tasks) == 1


def test_concurrent_submissions_receive_distinct_run_ids(tmp_path: Path) -> None:
    ids = iter(("run-one", "run-two"))
    run_service, _, _ = service(tmp_path, executor=HoldingExecutor(), id_factory=lambda: next(ids))

    first = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    second = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )

    assert first.run_id == "run-one"
    assert second.run_id == "run-two"
    assert first.run_id != second.run_id


def test_api_request_models_are_closed_and_frozen() -> None:
    request = RunCreateRequest(
        mode=RunMode.SOLVE_AND_AUDIT,
        problem_id="cf-123-a",
    )

    with pytest.raises(ValidationError, match="Extra inputs"):
        RunCreateRequest.model_validate(
            {
                "mode": "solve_and_audit",
                "problem_id": "cf-123-a",
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError, match="frozen"):
        request.problem_id = "cf-999-z"


def test_ac_with_material_reasoning_error_completes_as_paradox(tmp_path: Path) -> None:
    class ParadoxReviews:
        def review(
            self,
            problem: ProblemRecord,
            oracle: ProblemOracle,
            trace: SolutionTrace,
        ) -> ReviewOutcome:
            def verdict(reviewer_id: str) -> ReviewerVerdict:
                reviews = (
                    StepReview(
                        step_id="s1",
                        status=StepStatus.INCORRECT,
                        material=True,
                        taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
                        evidence="The stated rationale is invalid.",
                        confidence=1.0,
                    ),
                    StepReview(
                        step_id="s2",
                        status=StepStatus.CORRECT,
                        material=False,
                        evidence="The implementation happens to be correct.",
                        confidence=1.0,
                    ),
                )
                return ReviewerVerdict(
                    reviewer_id=reviewer_id,
                    trace_id=trace.trace_id,
                    material_error=True,
                    error_taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
                    first_error_step_id="s1",
                    explanation="Correct result from invalid reasoning.",
                    per_step_reviews=reviews,
                )

            return ReviewOutcome(
                primary=(verdict("logic-reviewer"), verdict("adversarial-reviewer"))
            )

    run_service, _, _ = service(tmp_path, reviews=ParadoxReviews())

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)

    assert result.status is RunStatus.COMPLETED
    assert result.report is not None
    assert result.report.audit["final_correct"] is True
    assert result.report.audit["process_valid"] is False
    assert result.report.audit["final_error_taxonomy"] == "algorithm_logic"


def test_background_executor_runs_in_process_and_can_shutdown() -> None:
    calls: list[str] = []
    executor = InProcessBackgroundExecutor(max_workers=1)

    executor.submit(lambda: calls.append("ran"))
    executor.shutdown()

    assert calls == ["ran"]


def test_nonformal_catalog_object_is_rejected_before_any_run_artifact(tmp_path: Path) -> None:
    bundle = formal_bundle()

    class NonFormalCatalog:
        def get_bundle(self, problem_id: str) -> object:
            return object()

        def list_problems(self) -> tuple[object, ...]:
            return ()

        def get_public_detail(self, problem_id: str) -> dict[str, object]:
            return {}

    artifacts = ArtifactStore(tmp_path / "artifacts")
    run_service = RunService(  # type: ignore[arg-type]
        catalog=NonFormalCatalog(),
        artifacts=artifacts,
        generator=FakeGenerator(bundle.gold_trace),
        judge=FakeJudge(),
        reviews=CleanReviews(),
        executor=SynchronousExecutor(),
    )

    with pytest.raises(ProblemNotFoundError, match="formal"):
        run_service.submit(RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a"))

    assert artifacts.list_json("run-index") == ()


def test_review_failure_is_failed_without_persisting_exception_text(tmp_path: Path) -> None:
    class FailingReviews:
        def review(
            self,
            problem: ProblemRecord,
            oracle: ProblemOracle,
            trace: SolutionTrace,
        ) -> ReviewOutcome:
            raise RuntimeError("reviewer leaked /private/tmp/secret and Bearer key-value")

    run_service, _, artifacts = service(tmp_path, reviews=FailingReviews())

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    result = run_service.get_run(accepted.run_id)
    persisted = "".join(path.read_text(encoding="utf-8") for path in artifacts.root.rglob("*.json"))

    assert result.status is RunStatus.FAILED
    assert result.failure is not None
    assert result.failure.code is RunFailureCode.REVIEW_FAILED
    assert "private/tmp/secret" not in persisted
    assert "key-value" not in persisted
