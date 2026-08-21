from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def test_runtime_command_applies_all_container_security_boundaries(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "hy3-judge-safe"
    input_dir = workspace / "input"
    result_dir = workspace / "result"
    for directory in (workspace, input_dir, result_dir):
        directory.mkdir(exist_ok=True)

    command = docker_judge.DockerCommandFactory().runtime_command(
        container_name="hy3-judge-0123456789abcdef",
        workspace=workspace,
        input_dir=input_dir,
        result_dir=result_dir,
        memory_limit_mb=128,
        time_limit_ms=750,
        output_limit_bytes=4096,
    )

    assert command[:3] == ("docker", "run", "--rm")
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges:true" in command
    assert "--pids-limit=64" in command
    assert "--cpus=1.0" in command
    assert "--memory=128m" in command
    assert "--memory-swap=128m" in command
    assert "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m" in command
    assert "--ulimit=nofile=64:64" in command
    assert "--ulimit=fsize=4096:4096" in command
    assert "--user=65532:65532" in command
    assert docker_judge.JUDGE_IMAGE in command
    assert command[-8:] == (
        "run",
        "/workspace/main",
        "/input/input.txt",
        "/result/output.txt",
        "/result/diagnostics.txt",
        "/result/metrics.txt",
        "/result/status.txt",
        "0.750",
    )


def test_command_factory_rejects_unsafe_names_and_mount_paths(tmp_path: Path) -> None:
    docker_judge = importlib.import_module("hy3_algotrace.docker_judge")
    workspace = tmp_path / "unsafe,path"
    workspace.mkdir()

    with pytest.raises(ValueError, match="safe absolute directory"):
        docker_judge.DockerCommandFactory().compile_command(
            container_name="hy3-judge-valid",
            workspace=workspace,
            memory_limit_mb=128,
        )
    with pytest.raises(ValueError, match="container name"):
        docker_judge.DockerCommandFactory().compile_command(
            container_name="../../escape",
            workspace=tmp_path,
            memory_limit_mb=128,
        )
