from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

IMMUTABLE_TEST_IMAGE = "example.invalid/hy3-judge@sha256:" + "a" * 64
BUILD_ARG_VALIDATOR = Path("docker/judge/validate-build-args.sh")
DOCKERFILE = Path("docker/judge/Dockerfile")


def test_runtime_command_applies_all_container_security_boundaries(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "hy3-judge-safe"
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    for directory in (workspace, input_dir, result_dir):
        directory.mkdir(exist_ok=True)

    command = docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE).runtime_command(
        container_name="hy3-judge-0123456789abcdef",
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=750,
        output_limit_bytes=4096,
    )

    assert command[:2] == ("docker", "create")
    assert "--rm" not in command
    assert not any(argument.startswith("--cidfile=") for argument in command)
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--pids-limit=64" in command
    assert "--cpus=1.0" in command
    assert "--memory=128m" in command
    assert "--memory-swap=128m" in command
    assert "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m" in command
    assert not any(argument.startswith("--tmpfs=/result:") for argument in command)
    assert "--ulimit=nofile=64:64" in command
    assert "--ulimit=fsize=4096:4096" in command
    assert "--user=65532:65532" in command
    assert IMMUTABLE_TEST_IMAGE in command
    assert not any("dst=/result" in argument for argument in command)
    assert command[-3:] == (
        "run",
        "/workspace/main",
        "/input/input.txt",
    )


def test_runtime_container_is_retained_for_host_inspection(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "workspace"
    input_dir = workspace / "input"
    result_dir = workspace / "host-result"
    for directory in (workspace, input_dir, result_dir):
        directory.mkdir(exist_ok=True)

    command = docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE).runtime_command(
        container_name="hy3-judge-0123456789abcdef",
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=750,
        output_limit_bytes=4096,
    )

    assert command[:2] == ("docker", "create")
    assert "--rm" not in command
    assert not any(argument.startswith("--cidfile=") for argument in command)
    assert not any(argument.startswith("--tmpfs=/result:") for argument in command)
    assert command[-3:] == ("run", "/workspace/main", "/input/input.txt")


def test_compile_container_is_created_for_cid_only_bounded_execution(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    command = docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE).compile_command(
        container_name="hy3-judge-0123456789abcdef",
        workspace=workspace,
        memory_limit_mb=128,
    )

    assert command[:2] == ("docker", "create")
    assert "--rm" not in command


def test_compile_and_runtime_create_commands_disable_daemon_logging(
    tmp_path: Path,
) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "workspace"
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    for directory in (workspace, input_dir, result_dir):
        directory.mkdir(exist_ok=True)
    factory = docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE)

    commands = (
        factory.compile_command(
            container_name="hy3-judge-compile",
            workspace=workspace,
            memory_limit_mb=128,
        ),
        factory.runtime_command(
            container_name="hy3-judge-runtime",
            workspace=workspace,
            input_dir=input_dir,
            result_dir=result_dir,
            memory_limit_mb=128,
            time_limit_ms=750,
            output_limit_bytes=4096,
        ),
    )

    for command in commands:
        assert command.count("--log-driver=none") == 1
        assert [argument for argument in command if argument.startswith("--log-driver=")] == [
            "--log-driver=none"
        ]
        assert command.index("--log-driver=none") < command.index(IMMUTABLE_TEST_IMAGE)

    with pytest.raises(ValueError, match="container name"):
        factory.compile_command(
            container_name="hy3-judge-valid --log-driver=json-file",
            workspace=workspace,
            memory_limit_mb=128,
        )


