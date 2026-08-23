from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from hy3_algotrace.contracts import JudgeStatus, ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase


def _problem(
    *,
    public_tests: tuple[ContractTestCase, ...] = (),
    hidden_tests: tuple[ContractTestCase, ...] = (),
    generated_tests: tuple[ContractTestCase, ...] = (),
    time_limit_ms: int = 1000,
) -> ProblemRecord:
    return ProblemRecord(
        problem_id="cf-1-a",
        title="Double",
        statement_en="Double the integer.",
        source_url="https://codeforces.com/problemset/problem/1/A",
        attribution="Codeforces",
        cf_contest_id=1,
        cf_index="A",
        cf_tags=("implementation",),
        source_split="validation",
        topic=Topic.CONSTRUCTION_SIMULATION,
        rating=1200,
        time_limit_ms=time_limit_ms,
        memory_limit_mb=128,
        public_tests=public_tests,
        hidden_tests=hidden_tests,
        generated_tests=generated_tests,
        content_hash="a" * 64,
    )


class _FakeBackend:
    def __init__(
        self,
        module: Any,
        *,
        compile_status: JudgeStatus = JudgeStatus.AC,
        outcomes: dict[str, Any] | None = None,
        compile_diagnostics: str = "",
    ) -> None:
        self._module = module
        self._compile_status = compile_status
        self._outcomes = outcomes or {}
        self._compile_diagnostics = compile_diagnostics
        self.executed_inputs: list[str] = []
        self.workspace_names: list[str] = []

    def compile(self, *, workspace: Path, memory_limit_mb: int) -> Any:
        assert memory_limit_mb == 128
        assert (workspace / "main.cpp").read_text(encoding="utf-8") == "int main() {}"
        self.workspace_names.append(workspace.name)
        return self._module.CompileOutcome(
            status=self._compile_status,
            diagnostics=self._compile_diagnostics.replace("{workspace}", str(workspace)),
        )

    def execute(
        self,
        *,
        workspace: Path,
        input_dir: Path,
        result_dir: Path,
        memory_limit_mb: int,
        time_limit_ms: int,
        output_limit_bytes: int,
    ) -> Any:
        del result_dir
        assert workspace.name.startswith("hy3-judge-")
        assert memory_limit_mb == 128
        assert time_limit_ms > 0
        assert output_limit_bytes > 0
        input_data = (input_dir / "input.txt").read_text(encoding="utf-8")
        self.executed_inputs.append(input_data)
        outcome = self._outcomes[input_data]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _BrokenBackend:
    def compile(self, *, workspace: Path, memory_limit_mb: int) -> Any:
        del memory_limit_mb
        raise OSError(f"docker failed in {workspace}")


class _BrokenRuntimeBackend:
    def __init__(self, module: Any) -> None:
        self._module = module

    def compile(self, *, workspace: Path, memory_limit_mb: int) -> Any:
        del workspace, memory_limit_mb
        return self._module.CompileOutcome(status=JudgeStatus.AC)

    def execute(self, *, workspace: Path, **kwargs: Any) -> Any:
        del kwargs
        raise OSError(f"runtime docker failed in {workspace}")


class _OverflowRuntimeBackend(_BrokenRuntimeBackend):
    def execute(self, *, workspace: Path, **kwargs: Any) -> Any:
        del workspace, kwargs
        raise OverflowError("runtime limit cannot be represented")


class _BrokenCaseSetupBackend:
    def __init__(self, module: Any) -> None:
        self._module = module

    def compile(self, *, workspace: Path, memory_limit_mb: int) -> Any:
        del memory_limit_mb
        (workspace / "case-0000").write_text("blocks case directory", encoding="utf-8")
        return self._module.CompileOutcome(status=JudgeStatus.AC)

    def execute(self, **kwargs: Any) -> Any:
        del kwargs
        raise AssertionError("execute must not run when case setup fails")


