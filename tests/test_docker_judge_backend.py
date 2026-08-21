from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

import pytest

from hy3_algotrace.contracts import JudgeStatus


class _StubExecutor:
    def __init__(self, results: list[Any]) -> None:
        self._results = iter(results)
        self.commands: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []

    def run(self, command: tuple[str, ...], *, timeout_seconds: float) -> Any:
        self.commands.append(command)
        self.timeouts.append(timeout_seconds)
        return next(self._results)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "hy3-judge-unit"
    workspace.mkdir()
    (workspace / "main.cpp").write_text("int main() {}", encoding="utf-8")
    return workspace


def test_compile_maps_compiler_and_docker_failures_without_host_execution(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            module.DockerProcessResult(return_code=0),
            module.DockerProcessResult(return_code=1, stderr="main.cpp: error"),
            module.DockerProcessResult(return_code=125, stderr="daemon unavailable"),
        ]
    )
    backend = module.DockerCliBackend(executor=executor)
    workspace = _workspace(tmp_path)

    accepted = backend.compile(workspace=workspace, memory_limit_mb=128)
    compiler_error = backend.compile(workspace=workspace, memory_limit_mb=128)
    infrastructure_error = backend.compile(workspace=workspace, memory_limit_mb=128)

    assert accepted.status is JudgeStatus.AC
    assert compiler_error.status is JudgeStatus.COMPILE_ERROR
    assert compiler_error.diagnostics == "main.cpp: error"
    assert infrastructure_error.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert all(command[0:2] == ("docker", "run") for command in executor.commands)
    assert all(
        "int main()" not in argument
        for command in executor.commands
        for argument in command
    )
    names = [
        next(argument for argument in command if argument.startswith("--name="))
        for command in executor.commands
    ]
    assert len(set(names)) == 3
    assert all(re.fullmatch(r"--name=hy3-judge-[0-9a-f]{16}", name) for name in names)


@pytest.mark.parametrize(
    ("exit_status", "expected_status"),
    [
        (0, JudgeStatus.AC),
        (124, JudgeStatus.TLE),
        (153, JudgeStatus.OUTPUT_LIMIT),
        (137, JudgeStatus.MLE),
        (139, JudgeStatus.RUNTIME_ERROR),
    ],
)
def test_runtime_status_and_resource_metadata_come_from_container_results(
    tmp_path: Path,
    exit_status: int,
    expected_status: JudgeStatus,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor([module.DockerProcessResult(return_code=0)])
    backend = module.DockerCliBackend(executor=executor)
    workspace = _workspace(tmp_path)
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    input_dir.mkdir()
    result_dir.mkdir()
    (input_dir / "input.txt").write_text("3\n", encoding="utf-8")
    (result_dir / "status.txt").write_text(str(exit_status), encoding="ascii")
    (result_dir / "output.txt").write_text("6\n", encoding="utf-8")
    (result_dir / "diagnostics.txt").write_text("program diagnostic", encoding="utf-8")
    (result_dir / "metrics.txt").write_text("0.007 2345\n", encoding="ascii")

    outcome = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is expected_status
    assert outcome.stdout == "6\n"
    assert outcome.diagnostics == "program diagnostic"
    assert outcome.time_ms == 7
    assert outcome.memory_kb == 2345
    assert executor.timeouts == [2.25]
    assert executor.commands[0][-8:] == (
        "run",
        "/workspace/main",
        "/input/input.txt",
        "/result/output.txt",
        "/result/diagnostics.txt",
        "/result/metrics.txt",
        "/result/status.txt",
        "0.250",
    )


def test_host_side_safety_timeout_is_tle_and_missing_results_fail_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            module.DockerProcessResult(return_code=124, timed_out=True),
            module.DockerProcessResult(return_code=0),
        ]
    )
    backend = module.DockerCliBackend(executor=executor)
    workspace = _workspace(tmp_path)
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    input_dir.mkdir()
    result_dir.mkdir()
    (input_dir / "input.txt").write_text("3\n", encoding="utf-8")

    timed_out = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=100,
        output_limit_bytes=4096,
    )
    missing = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=100,
        output_limit_bytes=4096,
    )

    assert timed_out.status is JudgeStatus.TLE
    assert "safety timeout" in timed_out.diagnostics
    assert missing.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert "result metadata" in missing.diagnostics


def test_docker_oom_exit_is_reported_as_memory_limit(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [module.DockerProcessResult(return_code=137, stderr="Killed")]
    )
    backend = module.DockerCliBackend(executor=executor)
    workspace = _workspace(tmp_path)
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    input_dir.mkdir()
    result_dir.mkdir()
    (input_dir / "input.txt").write_text("3\n", encoding="utf-8")

    outcome = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=16,
        time_limit_ms=100,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.MLE
    assert outcome.diagnostics == "Killed"
