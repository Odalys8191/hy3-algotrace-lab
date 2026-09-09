"""Validate the authored smoke assets without executing a submitted program."""

import itertools
import shutil
import subprocess
from pathlib import Path

import pytest

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import ProblemOracle, ReasoningStage, SolutionTrace

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/smoke/cf-1613-c"


def test_smoke_contracts_and_reference_identity() -> None:
    reference = (EXAMPLE / "reference.cpp").read_text()
    oracle = ProblemOracle.model_validate_json((EXAMPLE / "oracle.json").read_text())
    trace = SolutionTrace.model_validate_json((EXAMPLE / "gold_trace.json").read_text())
    assert oracle.problem_id == trace.problem_id == "cf-1613-c"
    assert trace.code == reference
    assert oracle.reference_solution_hash == sha256_json(reference)
    assert [step.stage for step in trace.steps] == list(ReasoningStage)
    assert [step.step_number for step in trace.steps] == list(range(1, 7))


def test_authored_cpp_at_compile_time(tmp_path: Path) -> None:
    compiler = shutil.which("clang++") or shutil.which("g++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable; no Judge result is implied")
    source = (EXAMPLE / "reference.cpp").read_text()
    checks = ["#define main authored_example_main", source, "#undef main"]
    # Independent oracle: explicitly enumerate the union of poisoned integer seconds.
    for size in range(1, 7):
        for times in itertools.combinations(range(1, 7), size):
            name = "a_" + "_".join(map(str, times))
            checks.append(f"constexpr long long {name}[] = {{{','.join(map(str, times))}}};")
            for health in range(1, 13):
                expected = next(
                    k
                    for k in range(1, health + 1)
                    if len({second for a in times for second in range(a, a + k)}) >= health
                )
                checks.append(
                    f"static_assert(minimum_strength({name}, {size}, {health}) == {expected});"
                )
    checks.extend(
        [
            "constexpr long long single[] = {1000000000};",
            "static_assert(minimum_strength(single, 1, 1000000000000000000LL)"
            " == 1000000000000000000LL);",
            "constexpr long long far[] = {1, 1000000000};",
            "static_assert(minimum_strength(far, 2, 1000000000000000000LL)"
            " == 999999999000000001LL);",
            "constexpr long long sample[] = {3, 25, 64, 1337};",
            "static_assert(minimum_strength(sample, 4, 1000) == 470);",
        ]
    )
    translation_unit = tmp_path / "authored_compile_checks.cpp"
    translation_unit.write_text("\n".join(checks))
    result = subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
            str(translation_unit),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
