"""Docker CLI command construction for the isolated C++17 judge."""

from __future__ import annotations

import os
import re
import secrets
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .contracts import JudgeEvidence, JudgeStatus, PerTestEvidence, ProblemRecord, TestCase
from .judge import Judge

JUDGE_IMAGE = "hy3-algotrace-cpp17-judge:1.0"

DEFAULT_OUTPUT_LIMIT_BYTES = 64 * 1024
MAX_DIAGNOSTIC_CHARACTERS = 4096
MAX_COUNTEREXAMPLE_CHARACTERS = 2048

_CONTAINER_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")
_CONTAINER_USER = "65532:65532"
_ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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

    return_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


class CommandExecutor(Protocol):
    """Execute Docker CLI argv without a shell."""

    def run(
        self, command: tuple[str, ...], *, timeout_seconds: float
    ) -> DockerProcessResult: ...


class DockerCommandExecutor:
    """The only host process launcher: it accepts Docker commands exclusively."""

    def run(
        self, command: tuple[str, ...], *, timeout_seconds: float
    ) -> DockerProcessResult:
        if command[:2] != ("docker", "run"):
            raise ValueError("the judge executor accepts only docker run commands")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            container_name = _container_name_from_command(command)
            subprocess.run(
                ("docker", "kill", container_name),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            return DockerProcessResult(
                return_code=124,
                stdout=_timeout_output(error.stdout),
                stderr=_timeout_output(error.stderr),
                timed_out=True,
            )
        return DockerProcessResult(
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
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
        final_tests = (*problem.hidden_tests, *problem.generated_tests)
        if not final_tests:
            return JudgeEvidence(
                compile_status=JudgeStatus.NOT_RUN,
                verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="No hidden or generated final tests are configured.",
            )

        temp_root = self._validated_temp_root()
        with tempfile.TemporaryDirectory(prefix="hy3-judge-", dir=temp_root) as raw_workspace:
            workspace = Path(raw_workspace)
            workspace.chmod(0o777)
            source_path = workspace / "main.cpp"
            source_path.write_text(cpp_source, encoding="utf-8")
            source_path.chmod(0o644)

            try:
                compile_outcome = self._backend.compile(
                    workspace=workspace,
                    memory_limit_mb=problem.memory_limit_mb,
                )
            except (OSError, subprocess.SubprocessError, ValueError) as error:
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
            first_failure = next(
                (test for test in test_evidence if test.status is not JudgeStatus.AC),
                None,
            )
            verdict = first_failure.status if first_failure else JudgeStatus.AC
            return JudgeEvidence(
                compile_status=JudgeStatus.AC,
                verdict=verdict,
                tests=test_evidence,
                diagnostics=first_failure.diagnostics if first_failure else "",
                first_counterexample_input=(
                    first_failure.counterexample_input if first_failure else None
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
        input_dir.mkdir(parents=True)
        result_dir.mkdir()
        input_dir.chmod(0o755)
        result_dir.chmod(0o777)
        input_path = input_dir / "input.txt"
        input_path.write_text(test.input_data, encoding="utf-8")
        input_path.chmod(0o644)

        try:
            outcome = self._backend.execute(
                workspace=workspace,
                input_dir=input_dir,
                result_dir=result_dir,
                memory_limit_mb=problem.memory_limit_mb,
                time_limit_ms=problem.time_limit_ms,
                output_limit_bytes=self._output_limit_bytes,
            )
        except (OSError, subprocess.SubprocessError, ValueError) as error:
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

        counterexample = (
            _sanitize_counterexample(test.input_data)
            if status not in {JudgeStatus.AC, JudgeStatus.INFRASTRUCTURE_ERROR}
            else None
        )
        return PerTestEvidence(
            test_id=test.test_id,
            status=status,
            time_ms=outcome.time_ms,
            memory_kb=outcome.memory_kb,
            diagnostics=diagnostics,
            counterexample_input=counterexample,
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
        process = self._executor.run(command, timeout_seconds=20.0)
        diagnostics = _process_diagnostics(process)
        if process.timed_out or process.return_code not in {0, 1}:
            return CompileOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=diagnostics or "Docker compilation infrastructure failed.",
            )
        if process.return_code == 1:
            return CompileOutcome(
                status=JudgeStatus.COMPILE_ERROR,
                diagnostics=diagnostics,
            )
        return CompileOutcome(status=JudgeStatus.AC, diagnostics=diagnostics)

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
            timeout_seconds=(time_limit_ms / 1000) + 2.0,
        )
        if process.timed_out:
            return ExecutionOutcome(
                status=JudgeStatus.TLE,
                diagnostics="Docker host-side safety timeout exceeded.",
                time_ms=time_limit_ms,
            )
        if process.return_code == 137:
            return ExecutionOutcome(
                status=JudgeStatus.MLE,
                diagnostics=_process_diagnostics(process),
            )
        if process.return_code != 0:
            return ExecutionOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics=_process_diagnostics(process)
                or "Docker runtime infrastructure failed.",
            )

        status_bytes = _read_bounded_file(result_dir / "status.txt", 32)
        if status_bytes is None:
            return ExecutionOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="Container result metadata is missing.",
            )
        try:
            exit_status = int(status_bytes.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            return ExecutionOutcome(
                status=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="Container result metadata is invalid.",
            )

        output_bytes = _read_bounded_file(
            result_dir / "output.txt", output_limit_bytes + 1
        )
        if output_bytes is None:
            output_bytes = b""
        diagnostics_bytes = _read_bounded_file(
            result_dir / "diagnostics.txt", MAX_DIAGNOSTIC_CHARACTERS * 4
        )
        metrics_bytes = _read_bounded_file(result_dir / "metrics.txt", 128)
        time_ms, memory_kb = _parse_metrics(metrics_bytes)
        status = _status_from_exit_code(exit_status)
        if len(output_bytes) > output_limit_bytes:
            status = JudgeStatus.OUTPUT_LIMIT
            output_bytes = output_bytes[:output_limit_bytes]
        return ExecutionOutcome(
            status=status,
            stdout=output_bytes.decode("utf-8", errors="replace"),
            diagnostics=(
                diagnostics_bytes.decode("utf-8", errors="replace")
                if diagnostics_bytes
                else ""
            ),
            time_ms=time_ms,
            memory_kb=memory_kb,
        )


class DockerCommandFactory:
    """Build argv-only Docker commands with the mandatory sandbox boundaries."""

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
            JUDGE_IMAGE,
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
        safe_result_dir = _safe_mount_directory(result_dir)
        timeout_seconds = f"{time_limit_ms / 1000:.3f}"
        return (
            *self._security_prefix(
                container_name=container_name,
                memory_limit_mb=memory_limit_mb,
                output_limit_bytes=output_limit_bytes,
            ),
            f"--mount=type=bind,src={safe_workspace},dst=/workspace,readonly",
            f"--mount=type=bind,src={safe_input_dir},dst=/input,readonly",
            f"--mount=type=bind,src={safe_result_dir},dst=/result",
            JUDGE_IMAGE,
            "run",
            "/workspace/main",
            "/input/input.txt",
            "/result/output.txt",
            "/result/diagnostics.txt",
            "/result/metrics.txt",
            "/result/status.txt",
            timeout_seconds,
        )

    @staticmethod
    def _security_prefix(
        *, container_name: str, memory_limit_mb: int, output_limit_bytes: int
    ) -> tuple[str, ...]:
        if not _CONTAINER_NAME_PATTERN.fullmatch(container_name):
            raise ValueError("container name must contain only safe Docker name characters")
        if memory_limit_mb <= 0:
            raise ValueError("memory limit must be positive")
        if output_limit_bytes <= 0:
            raise ValueError("output limit must be positive")
        return (
            "docker",
            "run",
            "--rm",
            f"--name={container_name}",
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


def _outputs_match(actual: str, expected: str) -> bool:
    return actual.split() == expected.split()


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
        output.strip() for output in (process.stdout, process.stderr) if output.strip()
    )


def _status_from_exit_code(exit_status: int) -> JudgeStatus:
    if exit_status == 0:
        return JudgeStatus.AC
    if exit_status == 124:
        return JudgeStatus.TLE
    if exit_status == 153:
        return JudgeStatus.OUTPUT_LIMIT
    if exit_status == 137:
        return JudgeStatus.MLE
    return JudgeStatus.RUNTIME_ERROR


def _parse_metrics(metrics: bytes | None) -> tuple[int | None, int | None]:
    if metrics is None:
        return None, None
    try:
        seconds_text, memory_text = metrics.decode("ascii").split()
        return round(float(seconds_text) * 1000), int(memory_text)
    except (UnicodeDecodeError, ValueError):
        return None, None


def _read_bounded_file(path: Path, maximum_bytes: int) -> bytes | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except (FileNotFoundError, OSError):
        return None
    try:
        file_status = os.fstat(descriptor)
        if not stat.S_ISREG(file_status.st_mode):
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as result_file:
            return result_file.read(maximum_bytes)
    finally:
        os.close(descriptor)


def _container_name_from_command(command: tuple[str, ...]) -> str:
    name_argument = next(
        (argument for argument in command if argument.startswith("--name=")),
        "",
    )
    container_name = name_argument.removeprefix("--name=")
    if not _CONTAINER_NAME_PATTERN.fullmatch(container_name):
        raise ValueError("docker run command is missing a safe container name")
    return container_name


def _timeout_output(output: str | bytes | None) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