def test_judge_runs_only_hidden_and_generated_tests_for_final_verdict(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    public = ContractTestCase(test_id="public", input_data="1\n", expected_output="2\n")
    hidden = ContractTestCase(test_id="hidden", input_data="2\n", expected_output="4\n")
    generated = ContractTestCase(test_id="generated", input_data="3\n", expected_output="6\n")
    outcomes = {
        "2\n": module.ExecutionOutcome(
            status=JudgeStatus.AC,
            stdout="4   \n",
            time_ms=7,
            memory_kb=2048,
        ),
        "3\n": module.ExecutionOutcome(
            status=JudgeStatus.AC,
            stdout=" 6\n",
            time_ms=8,
            memory_kb=2052,
        ),
    }
    backend = _FakeBackend(module, outcomes=outcomes)

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(
            public_tests=(public,),
            hidden_tests=(hidden,),
            generated_tests=(generated,),
        ),
        "int main() {}",
    )

    assert isinstance(module.DockerJudge(backend=backend), module.Judge)
    assert evidence.compile_status is JudgeStatus.AC
    assert evidence.verdict is JudgeStatus.AC
    assert backend.executed_inputs == ["2\n", "3\n"]
    assert [test.test_id for test in evidence.tests] == ["hidden", "generated"]
    assert [(test.time_ms, test.memory_kb) for test in evidence.tests] == [
        (7, 2048),
        (8, 2052),
    ]
    assert evidence.first_counterexample_input is None
    assert len(backend.workspace_names[0].removeprefix("hy3-judge-")) >= 8


