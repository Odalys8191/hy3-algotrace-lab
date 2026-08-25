from __future__ import annotations

from dataclasses import dataclass

import pytest

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.catalog import problem_content_hash
from hy3_algotrace.contracts import (
    JudgeEvidence,
    JudgeStatus,
    ProblemRecord,
    Topic,
)
from hy3_algotrace.contracts import (
    TestCase as ContractTestCase,
)
from hy3_algotrace.differential import (
    DifferentialCase,
    DifferentialDataError,
    DifferentialExecution,
    DifferentialExecutionStatus,
    DifferentialStatus,
    JudgeCaseKind,
    JudgeSourceCase,
    run_differential_tests,
    validate_judge_cases,
)


def _problem() -> ProblemRecord:
    provisional = ProblemRecord(
        problem_id="cf-6000-a",
        title="Identity",
        statement_en="Print the input integer.",
        source_url="https://codeforces.com/problemset/problem/6000/A",
        attribution="Codeforces; CodeContests validation split.",
        cf_contest_id=6000,
        cf_index="A",
        cf_tags=("greedy",),
        source_split="validation",
        topic=Topic.GREEDY,
        rating=1400,
        time_limit_ms=1000,
        memory_limit_mb=256,
        public_tests=(
            ContractTestCase(test_id="public-1", input_data="1\n", expected_output="1\n"),
        ),
        hidden_tests=(
            ContractTestCase(test_id="hidden-1", input_data="2\n", expected_output="2\n"),
        ),
        generated_tests=(
            ContractTestCase(test_id="generated-1", input_data="3\n", expected_output="3\n"),
        ),
        content_hash="0" * 64,
    )
    return provisional.model_copy(update={"content_hash": problem_content_hash(provisional)})


@dataclass
class _SemanticJudge:
    calls: list[str]

    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        self.calls.append(f"{problem.problem_id}:{cpp_source}")
        verdict = JudgeStatus.WA if "mutant" in cpp_source else JudgeStatus.AC
        return JudgeEvidence(compile_status=JudgeStatus.AC, verdict=verdict)


def test_injected_judge_requires_gold_and_paradox_ac_and_mutant_runtime_failure() -> None:
    """Accepting a mutant or rejecting a paradox must fail the formal source audit."""

    problem = _problem()
    cases = (
        JudgeSourceCase(
            case_id="gold",
            kind=JudgeCaseKind.GOLD,
            problem=problem,
            cpp_source="// gold",
        ),
        JudgeSourceCase(
            case_id="mutant",
            kind=JudgeCaseKind.MUTANT,
            problem=problem,
            cpp_source="// mutant",
        ),
        JudgeSourceCase(
            case_id="paradox",
            kind=JudgeCaseKind.PARADOX,
            problem=problem,
            cpp_source="// paradox",
        ),
    )
    judge = _SemanticJudge(calls=[])

    report = validate_judge_cases(cases, judge=judge)

    assert [(result.case_id, result.verdict) for result in report.results] == [
        ("gold", JudgeStatus.AC),
        ("mutant", JudgeStatus.WA),
        ("paradox", JudgeStatus.AC),
    ]
    assert report.counts == {"gold": 1, "mutant": 1, "paradox": 1}
    assert len(judge.calls) == 3

    accepting = _SemanticJudge(calls=[])
    with pytest.raises(DifferentialDataError, match="mutant.*must fail"):
        validate_judge_cases(
            (cases[1].model_copy(update={"cpp_source": "// accidentally accepted"}),),
            judge=accepting,
        )


def test_infrastructure_or_compile_only_mutant_is_not_dataset_evidence() -> None:
    """Infrastructure and compile failures cannot satisfy semantic mutant validation."""

    problem = _problem()

    @dataclass
    class BrokenJudge:
        evidence: JudgeEvidence

        def judge(self, _problem: ProblemRecord, _cpp_source: str) -> JudgeEvidence:
            return self.evidence

    case = JudgeSourceCase(
        case_id="mutant",
        kind=JudgeCaseKind.MUTANT,
        problem=problem,
        cpp_source="// mutant",
    )
    with pytest.raises(DifferentialDataError, match="infrastructure"):
        validate_judge_cases(
            (case,),
            judge=BrokenJudge(
                JudgeEvidence(
                    compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
                    verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                )
            ),
        )
    with pytest.raises(DifferentialDataError, match="compile"):
        validate_judge_cases(
            (case,),
            judge=BrokenJudge(
                JudgeEvidence(
                    compile_status=JudgeStatus.COMPILE_ERROR,
                    verdict=JudgeStatus.COMPILE_ERROR,
                )
            ),
        )


@dataclass
class _Runner:
    outputs: dict[str, str]

    def run(
        self,
        cpp_source: str,
        input_data: str,
        *,
        time_limit_ms: int,
        memory_limit_mb: int,
    ) -> DifferentialExecution:
        assert sha256_json(cpp_source)
        assert time_limit_ms == 1000
        assert memory_limit_mb == 256
        return DifferentialExecution(
            status=DifferentialExecutionStatus.COMPLETED,
            stdout=self.outputs[input_data],
        )


def test_differential_interface_reports_hash_only_mismatch_and_uses_judge_whitespace() -> None:
    """A real runner mismatch must be visible without persisting raw adversarial I/O."""

    cases = (
        DifferentialCase(test_id="diff-1", input_data="1\n", expected_output="1\n"),
        DifferentialCase(test_id="diff-2", input_data="2\n", expected_output="2\n"),
    )
    runner = _Runner(outputs={"1\n": " 1 \n", "2\n": "wrong\n"})

    report = run_differential_tests(
        problem_id="cf-6000-a",
        reference_cpp="// reference",
        cases=cases,
        runner=runner,
        time_limit_ms=1000,
        memory_limit_mb=256,
    )

    assert report.status is DifferentialStatus.MISMATCH
    assert [result.matched for result in report.results] == [True, False]
    serialized = report.model_dump_json()
    assert "wrong" not in serialized
    assert "input_data" not in serialized
    assert report.results[1].actual_output_hash == sha256_json("wrong\n")


def test_differential_interface_rejects_duplicate_cases_and_runner_failure() -> None:
    """Duplicate IDs and execution errors cannot produce a passing differential report."""

    duplicate = DifferentialCase(test_id="same", input_data="1\n", expected_output="1\n")
    with pytest.raises(DifferentialDataError, match="unique"):
        run_differential_tests(
            problem_id="cf-6000-a",
            reference_cpp="// reference",
            cases=(duplicate, duplicate),
            runner=_Runner(outputs={"1\n": "1\n"}),
            time_limit_ms=1000,
            memory_limit_mb=256,
        )

    class FailedRunner:
        def run(
            self,
            cpp_source: str,
            input_data: str,
            *,
            time_limit_ms: int,
            memory_limit_mb: int,
        ) -> DifferentialExecution:
            return DifferentialExecution(
                status=DifferentialExecutionStatus.RUNTIME_ERROR,
                stdout="",
                diagnostics="RAW_RUNNER_SECRET_DO_NOT_PRINT",
            )

    with pytest.raises(DifferentialDataError, match="runner failed") as captured:
        run_differential_tests(
            problem_id="cf-6000-a",
            reference_cpp="// reference",
            cases=(duplicate,),
            runner=FailedRunner(),
            time_limit_ms=1000,
            memory_limit_mb=256,
        )
    assert str(captured.value) == "differential runner failed for same"
    assert "RAW_RUNNER_SECRET_DO_NOT_PRINT" not in str(captured.value)
