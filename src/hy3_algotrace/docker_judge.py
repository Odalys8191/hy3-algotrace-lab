"""Docker CLI command construction for the isolated C++17 judge."""

from __future__ import annotations

import json
import os
import re
import secrets
import selectors
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .contracts import JudgeEvidence, JudgeStatus, PerTestEvidence, ProblemRecord, TestCase
from .judge import Judge

JUDGE_BUILD_TAG = "hy3-algotrace-cpp17-judge:1.0"
JUDGE_IMAGE_ENV = "HY3_JUDGE_IMAGE"

DEFAULT_OUTPUT_LIMIT_BYTES = 64 * 1024
MAX_DIAGNOSTIC_CHARACTERS = 4096
MAX_COUNTEREXAMPLE_CHARACTERS = 2048
MAX_TRUSTED_INTEGER = (1 << 63) - 1
MAX_DOCKER_STDERR_BYTES = 16 * 1024
MAX_COMPILER_STREAM_BYTES = 16 * 1024
MAX_DOCKER_CREATE_STDOUT_BYTES = 128
MAX_MEMORY_STATS_LINE_BYTES = 4096
INVALID_RUNTIME_METADATA = "Trusted runtime metadata is invalid or missing."
INVALID_COMPILE_METADATA = "Trusted compilation metadata is invalid or missing."
COMPILER_DIAGNOSTICS_LIMIT = "Compiler diagnostics exceeded the host limit."

_CONTAINER_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")
_CONTAINER_USER = "65532:65532"
_ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_IMMUTABLE_IMAGE_PATTERN = re.compile(
    r"(?:[A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[0-9a-f]{64}\Z"
)
_VALIDATOR_IMAGE_PATTERN = re.compile(
    r"([A-Za-z0-9][A-Za-z0-9._:/-]*)@sha256:([0-9a-f]{64})\Z"
)
_PACKAGE_PATTERN = re.compile(r"[a-z0-9][a-z0-9+.-]*=[A-Za-z0-9][A-Za-z0-9.+:~_-]*\Z")
_CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class CompileOutcome:
    """Container compilation result before it is mapped to public evidence."""

    status: JudgeStatus
    diagnostics: str = ""


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """One container execution result before output comparison."""

    status: JudgeStatus
    stdout: str = ""
    diagnostics: str = ""
    time_ms: int | None = None
    memory_kb: int | None = None


@dataclass(frozen=True, slots=True)
class DockerProcessResult:
    """Bounded result returned by the host-side Docker CLI process."""

    return_code: object
    stdout: bytes | str = b""
    stderr: bytes | str = b""
    timed_out: object = False
    stdout_limited: object = False
    stderr_limited: object = False
    output_length: object = None
    elapsed_ms: object = None
    memory_kb: object = None
    container_id: object = None
    kill_succeeded: object = None
    inspect_succeeded: object = False
    cleanup_succeeded: object = False
    container_state: object = None


@dataclass(frozen=True, slots=True)
class _BoundedCapture:
    return_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    stdout_limited: bool
    stderr_limited: bool
    stop_succeeded: bool | None
    observed_at: float


@dataclass(slots=True)
class _MemoryObserver:
    process: subprocess.Popen[bytes]
    thread: threading.Thread
    samples_kb: list[int]


@dataclass(frozen=True, slots=True)
class _TrustedProcessObservation:
    exit_status: int
    oom_killed: bool
    timed_out: bool
    stdout_limited: bool
    stderr_limited: bool
    time_ms: int | None
    memory_kb: int | None


class CommandExecutor(Protocol):
    """Execute Docker CLI argv without a shell."""

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        stdout_limit_bytes: int,
        stderr_limit_bytes: int,
        collect_memory: bool = False,
    ) -> DockerProcessResult: ...


