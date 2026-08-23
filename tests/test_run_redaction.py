from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_run_service import FakeGenerator, formal_bundle, valid_trace

from hy3_algotrace.api_models import RunCreateRequest, RunMode
from hy3_algotrace.artifacts import ArtifactStore, UnsafeArtifactPathError
from hy3_algotrace.catalog import ProblemCatalog
from hy3_algotrace.contracts import (
    JudgeEvidence,
    JudgeStatus,
    ProblemOracle,
    ProblemRecord,
    ReviewerVerdict,
    SolutionTrace,
    StepReview,
    StepStatus,
)
from hy3_algotrace.evaluator import EvidenceFusion, ReviewOutcome
from hy3_algotrace.executor import SynchronousExecutor
from hy3_algotrace.rules import RuleEngine
from hy3_algotrace.run_service import RunService

API_KEY = "sk-live-123456789-secret"
ABSOLUTE_PATH = "/private/tmp/judge-workspace/solution.cpp"


class EchoingJudge:
    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        return JudgeEvidence(
            compile_status=JudgeStatus.AC,
            verdict=JudgeStatus.WA,
            diagnostics=f"Bearer {API_KEY} at {ABSOLUTE_PATH}",
            first_counterexample_input=problem.hidden_tests[0].input_data,
        )


class EchoingReviews:
    def review(
        self, problem: ProblemRecord, oracle: ProblemOracle, trace: SolutionTrace
    ) -> ReviewOutcome:
        protected_echo = " | ".join(
            (
                problem.hidden_tests[0].input_data,
                problem.hidden_tests[0].expected_output,
                oracle.decisive_facts[0],
                f"Bearer {API_KEY}",
                ABSOLUTE_PATH,
            )
        )

        def verdict(reviewer_id: str) -> ReviewerVerdict:
            return ReviewerVerdict(
                reviewer_id=reviewer_id,
                trace_id=trace.trace_id,
                material_error=False,
                explanation=protected_echo,
                per_step_reviews=tuple(
                    StepReview(
                        step_id=step.step_id,
                        status=StepStatus.CORRECT,
                        material=False,
                        evidence=protected_echo,
                        confidence=1.0,
                    )
                    for step in trace.steps
                ),
            )

        return ReviewOutcome(primary=(verdict("logic-reviewer"), verdict("adversarial-reviewer")))


def _walk(value: Any):  # type: ignore[no-untyped-def]
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)
    elif isinstance(value, str):
        yield value


def test_public_report_recursively_removes_protected_fields_values_and_paths(
    tmp_path: Path,
) -> None:
    bundle = formal_bundle()
    trace = valid_trace().model_copy(
        update={
            "algorithm": (
                f"Reviewer saw {bundle.oracle.decisive_facts[0]} at {ABSOLUTE_PATH} "
                f"using Bearer {API_KEY}"
            )
        }
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    run_service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=artifacts,
        generator=FakeGenerator(trace),
        judge=EchoingJudge(),
        reviews=EchoingReviews(),
        rules=RuleEngine(),
        fusion=EvidenceFusion(),
        executor=SynchronousExecutor(),
        id_factory=lambda: "run-redacted",
    )

    accepted = run_service.submit(
        RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
    )
    public = run_service.get_run(accepted.run_id)
    internal = run_service.get_internal_report(accepted.run_id)

    assert public.report is not None
    serialized = json.dumps(public.report.model_dump(mode="json"), sort_keys=True)
    lowered = serialized.lower()
    for forbidden_key in (
        "hidden_tests",
        "generated_tests",
        "expected_output",
        "oracle",
        "reference_cpp",
        "api_key",
    ):
        assert forbidden_key not in (item.lower() for item in _walk(public.report.model_dump()))
    for protected in (
        bundle.record.hidden_tests[0].input_data,
        bundle.record.hidden_tests[0].expected_output,
        bundle.record.generated_tests[0].input_data,
        bundle.record.generated_tests[0].expected_output,
        bundle.oracle.decisive_facts[0],
        bundle.reference_cpp,
        API_KEY,
        ABSOLUTE_PATH,
    ):
        assert protected not in serialized
    assert "bearer sk-" not in lowered
    assert internal.trace.trace_id == trace.trace_id
    assert len(internal.audit_report.reviewer_verdicts) == 2
    assert API_KEY not in "".join(
        path.read_text(encoding="utf-8") for path in artifacts.root.rglob("*.json")
    )


def test_problem_detail_redaction_is_recursive_even_for_malicious_catalog_data(
    tmp_path: Path,
) -> None:
    bundle = formal_bundle()
    run_service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=ArtifactStore(tmp_path / "artifacts"),
        generator=FakeGenerator(bundle.gold_trace),
        judge=EchoingJudge(),
        reviews=EchoingReviews(),
        executor=SynchronousExecutor(),
    )

    detail = run_service.get_public_problem("cf-123-a")
    serialized = json.dumps(detail, sort_keys=True)

    assert bundle.record.hidden_tests[0].input_data not in serialized
    assert bundle.record.hidden_tests[0].expected_output not in serialized
    assert bundle.oracle.decisive_facts[0] not in serialized


def test_run_enumeration_never_follows_a_symlink(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    artifacts.write_json("run-index/good.json", {"run_id": "good"})
    outside = tmp_path / "outside.json"
    outside.write_text('{"run_id":"evil"}', encoding="utf-8")
    (artifacts.root / "run-index" / "evil.json").symlink_to(outside)

    with pytest.raises(UnsafeArtifactPathError, match="unsafe"):
        artifacts.list_json("run-index")