def test_wrong_answer_exposes_safe_input_but_never_hidden_expected_output(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden_expected = "DO_NOT_LEAK_938475\n"
    hidden = ContractTestCase(
        test_id="../../hidden-case",
        input_data="7\x00\n",
        expected_output=hidden_expected,
    )
    backend = _FakeBackend(
        module,
        outcomes={
            "7\x00\n": module.ExecutionOutcome(
                status=JudgeStatus.AC,
                stdout="wrong\n",
                diagnostics=(
                    "\x1b[31m{workspace}/secret\x1b[0m " + hidden_expected
                ),
                time_ms=3,
                memory_kb=1024,
            )
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )
    serialized = evidence.model_dump_json()

    assert evidence.verdict is JudgeStatus.WA
    assert evidence.first_counterexample_input == "7�\n"
    assert evidence.tests[0].counterexample_input == "7�\n"
    assert "DO_NOT_LEAK_938475" not in serialized
    assert str(tmp_path) not in serialized
    assert "\x1b" not in serialized
    assert "expected output" in evidence.tests[0].diagnostics


def test_only_first_failure_exposes_a_counterexample(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = (
        ContractTestCase(test_id="hidden-1", input_data="SECRET_ONE\n", expected_output="1\n"),
        ContractTestCase(test_id="hidden-2", input_data="SECRET_TWO\n", expected_output="2\n"),
    )
    backend = _FakeBackend(
        module,
        outcomes={
            test.input_data: module.ExecutionOutcome(status=JudgeStatus.AC, stdout="wrong\n")
            for test in hidden
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=hidden),
        "int main() {}",
    )
    serialized = evidence.model_dump_json()

    assert evidence.first_counterexample_input == "SECRET_ONE\n"
    assert evidence.tests[0].counterexample_input == "SECRET_ONE\n"
    assert evidence.tests[1].counterexample_input is None
    assert "SECRET_TWO" not in serialized


def test_runtime_stderr_cannot_exfiltrate_hidden_inputs(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = (
        ContractTestCase(test_id="hidden-1", input_data="SECRET_ONE\n", expected_output="1\n"),
        ContractTestCase(test_id="hidden-2", input_data="SECRET_TWO\n", expected_output="2\n"),
    )
    backend = _FakeBackend(
        module,
        outcomes={
            "SECRET_ONE\n": module.ExecutionOutcome(
                status=JudgeStatus.AC,
                stdout="1\n",
                diagnostics="EXFIL:SECRET_ONE\n",
            ),
            "SECRET_TWO\n": module.ExecutionOutcome(
                status=JudgeStatus.AC,
                stdout="2\n",
                diagnostics="EXFIL:SECRET_TWO\n",
            ),
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=hidden),
        "int main() {}",
    )
    serialized = evidence.model_dump_json()

    assert evidence.verdict is JudgeStatus.AC
    assert all(test.diagnostics == "" for test in evidence.tests)
    assert "SECRET_ONE" not in serialized
    assert "SECRET_TWO" not in serialized


@pytest.mark.parametrize(
    ("runtime_status", "expected_verdict"),
    [
        (JudgeStatus.TLE, JudgeStatus.TLE),
        (JudgeStatus.RUNTIME_ERROR, JudgeStatus.RUNTIME_ERROR),
        (JudgeStatus.OUTPUT_LIMIT, JudgeStatus.OUTPUT_LIMIT),
    ],
)
def test_runtime_failures_are_preserved_in_per_test_evidence(
    tmp_path: Path,
    runtime_status: JudgeStatus,
    expected_verdict: JudgeStatus,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="9\n", expected_output="18\n")
    backend = _FakeBackend(
        module,
        outcomes={
            "9\n": module.ExecutionOutcome(
                status=runtime_status,
                diagnostics="runtime failed",
                time_ms=1000,
                memory_kb=4096,
            )
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.verdict is expected_verdict
    assert evidence.tests[0].status is expected_verdict
    assert evidence.tests[0].time_ms == 1000
    assert evidence.tests[0].memory_kb == 4096
    assert evidence.tests[0].counterexample_input == "9\n"


def test_compile_error_is_sanitized_and_does_not_run_tests(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="9\n", expected_output="18\n")
    backend = _FakeBackend(
        module,
        compile_status=JudgeStatus.COMPILE_ERROR,
        compile_diagnostics="\x1b[31m{workspace}/main.cpp: error\x1b[0m",
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.COMPILE_ERROR
    assert evidence.verdict is JudgeStatus.COMPILE_ERROR
    assert evidence.tests == ()
    assert evidence.diagnostics == "<sandbox>/main.cpp: error"
    assert backend.executed_inputs == []


def test_missing_final_tests_fails_closed_without_compiling(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    backend = _FakeBackend(module)

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.NOT_RUN
    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.tests == ()
    assert "hidden or generated" in evidence.diagnostics
    assert backend.workspace_names == []


def test_backend_failure_returns_sanitized_infrastructure_evidence(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="9\n", expected_output="18\n")

    evidence = module.DockerJudge(backend=_BrokenBackend(), temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.tests == ()
    assert str(tmp_path) not in evidence.diagnostics
    assert "docker failed" in evidence.diagnostics


def test_runtime_backend_failure_has_no_false_counterexample(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="9\n", expected_output="18\n")

    evidence = module.DockerJudge(
        backend=_BrokenRuntimeBackend(module), temp_root=tmp_path
    ).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.AC
    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.first_counterexample_input is None
    assert evidence.tests[0].counterexample_input is None
    assert str(tmp_path) not in evidence.diagnostics
    assert "runtime docker failed" in evidence.diagnostics


def test_any_runtime_infrastructure_error_dominates_an_earlier_wa(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = (
        ContractTestCase(test_id="hidden-1", input_data="1\n", expected_output="2\n"),
        ContractTestCase(test_id="hidden-2", input_data="2\n", expected_output="4\n"),
    )
    backend = _FakeBackend(
        module,
        outcomes={
            "1\n": module.ExecutionOutcome(status=JudgeStatus.AC, stdout="wrong\n"),
            "2\n": OSError("docker daemon disappeared"),
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=hidden),
        "int main() {}",
    )

    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.first_counterexample_input is None
    assert evidence.diagnostics == "docker daemon disappeared"


def test_invalid_temp_root_fails_closed_as_infrastructure_evidence(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")
    missing_root = tmp_path / "missing"

    evidence = module.DockerJudge(temp_root=missing_root).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.tests == ()
    assert str(tmp_path) not in evidence.diagnostics


def test_runtime_arithmetic_failure_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")

    evidence = module.DockerJudge(
        backend=_OverflowRuntimeBackend(module), temp_root=tmp_path
    ).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.first_counterexample_input is None
    assert evidence.diagnostics == "runtime limit cannot be represented"


def test_symlink_loop_temp_root_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.symlink_to(second, target_is_directory=True)
    second.symlink_to(first, target_is_directory=True)

    evidence = module.DockerJudge(temp_root=first).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.tests == ()
    assert str(tmp_path) not in evidence.diagnostics


def test_per_test_workspace_setup_failure_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")

    evidence = module.DockerJudge(
        backend=_BrokenCaseSetupBackend(module), temp_root=tmp_path
    ).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.first_counterexample_input is None
    assert str(tmp_path) not in evidence.diagnostics


def test_pydantic_evidence_validation_failure_is_fixed_infrastructure_error(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")
    backend = _FakeBackend(
        module,
        outcomes={
            "1\n": module.ExecutionOutcome(
                status=JudgeStatus.AC,
                stdout="2\n",
                time_ms=-1,
                memory_kb=-1,
            )
        },
    )

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.first_counterexample_input is None
    assert evidence.tests[0].diagnostics == "Trusted runtime metadata is invalid or missing."


def test_any_pydantic_judge_construction_failure_is_fixed_infrastructure_error(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    hidden = ContractTestCase(test_id="hidden", input_data="1\n", expected_output="2\n")
    backend = _FakeBackend(module, compile_status="forged-status")

    evidence = module.DockerJudge(backend=backend, temp_root=tmp_path).judge(
        _problem(hidden_tests=(hidden,)),
        "int main() {}",
    )

    assert evidence.compile_status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
    assert evidence.tests == ()
    assert evidence.diagnostics == "Trusted runtime metadata is invalid or missing."