class DockerCommandExecutor:
    """The only host process launcher: it accepts Docker commands exclusively."""

    def run(
        self,
        command: tuple[str, ...],
        *,
        timeout_seconds: float,
        stdout_limit_bytes: int,
        stderr_limit_bytes: int,
        collect_memory: bool = False,
    ) -> DockerProcessResult:
        if command[:2] != ("docker", "create"):
            raise ValueError("the judge executor accepts only docker create commands")
        if timeout_seconds <= 0 or stdout_limit_bytes <= 0 or stderr_limit_bytes <= 0:
            raise ValueError("process bounds must be positive")

        create = _run_bounded_command(
            command,
            timeout_seconds=10.0,
            stdout_limit_bytes=MAX_DOCKER_CREATE_STDOUT_BYTES,
            stderr_limit_bytes=MAX_DOCKER_STDERR_BYTES,
        )
        container_id = _container_id_from_create(create)
        if container_id is None:
            return DockerProcessResult(
                return_code=create.return_code,
                stdout=create.stdout,
                stderr=create.stderr,
                timed_out=create.timed_out,
                stdout_limited=create.stdout_limited,
                stderr_limited=create.stderr_limited,
            )

        started = time.monotonic()
        memory_observer: _MemoryObserver | None = None
        try:
            attached = subprocess.Popen(
                ("docker", "start", "--attach", container_id),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if collect_memory:
                memory_observer = _start_memory_observer(container_id)
            capture = _capture_bounded_process(
                attached,
                timeout_seconds=timeout_seconds,
                stdout_limit_bytes=stdout_limit_bytes,
                stderr_limit_bytes=stderr_limit_bytes,
                started=started,
                stop=lambda: _kill_container(container_id),
            )
        except (OSError, RuntimeError, ValueError):
            capture = _BoundedCapture(
                return_code=None,
                stdout=b"",
                stderr=b"",
                timed_out=False,
                stdout_limited=False,
                stderr_limited=False,
                stop_succeeded=None,
                observed_at=time.monotonic(),
            )
        try:
            memory_kb = _stop_memory_observer(memory_observer)
        except (OSError, RuntimeError, subprocess.SubprocessError):
            memory_kb = None
        try:
            inspect_succeeded, container_state = _inspect_container_state(container_id)
        except (OSError, RuntimeError, ValueError):
            inspect_succeeded, container_state = False, None
        cleanup_succeeded = _remove_container(container_id)
        return DockerProcessResult(
            return_code=capture.return_code,
            stdout=capture.stdout,
            stderr=capture.stderr,
            timed_out=capture.timed_out,
            stdout_limited=capture.stdout_limited,
            stderr_limited=capture.stderr_limited,
            output_length=len(capture.stdout),
            elapsed_ms=round((capture.observed_at - started) * 1000),
            memory_kb=memory_kb,
            container_id=container_id,
            kill_succeeded=capture.stop_succeeded,
            inspect_succeeded=inspect_succeeded,
            cleanup_succeeded=cleanup_succeeded,
            container_state=container_state,
        )


class SandboxBackend(Protocol):
    """Container-only backend used by the judge orchestrator."""

    def compile(self, *, workspace: Path, memory_limit_mb: int) -> CompileOutcome: ...

    def execute(
        self,
        *,
        workspace: Path,
        input_dir: Path,
        result_dir: Path,
        memory_limit_mb: int,
        time_limit_ms: int,
        output_limit_bytes: int,
    ) -> ExecutionOutcome: ...


class DockerJudge(Judge):
    """Compile and execute C++17 source only through a sandbox backend."""

    def __init__(
        self,
        *,
        backend: SandboxBackend | None = None,
        temp_root: Path | None = None,
        output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    ) -> None:
        if output_limit_bytes <= 0:
            raise ValueError("output limit must be positive")
        self._backend = backend or DockerCliBackend()
        self._temp_root = temp_root
        self._output_limit_bytes = output_limit_bytes

    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        try:
            return self._judge(problem, cpp_source)
        except ValidationError:
            return JudgeEvidence(
                compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
                verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=INVALID_RUNTIME_METADATA,
            )

    def _judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        final_tests = (*problem.hidden_tests, *problem.generated_tests)
        if not final_tests:
            return JudgeEvidence(
                compile_status=JudgeStatus.NOT_RUN,
                verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="No hidden or generated final tests are configured.",
            )

        try:
            temp_root = self._validated_temp_root()
            temporary_directory = tempfile.TemporaryDirectory(
                prefix="hy3-judge-", dir=temp_root
            )
        except (OSError, RuntimeError, ValueError) as error:
            return _infrastructure_evidence(
                error,
                sandbox_root=_diagnostic_sandbox_root(self._temp_root),
                final_tests=final_tests,
            )
        with temporary_directory as raw_workspace:
            workspace = Path(raw_workspace)
            try:
                workspace.chmod(0o777)
                source_path = workspace / "main.cpp"
                source_path.write_text(cpp_source, encoding="utf-8")
                source_path.chmod(0o644)
            except (OSError, RuntimeError, ValueError) as error:
                return _infrastructure_evidence(
                    error,
                    sandbox_root=workspace,
                    final_tests=final_tests,
                )

            try:
                compile_outcome = self._backend.compile(
                    workspace=workspace,
                    memory_limit_mb=problem.memory_limit_mb,
                )
            except (
                OSError,
                ArithmeticError,
                RuntimeError,
                subprocess.SubprocessError,
                ValueError,
            ) as error:
                return JudgeEvidence(
                    compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
                    verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                    diagnostics=_sanitize_diagnostics(
                        str(error),
                        sandbox_root=workspace,
                        hidden_expected_outputs=tuple(
                            test.expected_output for test in final_tests
                        ),
                    ),
                )
            compile_diagnostics = _sanitize_diagnostics(
                compile_outcome.diagnostics,
                sandbox_root=workspace,
                hidden_expected_outputs=tuple(
                    test.expected_output for test in final_tests
                ),
            )
            if compile_outcome.status is not JudgeStatus.AC:
                return JudgeEvidence(
                    compile_status=compile_outcome.status,
                    verdict=compile_outcome.status,
                    diagnostics=compile_diagnostics,
                )

            test_evidence = tuple(
                self._run_test(
                    problem=problem,
                    test=test,
                    index=index,
                    workspace=workspace,
                    hidden_expected_outputs=tuple(
                        final_test.expected_output for final_test in final_tests
                    ),
                )
                for index, test in enumerate(final_tests)
            )
            infrastructure_failure = next(
                (
                    test
                    for test in test_evidence
                    if test.status is JudgeStatus.INFRASTRUCTURE_ERROR
                ),
                None,
            )
            first_failure = infrastructure_failure or next(
                (test for test in test_evidence if test.status is not JudgeStatus.AC),
                None,
            )
            if first_failure is None or infrastructure_failure is not None:
                safe_test_evidence = tuple(
                    test.model_copy(update={"counterexample_input": None})
                    for test in test_evidence
                )
            else:
                first_failure_seen = False
                safe_tests: list[PerTestEvidence] = []
                for test in test_evidence:
                    expose_counterexample = (
                        not first_failure_seen and test.status is not JudgeStatus.AC
                    )
                    if expose_counterexample:
                        first_failure_seen = True
                    safe_tests.append(
                        test
                        if expose_counterexample
                        else test.model_copy(update={"counterexample_input": None})
                    )
                safe_test_evidence = tuple(safe_tests)
            verdict = first_failure.status if first_failure else JudgeStatus.AC
            return JudgeEvidence(
                compile_status=JudgeStatus.AC,
                verdict=verdict,
                tests=safe_test_evidence,
                diagnostics=first_failure.diagnostics if first_failure else "",
                first_counterexample_input=(
                    first_failure.counterexample_input
                    if first_failure and infrastructure_failure is None
                    else None
                ),
            )

    def _run_test(
        self,
        *,
        problem: ProblemRecord,
        test: TestCase,
        index: int,
        workspace: Path,
        hidden_expected_outputs: tuple[str, ...],
    ) -> PerTestEvidence:
        case_directory = workspace / f"case-{index:04d}"
        input_dir = case_directory / "input"
        result_dir = case_directory / "result"
        try:
            input_dir.mkdir(parents=True)
            result_dir.mkdir()
            input_dir.chmod(0o755)
            result_dir.chmod(0o700)
            input_path = input_dir / "input.txt"
            input_path.write_text(test.input_data, encoding="utf-8")
            input_path.chmod(0o644)
            outcome = self._backend.execute(
                workspace=workspace,
                input_dir=input_dir,
                result_dir=result_dir,
                memory_limit_mb=problem.memory_limit_mb,
                time_limit_ms=problem.time_limit_ms,
                output_limit_bytes=self._output_limit_bytes,
            )
        except (
            OSError,
            ArithmeticError,
            RuntimeError,
            subprocess.SubprocessError,
            ValueError,
        ) as error:
            return PerTestEvidence(
                test_id=test.test_id,
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=_sanitize_diagnostics(
                    str(error),
                    sandbox_root=workspace,
                    hidden_expected_outputs=hidden_expected_outputs,
                ),
            )
        status = outcome.status
        diagnostics = ""
        if status is JudgeStatus.INFRASTRUCTURE_ERROR:
            diagnostics = _sanitize_diagnostics(
                outcome.diagnostics,
                sandbox_root=workspace,
                hidden_expected_outputs=hidden_expected_outputs,
            )
        if status is JudgeStatus.AC and not _outputs_match(
            outcome.stdout, test.expected_output
        ):
            status = JudgeStatus.WA
            diagnostics = "Program output did not match the expected output."
        elif status not in {JudgeStatus.AC, JudgeStatus.INFRASTRUCTURE_ERROR}:
            diagnostics = _public_runtime_diagnostics(status)

        counterexample = (
            _sanitize_counterexample(test.input_data)
            if status not in {JudgeStatus.AC, JudgeStatus.INFRASTRUCTURE_ERROR}
            else None
        )
        try:
            return PerTestEvidence(
                test_id=test.test_id,
                status=status,
                time_ms=outcome.time_ms,
                memory_kb=outcome.memory_kb,
                diagnostics=diagnostics,
                counterexample_input=counterexample,
            )
        except ValidationError:
            return PerTestEvidence(
                test_id=test.test_id,
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=INVALID_RUNTIME_METADATA,
            )

    def _validated_temp_root(self) -> Path | None:
        if self._temp_root is None:
            return None
        return _safe_mount_directory(self._temp_root)


class DockerCliBackend:
    """Compile and execute exclusively through hardened Docker CLI commands."""

    def __init__(
        self,
        *,
        executor: CommandExecutor | None = None,
        command_factory: DockerCommandFactory | None = None,
    ) -> None:
        self._executor = executor or DockerCommandExecutor()
        self._command_factory = command_factory or DockerCommandFactory()

    def compile(self, *, workspace: Path, memory_limit_mb: int) -> CompileOutcome:
        command = self._command_factory.compile_command(
            container_name=_random_container_name(),
            workspace=workspace,
            memory_limit_mb=memory_limit_mb,
        )
        process = self._executor.run(
            command,
            timeout_seconds=20.0,
            stdout_limit_bytes=MAX_COMPILER_STREAM_BYTES,
            stderr_limit_bytes=MAX_COMPILER_STREAM_BYTES,
        )
        observation = _trusted_process_observation(
            process,
            stdout_limit_bytes=MAX_COMPILER_STREAM_BYTES,
            stderr_limit_bytes=MAX_COMPILER_STREAM_BYTES,
        )
        if observation is None:
            return CompileOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=INVALID_COMPILE_METADATA,
            )
        if observation.stdout_limited or observation.stderr_limited:
            return CompileOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=COMPILER_DIAGNOSTICS_LIMIT,
            )
        if observation.timed_out or observation.oom_killed:
            return CompileOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="Docker compilation infrastructure failed.",
            )
        diagnostics = _process_diagnostics(process)
        if observation.exit_status == 1:
            return CompileOutcome(
                status=JudgeStatus.COMPILE_ERROR,
                diagnostics=diagnostics,
            )
        if observation.exit_status == 0:
            return CompileOutcome(status=JudgeStatus.AC, diagnostics=diagnostics)
        return CompileOutcome(
            status=JudgeStatus.INFRASTRUCTURE_ERROR,
            diagnostics="Docker compilation infrastructure failed.",
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
    ) -> ExecutionOutcome:
        command = self._command_factory.runtime_command(
            container_name=_random_container_name(),
            workspace=workspace,
            input_dir=input_dir,
            result_dir=result_dir,
            memory_limit_mb=memory_limit_mb,
            time_limit_ms=time_limit_ms,
            output_limit_bytes=output_limit_bytes,
        )
        process = self._executor.run(
            command,
            timeout_seconds=time_limit_ms / 1000,
            stdout_limit_bytes=output_limit_bytes,
            stderr_limit_bytes=output_limit_bytes,
            collect_memory=True,
        )
        return _execution_outcome_from_process(
            process,
            output_limit_bytes=output_limit_bytes,
        )


