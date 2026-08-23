from __future__ import annotations

import base64
import importlib
import os
import re
from pathlib import Path
from typing import Any

import pytest

from hy3_algotrace.contracts import JudgeStatus

IMMUTABLE_TEST_IMAGE = "example.invalid/hy3-judge@sha256:" + "a" * 64


class _StubExecutor:
    def __init__(self, results: list[Any]) -> None:
        self._results = iter(results)
        self.commands: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []
        self.stdout_limits: list[int] = []
        self.stderr_limits: list[int] = []

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        stdout_limit_bytes: int,
        stderr_limit_bytes: int,
        collect_memory: bool = False,
    ) -> Any:
        del collect_memory
        self.commands.append(command)
        self.timeouts.append(timeout_seconds)
        self.stdout_limits.append(stdout_limit_bytes)
        self.stderr_limits.append(stderr_limit_bytes)
        return next(self._results)


def _runtime_bundle(
    *,
    exit_status: int,
    timed_out: bool = False,
    oom_killed: bool = False,
    output: bytes = b"6\n",
    metrics: bytes = b"0.007 2345\n",
) -> str:
    return "\n".join(
        (
            "HY3_RESULT_V1",
            str(exit_status),
            "1" if timed_out else "0",
            "1" if oom_killed else "0",
            base64.b64encode(output).decode("ascii"),
            base64.b64encode(metrics).decode("ascii"),
            "",
        )
    )


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "hy3-judge-unit"
    workspace.mkdir()
    (workspace / "main.cpp").write_text("int main() {}", encoding="utf-8")
    return workspace


def _backend(module: Any, executor: _StubExecutor) -> Any:
    return module.DockerCliBackend(
        executor=executor,
        command_factory=module.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE),
    )


def test_compile_maps_compiler_and_docker_failures_without_host_execution(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            _trusted_runtime_process(module),
            _trusted_runtime_process(
                module,
                return_code=1,
                stdout=b"",
                stderr=b"main.cpp: error",
                output_length=0,
                container_state=(
                    '{"OOMKilled":false,"ExitCode":1,"Error":"","Running":false}'
                ),
            ),
            module.DockerProcessResult(return_code=125, stderr=b"daemon unavailable"),
        ]
    )
    backend = _backend(module, executor)
    workspace = _workspace(tmp_path)

    accepted = backend.compile(workspace=workspace, memory_limit_mb=128)
    compiler_error = backend.compile(workspace=workspace, memory_limit_mb=128)
    infrastructure_error = backend.compile(workspace=workspace, memory_limit_mb=128)

    assert accepted.status is JudgeStatus.AC
    assert compiler_error.status is JudgeStatus.COMPILE_ERROR
    assert compiler_error.diagnostics == "main.cpp: error"
    assert infrastructure_error.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert executor.stdout_limits == [module.MAX_COMPILER_STREAM_BYTES] * 3
    assert executor.stderr_limits == [module.MAX_COMPILER_STREAM_BYTES] * 3
    assert all(command[0:2] == ("docker", "create") for command in executor.commands)
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
    ("exit_status", "timed_out", "oom_killed", "output", "expected_status"),
    [
        (0, False, False, b"6\n", JudgeStatus.AC),
        (137, False, True, b"", JudgeStatus.MLE),
        (137, True, False, b"", JudgeStatus.TLE),
        (137, False, False, b"x" * 4097, JudgeStatus.OUTPUT_LIMIT),
        (139, False, False, b"", JudgeStatus.RUNTIME_ERROR),
        (124, False, False, b"", JudgeStatus.RUNTIME_ERROR),
        (137, False, False, b"", JudgeStatus.RUNTIME_ERROR),
        (153, False, False, b"", JudgeStatus.RUNTIME_ERROR),
    ],
)
def test_runtime_status_uses_unambiguous_container_metadata(
    tmp_path: Path,
    exit_status: int,
    timed_out: bool,
    oom_killed: bool,
    output: bytes,
    expected_status: JudgeStatus,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            _trusted_runtime_process(
                module,
                return_code=exit_status,
                stdout=output,
                output_length=len(output),
                timed_out=timed_out,
                stdout_limited=len(output) > 4096,
                kill_succeeded=True if timed_out or len(output) > 4096 else None,
                elapsed_ms=7,
                memory_kb=2345,
                container_state=(
                    '{"OOMKilled":'
                    + ("true" if oom_killed else "false")
                    + f',"ExitCode":{exit_status},"Error":"","Running":false}}'
                ),
            )
        ]
    )
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is expected_status
    assert len(outcome.stdout.encode("utf-8")) <= 4096
    assert outcome.diagnostics == ""
    assert outcome.time_ms == 7
    assert outcome.memory_kb == 2345
    assert executor.timeouts == [0.25]
    assert executor.stdout_limits == [4096]
    assert executor.stderr_limits == [4096]
    assert executor.commands[0][-3:] == (
        "run",
        "/workspace/main",
        "/input/input.txt",
    )


