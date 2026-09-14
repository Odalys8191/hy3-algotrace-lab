"""Public-spec authoring checks; no private test material belongs in this file."""

import importlib.util
import runpy
import subprocess
from itertools import combinations
from pathlib import Path


def test_fixed_point_boundary_mutant_counts_an_impossible_singleton(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = runpy.run_path(str(root / "scripts/formal_authoring_specs_b.py"))["SPECS"]["cf-1575-l"]
    mutation = spec["mutants"][0]
    codes = [spec["code"], spec["code"].replace(mutation["old"], mutation["new"], 1)]
    answers = []
    for index, code in enumerate(codes):
        source = tmp_path / f"fixed-{index}.cpp"
        source.write_text(
            code.replace(
                "#include <bits/stdc++.h>",
                "#include <iostream>\n#include <vector>\n#include <algorithm>\n#include <utility>",
            )
        )
        binary = tmp_path / f"fixed-{index}"
        subprocess.run(
            ["c++", "-std=c++17", "-O2", str(source), "-o", str(binary)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result = subprocess.run(
            [str(binary)], input="1\n2\n", text=True, capture_output=True, check=True, timeout=10
        )
        answers.append(result.stdout.split())
    assert answers[0] == ["0"]  # Keeping 2 at position 1 or deleting it yields no fixed point.
    assert answers[1] != answers[0]


def test_noble_boundary_mutant_has_an_edgeless_graph_witness(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = runpy.run_path(str(root / "scripts/formal_authoring_specs_b.py"))["SPECS"]["cf-1549-c"]
    mutation = spec["mutants"][1]
    codes = [spec["code"], spec["code"].replace(mutation["old"], mutation["new"], 1)]
    answers = []
    for index, code in enumerate(codes):
        source = tmp_path / f"nobles-{index}.cpp"
        source.write_text(
            code.replace(
                "#include <bits/stdc++.h>",
                "#include <iostream>\n#include <vector>\n#include <algorithm>",
            )
        )
        binary = tmp_path / f"nobles-{index}"
        subprocess.run(
            ["c++", "-std=c++17", "-O2", str(source), "-o", str(binary)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result = subprocess.run(
            [str(binary)],
            input="2 0\n1\n3\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=10,
        )
        answers.append(result.stdout.split())
    assert answers[0] == ["2"]  # Both isolated nobles survive.
    assert answers[1] != answers[0]


def test_chip_reference_matches_public_example_exact_spelling(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = runpy.run_path(str(root / "scripts/formal_authoring_specs_a.py"))["SPECS"]["cf-1553-b"]
    source = tmp_path / "chip.cpp"
    source.write_text(
        spec["code"].replace(
            "#include <bits/stdc++.h>",
            "#include <iostream>\n#include <vector>\n#include <string>\n#include <algorithm>",
        )
    )
    binary = tmp_path / "chip"
    subprocess.run(
        ["c++", "-std=c++17", "-O2", str(source), "-o", str(binary)],
        check=True,
        capture_output=True,
        timeout=30,
    )
    result = subprocess.run(
        [str(binary)],
        text=True,
        capture_output=True,
        check=True,
        input="6\nabcdef\ncdedcb\naaa\naaaaa\naab\nbaaa\nab\nb\nabcdef\nabcdef\nba\nbaa\n",
        timeout=10,
    )
    assert result.stdout.split() == ["Yes", "Yes", "No", "Yes", "Yes", "No"]


def test_coin_inventory_mutants_have_public_semantic_witnesses(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = runpy.run_path(str(root / "scripts/formal_authoring_specs_a.py"))["SPECS"]["cf-1620-d"]
    prices = [a for n in range(1, 9) for a in combinations(range(1, 9), n)]
    inventories = sorted(
        (
            one + two + three,
            {
                u + 2 * v + 3 * w
                for u in range(one + 1)
                for v in range(two + 1)
                for w in range(three + 1)
            },
        )
        for one in range(9)
        for two in range(5)
        for three in range(4)
    )
    expected = [min(count for count, sums in inventories if set(a) <= sums) for a in prices]
    inputs = (
        str(len(prices)) + "\n" + "".join(f"{len(a)}\n{' '.join(map(str, a))}\n" for a in prices)
    )
    sources = [spec["code"]] + [
        spec["code"].replace(m["old"], m["new"], 1) for m in spec["mutants"]
    ]
    for index, code in enumerate(sources):
        # macOS lacks bits/stdc++.h; only expand this convenience header.
        source = tmp_path / f"coin-{index}.cpp"
        source.write_text(
            code.replace(
                "#include <bits/stdc++.h>",
                "#include <iostream>\n#include <vector>\n#include <algorithm>\n#include <climits>",
            )
        )
        binary = tmp_path / f"coin-{index}"
        subprocess.run(
            ["c++", "-std=c++17", "-O2", str(source), "-o", str(binary)],
            check=True,
            capture_output=True,
            timeout=30,
        )
        result = subprocess.run(
            [str(binary)], input=inputs, text=True, capture_output=True, check=True, timeout=10
        )
        observed = list(map(int, result.stdout.split()))
        assert len(observed) == len(expected)
        if index == 0:
            assert observed == expected
        else:
            assert observed != expected, f"mutant {index} has no semantic witness"


def test_missing_connectivity_subtraction_is_an_algorithm_error():
    root = Path(__file__).resolve().parents[1]
    spec = runpy.run_path(str(root / "scripts/formal_authoring_specs_b.py"))["SPECS"]["cf-1608-d"]
    assert spec["mutants"][0]["taxonomy"] == "algorithm_logic"


def test_authored_sources_have_reproducible_semantic_mutations() -> None:
    root = Path(__file__).resolve().parents[1]
    specs = {}
    for group in ("a", "b"):
        path = root / "scripts" / f"formal_authoring_specs_{group}.py"
        spec = importlib.util.spec_from_file_location(f"authoring_{group}", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        specs.update(module.SPECS)
    assert len(specs) == 30
    for pid, item in specs.items():
        assert pid.startswith("cf-")
        assert "int main(" in item["code"]
        assert len(item["steps"]) >= 4
        assert item["proof"] and item["invariants"] and item["traps"]
        mutants = item["mutants"]
        assert len(mutants) == 2
        outputs = {item["code"]}
        for mutant in mutants:
            assert item["code"].count(mutant["old"]) == 1, pid
            outputs.add(item["code"].replace(mutant["old"], mutant["new"], 1))
            assert mutant["claim"] and mutant["taxonomy"]
        assert len(outputs) == 3