class DockerCommandFactory:
    """Build argv-only Docker commands with the mandatory sandbox boundaries."""

    def __init__(self, *, image: str | None = None) -> None:
        self._image = image

    def compile_command(
        self,
        *,
        container_name: str,
        workspace: Path,
        memory_limit_mb: int,
    ) -> tuple[str, ...]:
        safe_workspace = _safe_mount_directory(workspace)
        return (
            *self._security_prefix(
                container_name=container_name,
                memory_limit_mb=memory_limit_mb,
                output_limit_bytes=16 * 1024 * 1024,
            ),
            f"--mount=type=bind,src={safe_workspace},dst=/workspace",
            self._image_reference(),
            "compile",
            "/workspace/main.cpp",
            "/workspace/main",
        )

    def runtime_command(
        self,
        *,
        container_name: str,
        workspace: Path,
        input_dir: Path,
        result_dir: Path,
        memory_limit_mb: int,
        time_limit_ms: int,
        output_limit_bytes: int,
    ) -> tuple[str, ...]:
        safe_workspace = _safe_mount_directory(workspace)
        safe_input_dir = _safe_mount_directory(input_dir)
        _safe_mount_directory(result_dir)
        if time_limit_ms <= 0:
            raise ValueError("time limit must be positive")
        return (
            *self._security_prefix(
                container_name=container_name,
                memory_limit_mb=memory_limit_mb,
                output_limit_bytes=output_limit_bytes,
            ),
            f"--mount=type=bind,src={safe_workspace},dst=/workspace,readonly",
            f"--mount=type=bind,src={safe_input_dir},dst=/input,readonly",
            self._image_reference(),
            "run",
            "/workspace/main",
            "/input/input.txt",
        )

    def _image_reference(self) -> str:
        return _immutable_image_reference(self._image or os.environ.get(JUDGE_IMAGE_ENV, ""))

    @staticmethod
    def _security_prefix(
        *,
        container_name: str,
        memory_limit_mb: int,
        output_limit_bytes: int,
    ) -> tuple[str, ...]:
        if not _CONTAINER_NAME_PATTERN.fullmatch(container_name):
            raise ValueError("container name must contain only safe Docker name characters")
        if memory_limit_mb <= 0:
            raise ValueError("memory limit must be positive")
        if output_limit_bytes <= 0:
            raise ValueError("output limit must be positive")
        if output_limit_bytes > MAX_TRUSTED_INTEGER:
            raise ValueError("output limit exceeds its supported bound")
        return (
            "docker",
            "create",
            f"--name={container_name}",
            "--log-driver=none",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=64",
            "--cpus=1.0",
            f"--memory={memory_limit_mb}m",
            f"--memory-swap={memory_limit_mb}m",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m",
            "--ulimit=nofile=64:64",
            f"--ulimit=fsize={output_limit_bytes}:{output_limit_bytes}",
            f"--user={_CONTAINER_USER}",
        )