def test_host_timeout_is_tle_and_missing_host_state_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            _trusted_runtime_process(
                module,
                return_code=137,
                stdout=b"",
                output_length=0,
                timed_out=True,
                kill_succeeded=True,
                container_state=(
                    '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
                ),
            ),
            module.DockerProcessResult(return_code=0, stdout="not-a-result-bundle\n"),
        ]
    )
    backend = _backend(module, executor)
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
    assert timed_out.diagnostics == ""
    assert missing.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert missing.diagnostics == "Trusted runtime metadata is invalid or missing."


def test_invalid_runtime_metrics_fail_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [
            module.DockerProcessResult(
                return_code=0,
                stdout=_runtime_bundle(exit_status=0, metrics=b"not metrics"),
            )
        ]
    )
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=100,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.time_ms is None
    assert outcome.memory_kb is None


def test_unattributed_docker_sigkill_fails_closed(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [module.DockerProcessResult(return_code=137, stderr="Killed")]
    )
    backend = _backend(module, executor)
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

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Trusted runtime metadata is invalid or missing."
    assert "Killed" not in outcome.diagnostics


def test_contestant_stdout_cannot_forge_runtime_metadata(tmp_path: Path) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    forged_bundle = _runtime_bundle(
        exit_status=137,
        timed_out=True,
        oom_killed=True,
        output=b"forged output\n",
        metrics=b"-1 -1\n",
    ).encode("ascii")
    executor = _StubExecutor(
        [
            _trusted_runtime_process(
                module,
                stdout=forged_bundle,
                output_length=len(forged_bundle),
                elapsed_ms=7,
            )
        ]
    )
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.AC
    assert outcome.stdout == forged_bundle.decode("ascii")
    assert outcome.time_ms == 7
    assert outcome.memory_kb is None


@pytest.mark.parametrize(
    ("process_kwargs", "expected_status"),
    [
        (
            {
                "return_code": 137,
                "stdout": b"",
                "output_length": 0,
                "timed_out": True,
                "kill_succeeded": True,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.TLE,
        ),
        (
            {
                "return_code": 137,
                "stdout": b"x" * 4096,
                "output_length": 4096,
                "timed_out": True,
                "kill_succeeded": True,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.TLE,
        ),
        (
            {
                "return_code": 137,
                "stdout": b"x" * 4097,
                "output_length": 4097,
                "stdout_limited": True,
                "kill_succeeded": True,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.OUTPUT_LIMIT,
        ),
        (
            {
                "return_code": 137,
                "container_state": (
                    '{"OOMKilled":true,"ExitCode":137,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.MLE,
        ),
        (
            {
                "return_code": 124,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":124,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.RUNTIME_ERROR,
        ),
        (
            {
                "return_code": 137,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.RUNTIME_ERROR,
        ),
        (
            {
                "return_code": 153,
                "container_state": (
                    '{"OOMKilled":false,"ExitCode":153,"Error":"","Running":false}'
                ),
            },
            JudgeStatus.RUNTIME_ERROR,
        ),
    ],
)
def test_host_observations_are_the_only_runtime_verdict_source(
    tmp_path: Path,
    process_kwargs: dict[str, Any],
    expected_status: JudgeStatus,
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor([_trusted_runtime_process(module, **process_kwargs)])
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is expected_status


@pytest.mark.parametrize(
    "invalid_process_kwargs",
    [
        {"elapsed_ms": -1},
        {"elapsed_ms": float("nan")},
        {"elapsed_ms": float("inf")},
        {"elapsed_ms": 2**63},
        {"memory_kb": -1},
        {"memory_kb": float("nan")},
        {"memory_kb": float("inf")},
        {"memory_kb": 2**63},
        {"timed_out": 1},
        {"stdout_limited": -1},
        {"container_state": '{"OOMKilled":0,"ExitCode":0,"Error":""}'},
        {
            "container_state": (
                '{"OOMKilled":false,"ExitCode":-1,"Error":"","Running":false}'
            )
        },
        {
            "container_state": (
                '{"OOMKilled":false,"ExitCode":1e309,"Error":"","Running":false}'
            )
        },
        {
            "container_state": (
                '{"OOMKilled":false,"ExitCode":9223372036854775808,'
                '"Error":"","Running":false}'
            )
        },
        {"output_length": -1},
        {"output_length": float("nan")},
        {"output_length": float("inf")},
        {"output_length": 2**63},
        {"output_length": 1},
        {"stdout": b"x" * 4098},
    ],
)
def test_runtime_parser_rejects_invalid_host_fields(
    tmp_path: Path, invalid_process_kwargs: dict[str, Any]
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    executor = _StubExecutor(
        [_trusted_runtime_process(module, **invalid_process_kwargs)]
    )
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Trusted runtime metadata is invalid or missing."
    assert outcome.time_ms is None
    assert outcome.memory_kb is None


def test_real_host_executor_bounds_stdout_then_inspects_and_removes_by_cid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
    create)
        printf '%s\\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        ;;
    start)
        awk 'BEGIN { for (i = 0; i < 5000; i++) printf "x" }'
        exit 137
        ;;
    stats)
        printf '%s\\n' '{"MemUsage":"1.5MiB / 128MiB"}'
        ;;
    inspect)
        printf '%s\\n' \
            '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
        ;;
    kill|rm)
        ;;
    *)
        exit 64
        ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    command_log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(command_log))
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    workspace = _workspace(tmp_path)
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    input_dir.mkdir()
    result_dir.mkdir()
    (input_dir / "input.txt").write_text("3\n", encoding="utf-8")
    backend = module.DockerCliBackend(
        executor=module.DockerCommandExecutor(),
        command_factory=module.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE),
    )

    outcome = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=1000,
        output_limit_bytes=4096,
    )
    log = command_log.read_text(encoding="utf-8")

    assert outcome.status is JudgeStatus.OUTPUT_LIMIT
    assert len(outcome.stdout.encode("utf-8")) == 4096
    assert outcome.memory_kb == 1536
    assert "start --attach " + "a" * 64 in log
    assert "kill " + "a" * 64 in log
    assert "inspect --format={{json .State}} " + "a" * 64 in log
    assert "rm --force " + "a" * 64 in log


