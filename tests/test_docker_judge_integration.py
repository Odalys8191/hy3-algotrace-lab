from __future__ import annotations

import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from hy3_algotrace.contracts import JudgeStatus, ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.docker_judge import (
    DockerCliBackend,
    DockerCommandFactory,
    DockerJudge,
    release_build_command,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_CONTEXT = PROJECT_ROOT / "docker" / "judge"


def _docker_daemon_unavailable_reason() -> str | None:
    try:
        probe = subprocess.run(
            ("docker", "info", "--format", "{{.ServerVersion}}"),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return str(error)
    if probe.returncode == 0:
        return None
    return (probe.stderr or probe.stdout or "docker info failed").strip().splitlines()[-1]


@pytest.fixture(scope="module")
def docker_judge_image() -> Iterator[str]:
    unavailable_reason = _docker_daemon_unavailable_reason()
    if unavailable_reason is not None:
        pytest.skip(f"Docker daemon unavailable: {unavailable_reason}")
    required_build_environment = {
        "validator_image": os.environ.get("HY3_JUDGE_VALIDATOR_IMAGE", ""),
        "base_image": os.environ.get("HY3_JUDGE_BASE_IMAGE", ""),
        "time_package": os.environ.get("HY3_JUDGE_TIME_PACKAGE", ""),
        "util_linux_package": os.environ.get("HY3_JUDGE_UTIL_LINUX_PACKAGE", ""),
    }
    if not all(required_build_environment.values()):
        pytest.fail(
            "Docker is available but immutable build inputs are missing: "
            "HY3_JUDGE_VALIDATOR_IMAGE, HY3_JUDGE_BASE_IMAGE, "
            "HY3_JUDGE_TIME_PACKAGE, HY3_JUDGE_UTIL_LINUX_PACKAGE"
        )
    build = subprocess.run(
        release_build_command(context=IMAGE_CONTEXT, **required_build_environment),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert build.returncode == 0, build.stderr or build.stdout
    inspect = subprocess.run(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "hy3-algotrace-cpp17-judge:1.0",
        ),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert inspect.returncode == 0, inspect.stderr or inspect.stdout
    yield inspect.stdout.strip()


def _problem(*, time_limit_ms: int = 500) -> ProblemRecord:
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
        public_tests=(
            ContractTestCase(test_id="public", input_data="1\n", expected_output="2\n"),
        ),
        hidden_tests=(
            ContractTestCase(test_id="hidden", input_data="3\n", expected_output="6\n"),
        ),
        generated_tests=(
            ContractTestCase(test_id="generated", input_data="5\n", expected_output="10\n"),
        ),
        content_hash="a" * 64,
    )


@pytest.mark.parametrize(
    ("source", "expected_compile", "expected_verdict"),
    [
        (
            "#include <iostream>\nint main(){long long n;std::cin>>n;std::cout<<2*n<<'\\n';}",
            JudgeStatus.AC,
            JudgeStatus.AC,
        ),
        ("int main( {", JudgeStatus.COMPILE_ERROR, JudgeStatus.COMPILE_ERROR),
        (
            "#include <iostream>\nint main(){std::cout<<0<<'\\n';}",
            JudgeStatus.AC,
            JudgeStatus.WA,
        ),
        (
            "int main(){for(;;){} }",
            JudgeStatus.AC,
            JudgeStatus.TLE,
        ),
        (
            "#include <cstdlib>\nint main(){std::abort();}",
            JudgeStatus.AC,
            JudgeStatus.RUNTIME_ERROR,
        ),
        (
            "#include <iostream>\nint main(){for(;;)std::cout<<\"xxxxxxxxxxxxxxxx\";}",
            JudgeStatus.AC,
            JudgeStatus.OUTPUT_LIMIT,
        ),
        (
            "int main(){for(;;){auto p=new volatile char[1<<20];"
            "for(int i=0;i<(1<<20);i+=4096)p[i]=1;}}",
            JudgeStatus.AC,
            JudgeStatus.MLE,
        ),
    ],
)
def test_real_docker_judge_verdict_matrix(
    docker_judge_image: str,
    source: str,
    expected_compile: JudgeStatus,
    expected_verdict: JudgeStatus,
) -> None:
    backend = DockerCliBackend(
        command_factory=DockerCommandFactory(image=docker_judge_image)
    )
    evidence = DockerJudge(backend=backend, output_limit_bytes=4096).judge(
        _problem(), source
    )

    assert evidence.compile_status is expected_compile
    assert evidence.verdict is expected_verdict
    if expected_verdict is JudgeStatus.AC:
        assert [test.test_id for test in evidence.tests] == ["hidden", "generated"]
        assert all(test.time_ms is not None for test in evidence.tests)
        assert all(test.memory_kb is None or test.memory_kb >= 0 for test in evidence.tests)


def test_direct_docker_build_cannot_bypass_pinned_inputs(
    docker_judge_image: str,
) -> None:
    del docker_judge_image
    immutable_base = os.environ["HY3_JUDGE_BASE_IMAGE"]
    validator_image = os.environ["HY3_JUDGE_VALIDATOR_IMAGE"]
    validator_repository, validator_digest = validator_image.rsplit("@sha256:", maxsplit=1)
    exact_time = os.environ["HY3_JUDGE_TIME_PACKAGE"]
    exact_util_linux = os.environ["HY3_JUDGE_UTIL_LINUX_PACKAGE"]
    mutable_base = f"hy3-algotrace-test-base:{uuid.uuid4().hex}"
    tag = subprocess.run(
        ("docker", "tag", immutable_base, mutable_base),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert tag.returncode == 0, tag.stderr or tag.stdout
    try:
        invalid_build_args = (
            (mutable_base, exact_time, exact_util_linux),
            (immutable_base, "time", exact_util_linux),
            (immutable_base, "time=1.9-0.2; touch /tmp/hy3-injected", exact_util_linux),
            (immutable_base, exact_time, "util-linux"),
            (
                immutable_base,
                exact_time,
                "util-linux=2.38.1-5+deb12u3; touch /tmp/hy3-injected",
            ),
        )
        for base_image, time_package, util_linux_package in invalid_build_args:
            build = subprocess.run(
                (
                    "docker",
                    "build",
                    "--build-arg",
                    f"JUDGE_VALIDATOR_REPOSITORY={validator_repository}",
                    "--build-arg",
                    f"JUDGE_VALIDATOR_DIGEST={validator_digest}",
                    "--build-arg",
                    f"JUDGE_BASE_IMAGE={base_image}",
                    "--build-arg",
                    f"JUDGE_TIME_PACKAGE={time_package}",
                    "--build-arg",
                    f"JUDGE_UTIL_LINUX_PACKAGE={util_linux_package}",
                    str(IMAGE_CONTEXT),
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            assert build.returncode != 0

        for validator_arguments in (
            (),
            ("--build-arg", "JUDGE_VALIDATOR_REPOSITORY=busybox:latest"),
        ):
            build = subprocess.run(
                (
                    "docker",
                    "build",
                    *validator_arguments,
                    "--build-arg",
                    f"JUDGE_BASE_IMAGE={immutable_base}",
                    "--build-arg",
                    f"JUDGE_TIME_PACKAGE={exact_time}",
                    "--build-arg",
                    f"JUDGE_UTIL_LINUX_PACKAGE={exact_util_linux}",
                    str(IMAGE_CONTEXT),
                ),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            assert build.returncode != 0
    finally:
        subprocess.run(
            ("docker", "image", "rm", mutable_base),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )


def test_created_container_disables_daemon_logging(
    docker_judge_image: str, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "main.cpp").write_text("int main() {}", encoding="utf-8")
    command = DockerCommandFactory(image=docker_judge_image).compile_command(
        container_name=f"hy3-judge-log-{uuid.uuid4().hex}",
        workspace=workspace,
        memory_limit_mb=128,
    )
    container_id: str | None = None
    try:
        create = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert create.returncode == 0, create.stderr or create.stdout
        container_id = create.stdout.strip()
        assert re.fullmatch(r"[0-9a-f]{64}", container_id)
        inspect = subprocess.run(
            (
                "docker",
                "inspect",
                "--format={{.HostConfig.LogConfig.Type}}",
                container_id,
            ),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert inspect.returncode == 0, inspect.stderr or inspect.stdout
        assert inspect.stdout.strip() == "none"
    finally:
        if container_id is not None and re.fullmatch(r"[0-9a-f]{64}", container_id):
            subprocess.run(
                ("docker", "rm", "--force", container_id),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