def _safe_mount_directory(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_absolute() or not resolved.is_dir() or any(
        character in str(resolved) for character in (",", "\n", "\r", "\0")
    ):
        raise ValueError("Docker mounts require a safe absolute directory path")
    return resolved


def _immutable_image_reference(image: str) -> str:
    if not _IMMUTABLE_IMAGE_PATTERN.fullmatch(image):
        raise ValueError(
            f"{JUDGE_IMAGE_ENV} must be an immutable SHA-256 image reference"
        )
    return image


def _exact_package(package: str, *, expected_name: str) -> str:
    if not _PACKAGE_PATTERN.fullmatch(package) or not package.startswith(
        f"{expected_name}="
    ):
        raise ValueError(f"{expected_name} must include an exact package version")
    return package


def _validator_image_parts(image: str) -> tuple[str, str]:
    match = _VALIDATOR_IMAGE_PATTERN.fullmatch(image)
    if match is None:
        raise ValueError("validator image must be a repository-pinned SHA-256 reference")
    return match.group(1), match.group(2)


def release_build_command(
    *,
    context: Path,
    validator_image: str,
    base_image: str,
    time_package: str,
    util_linux_package: str,
) -> tuple[str, ...]:
    """Return the reproducible release-image build command without executing it."""

    safe_context = _safe_mount_directory(context)
    validator_repository, validator_digest = _validator_image_parts(validator_image)
    immutable_base = _immutable_image_reference(base_image)
    exact_time = _exact_package(time_package, expected_name="time")
    exact_util_linux = _exact_package(util_linux_package, expected_name="util-linux")
    return (
        "docker",
        "build",
        "--tag",
        JUDGE_BUILD_TAG,
        "--build-arg",
        f"JUDGE_VALIDATOR_REPOSITORY={validator_repository}",
        "--build-arg",
        f"JUDGE_VALIDATOR_DIGEST={validator_digest}",
        "--build-arg",
        f"JUDGE_BASE_IMAGE={immutable_base}",
        "--build-arg",
        f"JUDGE_TIME_PACKAGE={exact_time}",
        "--build-arg",
        f"JUDGE_UTIL_LINUX_PACKAGE={exact_util_linux}",
        str(safe_context),
    )


def _outputs_match(actual: str, expected: str) -> bool:
    return actual.split() == expected.split()


def _infrastructure_evidence(
    error: BaseException,
    *,
    sandbox_root: Path,
    final_tests: tuple[TestCase, ...],
) -> JudgeEvidence:
    return JudgeEvidence(
        compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
        verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
        diagnostics=_sanitize_diagnostics(
            str(error),
            sandbox_root=sandbox_root,
            hidden_expected_outputs=tuple(test.expected_output for test in final_tests),
        ),
    )


def _diagnostic_sandbox_root(temp_root: Path | None) -> Path:
    if temp_root is None:
        return Path(tempfile.gettempdir())
    return temp_root.absolute()


def _public_runtime_diagnostics(status: JudgeStatus) -> str:
    messages = {
        JudgeStatus.TLE: "Program exceeded the time limit.",
        JudgeStatus.MLE: "Program exceeded the memory limit.",
        JudgeStatus.OUTPUT_LIMIT: "Program exceeded the output limit.",
        JudgeStatus.RUNTIME_ERROR: "Program terminated with a runtime error.",
    }
    return messages.get(status, "Program execution failed.")


def _sanitize_diagnostics(
    diagnostics: str,
    *,
    sandbox_root: Path,
    hidden_expected_outputs: tuple[str, ...],
) -> str:
    sanitized = _ANSI_PATTERN.sub("", diagnostics)
    sanitized = sanitized.replace(str(sandbox_root), "<sandbox>")
    sanitized = sanitized.replace("/workspace", "<sandbox>")
    for expected_output in hidden_expected_outputs:
        candidates = {expected_output, expected_output.strip()}
        for candidate in sorted(candidates, key=len, reverse=True):
            if candidate:
                sanitized = sanitized.replace(candidate, "<redacted expected output>")
    sanitized = "".join(
        character
        if character in {"\n", "\t"} or ord(character) >= 32
        else "\ufffd"
        for character in sanitized
    )
    if len(sanitized) > MAX_DIAGNOSTIC_CHARACTERS:
        sanitized = sanitized[:MAX_DIAGNOSTIC_CHARACTERS] + "\n<truncated>"
    return sanitized.strip()


def _sanitize_counterexample(input_data: str) -> str:
    sanitized = "".join(
        character
        if character in {"\n", "\t"} or ord(character) >= 32
        else "\ufffd"
        for character in input_data
    )
    if len(sanitized) > MAX_COUNTEREXAMPLE_CHARACTERS:
        return sanitized[:MAX_COUNTEREXAMPLE_CHARACTERS] + "\n<truncated>"
    return sanitized


def _random_container_name() -> str:
    return f"hy3-judge-{secrets.token_hex(8)}"


def _process_diagnostics(process: DockerProcessResult) -> str:
    return "\n".join(
        decoded
        for output in (process.stdout, process.stderr)
        if (decoded := _decode_process_output(output).strip())
    )


def _execution_outcome_from_process(
    process: DockerProcessResult, *, output_limit_bytes: int
) -> ExecutionOutcome:
    observation = _trusted_process_observation(
        process,
        stdout_limit_bytes=output_limit_bytes,
        stderr_limit_bytes=output_limit_bytes,
    )
    if observation is None:
        return ExecutionOutcome(
            status=JudgeStatus.INFRASTRUCTURE_ERROR,
            diagnostics=INVALID_RUNTIME_METADATA,
        )
    if not isinstance(process.stdout, bytes):
        return ExecutionOutcome(
            status=JudgeStatus.INFRASTRUCTURE_ERROR,
            diagnostics=INVALID_RUNTIME_METADATA,
        )
    if observation.timed_out:
        status = JudgeStatus.TLE
    elif observation.stdout_limited or observation.stderr_limited:
        status = JudgeStatus.OUTPUT_LIMIT
    elif observation.oom_killed:
        status = JudgeStatus.MLE
    elif observation.exit_status == 0:
        status = JudgeStatus.AC
    else:
        status = JudgeStatus.RUNTIME_ERROR
    return ExecutionOutcome(
        status=status,
        stdout=process.stdout[:output_limit_bytes].decode(
            "utf-8", errors="replace"
        ),
        time_ms=observation.time_ms,
        memory_kb=observation.memory_kb,
    )


def _trusted_process_observation(
    process: DockerProcessResult,
    *,
    stdout_limit_bytes: int,
    stderr_limit_bytes: int,
) -> _TrustedProcessObservation | None:
    try:
        validated_stdout_limit = _bounded_integer(
            stdout_limit_bytes,
            minimum=1,
            maximum=MAX_TRUSTED_INTEGER - 1,
        )
        validated_stderr_limit = _bounded_integer(
            stderr_limit_bytes,
            minimum=1,
            maximum=MAX_TRUSTED_INTEGER - 1,
        )
        if not isinstance(process.stdout, bytes) or not isinstance(process.stderr, bytes):
            raise ValueError("captured streams must be bounded bytes")
        timed_out = _strict_boolean(process.timed_out)
        stdout_limited = _strict_boolean(process.stdout_limited)
        stderr_limited = _strict_boolean(process.stderr_limited)
        if sum((timed_out, stdout_limited, stderr_limited)) > 1:
            raise ValueError("only the first observed host bound may be reported")
        _validate_stream_length(
            process.stdout,
            limit=validated_stdout_limit,
            limited=stdout_limited,
        )
        _validate_stream_length(
            process.stderr,
            limit=validated_stderr_limit,
            limited=stderr_limited,
        )
        reported_output_length = _bounded_integer(
            process.output_length,
            minimum=0,
            maximum=MAX_TRUSTED_INTEGER,
        )
        if reported_output_length != len(process.stdout):
            raise ValueError("reported output length disagrees with its bounded buffer")
        if not isinstance(process.container_id, str) or not _CONTAINER_ID_PATTERN.fullmatch(
            process.container_id
        ):
            raise ValueError("trusted container ID is missing")
        if _strict_boolean(process.inspect_succeeded) is not True:
            raise ValueError("container inspection did not succeed")
        if _strict_boolean(process.cleanup_succeeded) is not True:
            raise ValueError("container cleanup did not succeed")
        host_stopped = timed_out or stdout_limited or stderr_limited
        if host_stopped:
            if _strict_boolean(process.kill_succeeded) is not True:
                raise ValueError("host limit requires a successful CID-only kill")
        elif process.kill_succeeded is not None:
            raise ValueError("kill metadata is present without a host limit")
        oom_killed, exit_status = _parse_container_state(process.container_state)
        docker_return_code = _bounded_integer(
            process.return_code,
            minimum=0,
            maximum=255,
        )
        if docker_return_code != exit_status:
            raise ValueError("Docker exit status disagrees with container state")
        if host_stopped and (oom_killed or exit_status != 137):
            raise ValueError("host SIGKILL metadata disagrees with container state")
        time_ms = _optional_nonnegative_integer(process.elapsed_ms)
        memory_kb = _optional_nonnegative_integer(process.memory_kb)
    except (ArithmeticError, TypeError, ValueError):
        return None
    return _TrustedProcessObservation(
        exit_status=exit_status,
        oom_killed=oom_killed,
        timed_out=timed_out,
        stdout_limited=stdout_limited,
        stderr_limited=stderr_limited,
        time_ms=time_ms,
        memory_kb=memory_kb,
    )


def _validate_stream_length(stream: bytes, *, limit: int, limited: bool) -> None:
    maximum = limit + 1 if limited else limit
    if len(stream) > maximum:
        raise ValueError("captured stream exceeds its hard bound")
    if limited and len(stream) != limit + 1:
        raise ValueError("stream limit marker lacks the overflow sentinel byte")


def _strict_boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("trusted boolean metadata must be a JSON boolean")
    return value


def _bounded_integer(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("trusted integer metadata is outside its supported bound")
    return value


def _optional_nonnegative_integer(value: object) -> int | None:
    if value is None:
        return None
    return _bounded_integer(value, minimum=0, maximum=MAX_TRUSTED_INTEGER)


def _parse_container_state(value: object) -> tuple[bool, int]:
    if not isinstance(value, str) or len(value) > MAX_DOCKER_STDERR_BYTES:
        raise ValueError("container state is missing or oversized")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("container state must be a JSON object")
    oom_killed = _strict_boolean(parsed.get("OOMKilled"))
    exit_status = _bounded_integer(
        parsed.get("ExitCode"),
        minimum=0,
        maximum=255,
    )
    state_error = parsed.get("Error")
    if not isinstance(state_error, str) or state_error:
        raise ValueError("container state reports an infrastructure error")
    if _strict_boolean(parsed.get("Running")):
        raise ValueError("container is still running after host observation")
    return oom_killed, exit_status


def _run_bounded_command(
    command: tuple[str, ...],
    *,
    timeout_seconds: float,
    stdout_limit_bytes: int,
    stderr_limit_bytes: int,
) -> _BoundedCapture:
    started = time.monotonic()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError:
        return _BoundedCapture(
            return_code=None,
            stdout=b"",
            stderr=b"",
            timed_out=False,
            stdout_limited=False,
            stderr_limited=False,
            stop_succeeded=None,
            observed_at=time.monotonic(),
        )
    return _capture_bounded_process(
        process,
        timeout_seconds=timeout_seconds,
        stdout_limit_bytes=stdout_limit_bytes,
        stderr_limit_bytes=stderr_limit_bytes,
        started=started,
        stop=None,
    )


def _capture_bounded_process(
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float,
    stdout_limit_bytes: int,
    stderr_limit_bytes: int,
    started: float,
    stop: Callable[[], bool] | None,
) -> _BoundedCapture:
    if process.stdout is None or process.stderr is None:
        raise RuntimeError("Docker runtime pipes are unavailable")
    stdout_pipe = process.stdout
    stderr_pipe = process.stderr
    selector = selectors.DefaultSelector()
    selector.register(stdout_pipe, selectors.EVENT_READ, "stdout")
    selector.register(stderr_pipe, selectors.EVENT_READ, "stderr")
    stdout = bytearray()
    stderr = bytearray()
    deadline = started + timeout_seconds
    timed_out = False
    stdout_limited = False
    stderr_limited = False
    stop_succeeded: bool | None = None
    stopped_at: float | None = None

    def stop_process() -> None:
        nonlocal stop_succeeded, stopped_at
        stopped_at = time.monotonic()
        if stop is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        else:
            stop_succeeded = stop()

    while selector.get_map():
        now = time.monotonic()
        if stopped_at is None and now >= deadline:
            timed_out = True
            stop_process()
        wait_seconds = 0.05
        if stopped_at is None:
            wait_seconds = max(0.0, min(wait_seconds, deadline - now))
        for key, _ in selector.select(wait_seconds):
            chunk = os.read(key.fd, 64 * 1024)
            if not chunk:
                selector.unregister(key.fileobj)
                (stdout_pipe if key.data == "stdout" else stderr_pipe).close()
                continue
            if key.data == "stdout":
                allowed = stdout_limit_bytes + (1 if stopped_at is None else 0)
                remaining = allowed - len(stdout)
                if remaining > 0:
                    stdout.extend(chunk[:remaining])
                crossed_limit = len(chunk) > remaining or len(stdout) > stdout_limit_bytes
                if crossed_limit and stopped_at is None:
                    stdout_limited = True
                    stop_process()
            else:
                allowed = stderr_limit_bytes + (1 if stopped_at is None else 0)
                remaining = allowed - len(stderr)
                if remaining > 0:
                    stderr.extend(chunk[:remaining])
                crossed_limit = len(chunk) > remaining or len(stderr) > stderr_limit_bytes
                if crossed_limit and stopped_at is None:
                    stderr_limited = True
                    stop_process()
        if stopped_at is not None and time.monotonic() - stopped_at > 5:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        if process.poll() is not None and not selector.get_map():
            break

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    observed_at = stopped_at or time.monotonic()
    return _BoundedCapture(
        return_code=process.returncode,
        stdout=bytes(stdout),
        stderr=bytes(stderr),
        timed_out=timed_out,
        stdout_limited=stdout_limited,
        stderr_limited=stderr_limited,
        stop_succeeded=stop_succeeded,
        observed_at=observed_at,
    )


def _container_id_from_create(capture: _BoundedCapture) -> str | None:
    if (
        capture.return_code != 0
        or capture.timed_out
        or capture.stdout_limited
        or capture.stderr_limited
    ):
        return None
    try:
        container_id = capture.stdout.decode("ascii").strip()
    except UnicodeError:
        return None
    if not _CONTAINER_ID_PATTERN.fullmatch(container_id):
        return None
    return container_id


def _run_silent_docker_control(command: tuple[str, ...]) -> bool:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _kill_container(container_id: str) -> bool:
    if not _CONTAINER_ID_PATTERN.fullmatch(container_id):
        return False
    return _run_silent_docker_control(("docker", "kill", container_id))


def _inspect_container_state(container_id: str) -> tuple[bool, str | None]:
    if not _CONTAINER_ID_PATTERN.fullmatch(container_id):
        return False, None
    capture = _run_bounded_command(
        ("docker", "inspect", "--format={{json .State}}", container_id),
        timeout_seconds=5,
        stdout_limit_bytes=MAX_DOCKER_STDERR_BYTES,
        stderr_limit_bytes=MAX_DOCKER_STDERR_BYTES,
    )
    if (
        capture.return_code != 0
        or capture.timed_out
        or capture.stdout_limited
        or capture.stderr_limited
    ):
        return False, None
    try:
        state = capture.stdout.decode("utf-8")
    except UnicodeError:
        return False, None
    return True, state.strip()


def _remove_container(container_id: str) -> bool:
    if not _CONTAINER_ID_PATTERN.fullmatch(container_id):
        return False
    command = ("docker", "rm", "--force", container_id)
    succeeded = _run_silent_docker_control(command)
    if not succeeded:
        _run_silent_docker_control(command)
    return succeeded


def _start_memory_observer(container_id: str) -> _MemoryObserver | None:
    if not _CONTAINER_ID_PATTERN.fullmatch(container_id):
        return None
    try:
        process = subprocess.Popen(
            (
                "docker",
                "stats",
                "--format={{json .}}",
                "--no-trunc",
                container_id,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    stdout_pipe = process.stdout
    if stdout_pipe is None:
        process.kill()
        return None
    samples_kb: list[int] = []

    def read_samples() -> None:
        try:
            while True:
                line = stdout_pipe.readline(MAX_MEMORY_STATS_LINE_BYTES + 1)
                if not line:
                    return
                if len(line) > MAX_MEMORY_STATS_LINE_BYTES:
                    while line and not line.endswith(b"\n"):
                        line = stdout_pipe.readline(MAX_MEMORY_STATS_LINE_BYTES + 1)
                    continue
                try:
                    sample = _parse_memory_stats(line.decode("utf-8"))
                except UnicodeError:
                    continue
                if sample is not None:
                    if samples_kb:
                        samples_kb[0] = max(samples_kb[0], sample)
                    else:
                        samples_kb.append(sample)
        except (OSError, ValueError):
            return

    thread = threading.Thread(target=read_samples, daemon=True)
    thread.start()
    return _MemoryObserver(process=process, thread=thread, samples_kb=samples_kb)


def _stop_memory_observer(observer: _MemoryObserver | None) -> int | None:
    if observer is None:
        return None
    if observer.process.poll() is None:
        try:
            observer.process.terminate()
        except ProcessLookupError:
            pass
    try:
        observer.process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        observer.process.kill()
        observer.process.wait(timeout=1)
    observer.thread.join(timeout=1)
    if not observer.samples_kb:
        return None
    return max(observer.samples_kb)


def _parse_memory_stats(stats_json: str) -> int | None:
    try:
        parsed = json.loads(stats_json)
        if not isinstance(parsed, dict):
            return None
        usage = parsed.get("MemUsage")
        if not isinstance(usage, str):
            return None
        current = usage.split("/", maxsplit=1)[0].strip()
        match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(B|KiB|MiB|GiB)", current)
        if match is None:
            return None
        value = Decimal(match.group(1))
        factors = {
            "B": Decimal(1) / Decimal(1024),
            "KiB": Decimal(1),
            "MiB": Decimal(1024),
            "GiB": Decimal(1024 * 1024),
        }
        memory_kb = int(
            (value * factors[match.group(2)]).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
    except (ArithmeticError, InvalidOperation, TypeError, ValueError):
        return None
    if not 0 <= memory_kb <= MAX_TRUSTED_INTEGER:
        return None
    return memory_kb


def _decode_process_output(output: bytes | str) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output


def _timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
