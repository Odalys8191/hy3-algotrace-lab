from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from hy3_algotrace.contracts import JudgeStatus, ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.docker_judge import JUDGE_IMAGE, DockerJudge

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
def docker_judge_image() -> Iterator[None]:
    unavailable_reason = _docker_daemon_unavailable_reason()
    if unavailable_reason is not None:
        pytest.skip(f"Docker daemon unavailable: {unavailable_reason}")
    build = subprocess.run(
        ("docker", "build", "--tag", JUDGE_IMAGE, str(IMAGE_CONTEXT)),
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert build.returncode == 0, build.stderr or build.stdout
    yield


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
    ],
)
def test_real_docker_judge_verdict_matrix(
    docker_judge_image: None,
    source: str,
    expected_compile: JudgeStatus,
    expected_verdict: JudgeStatus,
) -> None:
    del docker_judge_image
    evidence = DockerJudge(output_limit_bytes=4096).judge(_problem(), source)

    assert evidence.compile_status is expected_compile
    assert evidence.verdict is expected_verdict
    if expected_verdict is JudgeStatus.AC:
        assert [test.test_id for test in evidence.tests] == ["hidden", "generated"]
        assert all(test.time_ms is not None for test in evidence.tests)
        assert all(test.memory_kb is not None for test in evidence.tests)
