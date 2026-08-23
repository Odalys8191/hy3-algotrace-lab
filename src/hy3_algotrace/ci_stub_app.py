"""Controlled Docker-CI API fixture; never a formal catalog or model integration."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI

from .app import create_app as create_api_app
from .artifacts import ArtifactStore, sha256_json
from .catalog import ProblemBundle, ProblemCatalog, problem_content_hash
from .config import AppConfig
from .contracts import (
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
    TestCase,
    Topic,
)
from .evaluator import ReviewOutcome
from .executor import SynchronousExecutor
from .run_service import RunService


class _FixtureGenerator:
    def generate(self, problem: ProblemRecord) -> SolutionTrace:
        return _trace(problem.problem_id)


class _FixtureJudge:
    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        del problem, cpp_source
        return JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC)


class _FixtureReviews:
    def review(
        self, problem: ProblemRecord, oracle: ProblemOracle, trace: SolutionTrace
    ) -> ReviewOutcome:
        del problem, oracle
        verdicts = tuple(_clean_verdict(trace, reviewer_id) for reviewer_id in _REVIEWER_IDS)
        return ReviewOutcome(primary=(verdicts[0], verdicts[1]))


_REVIEWER_IDS = ("ci-logic", "ci-adversarial")


def create_app() -> FastAPI:
    """Create an in-process deterministic fixture endpoint for the Docker workflow only."""

    config = AppConfig.from_env()
    bundle = _bundle()
    service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=ArtifactStore(config.artifact_root),
        generator=_FixtureGenerator(),
        judge=_FixtureJudge(),
        reviews=_FixtureReviews(),
        executor=SynchronousExecutor(),
        model_name="ci-controlled-stub",
        code_revision="ci-controlled-stub",
        container_image_digest="sha256:" + "c" * 64,
        clock=lambda: datetime(2026, 8, 23, tzinfo=UTC),
        id_factory=lambda: "ci-run-1",
    )
    return create_api_app(catalog=ProblemCatalog((bundle,)), run_service=service)


def _bundle() -> ProblemBundle:
    reference_cpp = "#include <iostream>\nint main(){long long x;std::cin>>x;std::cout<<x+1;}\n"
    record = ProblemRecord(
        problem_id="cf-123-a",
        title="CI Add One Fixture",
        statement_en="Given one integer, print the integer plus one.",
        source_url="https://codeforces.com/problemset/problem/123/A",
        attribution="CI controlled fixture only; not formal data",
        cf_contest_id=123,
        cf_index="A",
        cf_tags=("greedy",),
        source_split="validation",
        topic=Topic.GREEDY,
        rating=1200,
        time_limit_ms=1000,
        memory_limit_mb=256,
        public_tests=(TestCase(test_id="public", input_data="1\n", expected_output="2\n"),),
        hidden_tests=(TestCase(test_id="hidden", input_data="41\n", expected_output="42\n"),),
        generated_tests=(),
        content_hash="0" * 64,
    )
    record = record.model_copy(update={"content_hash": problem_content_hash(record)})
    return ProblemBundle(
        record=record,
        oracle=ProblemOracle(
            problem_id=record.problem_id,
            accepted_algorithm_families=("arithmetic",),
            key_invariants=("answer is x + 1",),
            complexity_ceiling="O(1)",
            known_traps=("integer parsing",),
            adversarial_cases=("negative values",),
            decisive_facts=("one addition is sufficient",),
            reference_solution_hash=sha256_json(reference_cpp),
        ),
        reference_cpp=reference_cpp,
        gold_trace=_trace(record.problem_id),
    )


def _trace(problem_id: str) -> SolutionTrace:
    return SolutionTrace(
        trace_id="ci-trace-1",
        problem_id=problem_id,
        steps=(
            ReasoningStep(
                step_id="read-input",
                step_number=1,
                stage=ReasoningStage.PROBLEM_UNDERSTANDING,
                claim="Read x.",
                rationale="The fixture input has one integer.",
            ),
            ReasoningStep(
                step_id="print-answer",
                step_number=2,
                stage=ReasoningStage.IMPLEMENTATION,
                claim="Print x plus one.",
                rationale="That is the fixture output.",
                depends_on=("read-input",),
            ),
        ),
        problem_understanding="Read one integer.",
        algorithm="Add one and print.",
        correctness_argument="The output is exactly one greater than the input.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("negative integers",),
        code="#include <iostream>\nint main(){long long x;std::cin>>x;std::cout<<x+1;}",
    )


def _clean_verdict(trace: SolutionTrace, reviewer_id: str) -> ReviewerVerdict:
    return ReviewerVerdict(
        reviewer_id=reviewer_id,
        trace_id=trace.trace_id,
        material_error=False,
        explanation="Controlled CI fixture is internally consistent.",
        per_step_reviews=tuple(
            StepReview(
                step_id=step.step_id,
                status=StepStatus.CORRECT,
                material=False,
                evidence="Controlled CI fixture evidence.",
                confidence=1.0,
            )
            for step in trace.steps
        ),
    )