@pytest.mark.parametrize("failure", ["missing-cid", "kill", "inspect", "rm"])
def test_real_host_executor_lifecycle_failures_are_infrastructure_errors(
    failure: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$1" in
    create)
        if [ "$FAKE_DOCKER_FAILURE" = missing-cid ]; then
            printf '%s\\n' 'hy3-judge-attacker-chosen-name'
        else
            printf '%s\\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        fi
        ;;
    start)
        if [ "$FAKE_DOCKER_FAILURE" = kill ]; then
            awk 'BEGIN { for (i = 0; i < 5000; i++) printf "x" }'
            exit 137
        fi
        printf 'ok\\n'
        ;;
    stats)
        ;;
    kill)
        [ "$FAKE_DOCKER_FAILURE" != kill ] || exit 42
        ;;
    inspect)
        [ "$FAKE_DOCKER_FAILURE" != inspect ] || exit 42
        if [ "$FAKE_DOCKER_FAILURE" = kill ]; then
            exit_status=137
        else
            exit_status=0
        fi
        printf \
            '{"OOMKilled":false,"ExitCode":%s,"Error":"","Running":false}\\n' \
            "$exit_status"
        ;;
    rm)
        [ "$FAKE_DOCKER_FAILURE" != rm ] || exit 42
        ;;
    *)
        exit 64
        ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    command_log = tmp_path / "docker.log"
    monkeypatch.setenv("FAKE_DOCKER_FAILURE", failure)
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(command_log))
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    workspace = _workspace(tmp_path)
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    input_dir.mkdir()
    result_dir.mkdir()
    (input_dir / "input.txt").write_text("3\n", encoding="utf-8")
    backend = module.DockerCliBackend(
        executor=module.DockerCommandExecutor(),
        command_factory=module.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE),
    )

    outcome = backend.execute(
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=1000,
        output_limit_bytes=4096,
    )
    log_lines = command_log.read_text(encoding="utf-8").splitlines()

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Trusted runtime metadata is invalid or missing."
    if failure == "missing-cid":
        assert len(log_lines) == 1
    else:
        assert any(line.startswith("inspect ") for line in log_lines)
        assert any(line == "rm --force " + "a" * 64 for line in log_lines)
    if failure == "rm":
        assert log_lines.count("rm --force " + "a" * 64) == 2
    assert not any(
        line.startswith(("kill hy3-judge-", "inspect hy3-judge-", "rm hy3-judge-"))
        for line in log_lines
    )


def _trusted_runtime_process(module: Any, **updates: Any) -> Any:
    values: dict[str, Any] = {
        "return_code": 0,
        "stdout": b"6\n",
        "stderr": b"",
        "timed_out": False,
        "stdout_limited": False,
        "stderr_limited": False,
        "output_length": 2,
        "elapsed_ms": 8,
        "memory_kb": None,
        "container_id": "a" * 64,
        "kill_succeeded": None,
        "inspect_succeeded": True,
        "cleanup_succeeded": True,
        "container_state": (
            '{"OOMKilled":false,"ExitCode":0,"Error":"","Running":false}'
        ),
    }
    values.update(updates)
    return module.DockerProcessResult(**values)