def test_runtime_runner_emits_only_contestant_stdout(tmp_path: Path) -> None:
    program = tmp_path / "program.sh"
    program.write_text("#!/bin/sh\ncat\n", encoding="utf-8")
    program.chmod(0o755)
    input_path = tmp_path / "input.txt"
    input_path.write_text("contestant output\n", encoding="utf-8")

    completed = subprocess.run(
        ("sh", "docker/judge/runner.sh", "run", str(program), str(input_path)),
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout == "contestant output\n"
    assert completed.stderr == ""


def test_command_factory_rejects_unsafe_names_and_mount_paths(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "unsafe,path"
    workspace.mkdir()

    with pytest.raises(ValueError, match="safe absolute directory"):
        docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE).compile_command(
            container_name="hy3-judge-valid",
            workspace=workspace,
            memory_limit_mb=128,
        )
    with pytest.raises(ValueError, match="container name"):
        docker_judge.DockerCommandFactory(image=IMMUTABLE_TEST_IMAGE).compile_command(
            container_name="../../escape",
            workspace=tmp_path,
            memory_limit_mb=128,
        )


def test_runtime_image_must_be_content_addressed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.delenv("HY3_JUDGE_IMAGE", raising=False)

    with pytest.raises(ValueError, match="immutable SHA-256"):
        docker_judge.DockerCommandFactory().compile_command(
            container_name="hy3-judge-valid",
            workspace=workspace,
            memory_limit_mb=128,
        )
    with pytest.raises(ValueError, match="immutable SHA-256"):
        docker_judge.DockerCommandFactory(image="hy3-judge:latest").compile_command(
            container_name="hy3-judge-valid",
            workspace=workspace,
            memory_limit_mb=128,
        )


def test_release_build_command_requires_digest_and_exact_package_versions(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")

    command = docker_judge.release_build_command(
        context=tmp_path,
        validator_image="busybox@sha256:" + "c" * 64,
        base_image="gcc@sha256:" + "b" * 64,
        time_package="time=1.9-0.2",
        util_linux_package="util-linux=2.38.1-5+deb12u3",
    )

    assert command == (
        "docker",
        "build",
        "--tag",
        docker_judge.JUDGE_BUILD_TAG,
        "--build-arg",
        "JUDGE_VALIDATOR_REPOSITORY=busybox",
        "--build-arg",
        "JUDGE_VALIDATOR_DIGEST=" + "c" * 64,
        "--build-arg",
        "JUDGE_BASE_IMAGE=gcc@sha256:" + "b" * 64,
        "--build-arg",
        "JUDGE_TIME_PACKAGE=time=1.9-0.2",
        "--build-arg",
        "JUDGE_UTIL_LINUX_PACKAGE=util-linux=2.38.1-5+deb12u3",
        str(tmp_path.resolve()),
    )
    with pytest.raises(ValueError, match="immutable SHA-256"):
        docker_judge.release_build_command(
            context=tmp_path,
            validator_image="busybox@sha256:" + "c" * 64,
            base_image="gcc:13.3.0-bookworm",
            time_package="time=1.9-0.2",
            util_linux_package="util-linux=2.38.1-5+deb12u3",
        )


@pytest.mark.parametrize(
    ("base_image", "time_package", "util_linux_package"),
    [
        ("gcc:13.3.0-bookworm", "time=1.9-0.2", "util-linux=2.38.1-5+deb12u3"),
        ("gcc@sha256:" + "b" * 64, "time", "util-linux=2.38.1-5+deb12u3"),
        ("gcc@sha256:" + "b" * 64, "time=-1;touch /tmp/pwned", "util-linux=2.38.1-5+deb12u3"),
        ("gcc@sha256:" + "b" * 64, "time=1.9-0.2", "util-linux"),
        ("gcc@sha256:" + "b" * 64, "time=1.9-0.2", "util-linux=1;touch /tmp/pwned"),
        ("gcc@sha256:" + "b" * 64 + "\x00", "time=1.9-0.2", "util-linux=1.0"),
        ("gcc@sha256:" + "b" * 64, "time=1.9-0.2\x01", "util-linux=1.0"),
        ("gcc@sha256:" + "b" * 64, "time=1.9-0.2", "util-linux=1.0\r"),
    ],
)
def test_release_build_rejects_bypass_and_injection_inputs_before_launch(
    tmp_path: Path,
    base_image: str,
    time_package: str,
    util_linux_package: str,
) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")

    with pytest.raises(ValueError):
        docker_judge.release_build_command(
            context=tmp_path,
            validator_image="busybox@sha256:" + "c" * 64,
            base_image=base_image,
            time_package=time_package,
            util_linux_package=util_linux_package,
        )


@pytest.mark.parametrize(
    "validator_image",
    [
        "",
        "busybox:latest",
        "sha256:" + "c" * 64,
        "busybox@sha256:" + "c" * 63,
        "busybox@sha256:" + "C" * 64,
        "busybox@sha256:" + "c" * 64 + "\n",
        "busybox@sha256:" + "c" * 64 + "\r",
        "busybox@sha256:" + "c" * 64 + "\x01",
        "busybox@sha256:" + "c" * 64 + "\x00",
    ],
)
def test_release_build_requires_repository_pinned_validator_image(
    tmp_path: Path, validator_image: str
) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")

    with pytest.raises(ValueError, match="validator image"):
        docker_judge.release_build_command(
            context=tmp_path,
            validator_image=validator_image,
            base_image="gcc@sha256:" + "b" * 64,
            time_package="time=1.9-0.2",
            util_linux_package="util-linux=2.38.1-5+deb12u3",
        )


@pytest.mark.parametrize(
    ("base_image", "time_package", "util_linux_package", "expected_return_code"),
    [
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2",
            "util-linux=2.38.1-5+deb12u3",
            0,
        ),
        ("gcc:13.3.0-bookworm", "time=1.9-0.2", "util-linux=2.38.1-5+deb12u3", 1),
        ("gcc@sha256:" + "b" * 64, "time", "util-linux=2.38.1-5+deb12u3", 1),
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2; touch /tmp/hy3-injected",
            "util-linux=2.38.1-5+deb12u3",
            1,
        ),
        ("gcc@sha256:" + "b" * 64, "time=1.9-0.2", "util-linux", 1),
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2",
            "util-linux=2.38.1-5+deb12u3; touch /tmp/hy3-injected",
            1,
        ),
        (
            "gcc@sha256:" + "b" * 64 + "\n",
            "time=1.9-0.2",
            "util-linux=2.38.1-5+deb12u3",
            1,
        ),
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2\n",
            "util-linux=2.38.1-5+deb12u3",
            1,
        ),
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2\r",
            "util-linux=2.38.1-5+deb12u3",
            1,
        ),
        (
            "gcc@sha256:" + "b" * 64,
            "time=1.9-0.2\x01",
            "util-linux=2.38.1-5+deb12u3",
            1,
        ),
    ],
)
def test_dockerfile_build_arg_validator_fails_closed_without_shell_injection(
    tmp_path: Path,
    base_image: str,
    time_package: str,
    util_linux_package: str,
    expected_return_code: int,
) -> None:
    injection_marker = tmp_path / "hy3-injected"
    completed = subprocess.run(
        (
            "sh",
            str(BUILD_ARG_VALIDATOR),
            base_image,
            time_package.replace("/tmp/hy3-injected", str(injection_marker)),
            util_linux_package.replace("/tmp/hy3-injected", str(injection_marker)),
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == expected_return_code
    assert not injection_marker.exists()


def test_dockerfile_has_a_pinned_validator_stage_and_final_stage_dependency() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    validator_from = (
        "FROM ${JUDGE_VALIDATOR_REPOSITORY}@sha256:${JUDGE_VALIDATOR_DIGEST} "
        "AS input-validator"
    )
    final_from = "FROM ${JUDGE_BASE_IMAGE} AS judge"
    final_dependency = (
        "COPY --from=input-validator /validation/build-args "
        "/usr/local/share/hy3-build-args"
    )

    assert validator_from in dockerfile
    assert final_from in dockerfile
    assert final_dependency in dockerfile
    assert dockerfile.index(validator_from) < dockerfile.index(final_from)
    assert dockerfile.index(final_dependency) > dockerfile.index(final_from)
    assert "ARG JUDGE_VALIDATOR_REPOSITORY=" not in dockerfile
    assert "ARG JUDGE_VALIDATOR_DIGEST=" not in dockerfile