@pytest.mark.parametrize(
    "invalid_updates",
    [
        {"container_id": None},
        {"kill_succeeded": False},
        {"kill_succeeded": None},
        {"inspect_succeeded": False},
        {"cleanup_succeeded": False},
        {"return_code": -9},
        {
            "return_code": 0,
            "container_state": (
                '{"OOMKilled":false,"ExitCode":0,"Error":"","Running":false}'
            ),
        },
        {
            "container_state": (
                '{"OOMKilled":true,"ExitCode":137,"Error":"","Running":false}'
            )
        },
        {
            "container_state": (
                '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":true}'
            )
        },
        {
            "container_state": (
                '{"OOMKilled":false,"ExitCode":0,"Error":"","Running":false}'
            )
        },
    ],
)
def test_timeout_requires_complete_trusted_lifecycle(
    tmp_path: Path, invalid_updates: dict[str, Any]
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    process_values: dict[str, Any] = {
        "return_code": 137,
        "stdout": b"",
        "output_length": 0,
        "timed_out": True,
        "kill_succeeded": True,
        "container_state": (
            '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
        ),
    }
    process_values.update(invalid_updates)
    process = _trusted_runtime_process(module, **process_values)
    executor = _StubExecutor([process])
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Trusted runtime metadata is invalid or missing."


@pytest.mark.parametrize(
    "invalid_updates",
    [
        {"stdout": b"short", "output_length": 5},
        {"stdout": b"x" * 4097, "output_length": 4097, "stdout_limited": False},
        {"stdout": b"x" * 4098, "output_length": 4098},
        {"timed_out": True},
        {"kill_succeeded": False},
        {"inspect_succeeded": False},
        {"cleanup_succeeded": False},
        {
            "return_code": 0,
            "container_state": (
                '{"OOMKilled":false,"ExitCode":0,"Error":"","Running":false}'
            ),
        },
        {
            "container_state": (
                '{"OOMKilled":true,"ExitCode":137,"Error":"","Running":false}'
            )
        },
    ],
)
def test_output_limit_requires_observed_overflow_and_complete_lifecycle(
    tmp_path: Path, invalid_updates: dict[str, Any]
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    process_values: dict[str, Any] = {
        "return_code": 137,
        "stdout": b"x" * 4097,
        "output_length": 4097,
        "stdout_limited": True,
        "kill_succeeded": True,
        "container_state": (
            '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
        ),
    }
    process_values.update(invalid_updates)
    process = _trusted_runtime_process(module, **process_values)
    executor = _StubExecutor([process])
    backend = _backend(module, executor)
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
        memory_limit_mb=128,
        time_limit_ms=250,
        output_limit_bytes=4096,
    )

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Trusted runtime metadata is invalid or missing."


@pytest.mark.parametrize("limited_field", ["stdout_limited", "stderr_limited"])
def test_compile_diagnostic_overflow_is_fixed_infrastructure_error(
    tmp_path: Path, limited_field: str
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")
    overflow_size = module.MAX_COMPILER_STREAM_BYTES + 1
    process = _trusted_runtime_process(
        module,
        return_code=137,
        stdout=b"x" * (overflow_size if limited_field == "stdout_limited" else 0),
        stderr=b"x" * (overflow_size if limited_field == "stderr_limited" else 0),
        output_length=overflow_size if limited_field == "stdout_limited" else 0,
        kill_succeeded=True,
        container_state=(
            '{"OOMKilled":false,"ExitCode":137,"Error":"","Running":false}'
        ),
        **{limited_field: True},
    )
    executor = _StubExecutor([process])
    backend = _backend(module, executor)

    outcome = backend.compile(workspace=_workspace(tmp_path), memory_limit_mb=128)

    assert outcome.status is JudgeStatus.INFRASTRUCTURE_ERROR
    assert outcome.diagnostics == "Compiler diagnostics exceeded the host limit."


@pytest.mark.parametrize(
    ("stats_json", "expected_memory_kb"),
    [
        ('{"MemUsage":"1536KiB / 128MiB"}', 1536),
        ('{"MemUsage":"1.5MiB / 128MiB"}', 1536),
        ('{"MemUsage":"1024B / 128MiB"}', 1),
        ('{"MemUsage":"NaNMiB / 128MiB"}', None),
        ('{"MemUsage":"-1MiB / 128MiB"}', None),
        ('{"MemUsage":"1e999MiB / 128MiB"}', None),
        ('{"MemUsage":"9223372036854775808KiB / 128MiB"}', None),
    ],
)
def test_host_memory_stats_parser_is_nonnegative_and_bounded(
    stats_json: str, expected_memory_kb: int | None
) -> None:
    module = importlib.import_module("hy3_algotrace.docker_judge")

    assert module._parse_memory_stats(stats_json) == expected_memory_kb
