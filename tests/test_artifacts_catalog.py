from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hy3_algotrace.artifacts import (
    ArtifactExistsError,
    ArtifactStore,
    UnsafeArtifactPathError,
    canonical_json_bytes,
    sha256_json,
)
from hy3_algotrace.catalog import (
    BundleValidationError,
    ProblemBundle,
    ProblemCatalog,
    determine_primary_topic,
    validate_problem_record,
)
from hy3_algotrace.codecontests import (
    CodeContestsImportError,
    build_selection_manifest,
    load_codecontests_json,
    select_formal_problems,
    validate_selection_manifest,
)
from hy3_algotrace.contracts import (
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReasoningStep,
    SolutionTrace,
    StepStatus,
    Topic,
)


def record_payload(
    problem_id: str = "cf-1000-a", *, topic: Topic = Topic.GREEDY, rating: int = 1400
) -> dict[str, object]:
    tags = {
        Topic.CONSTRUCTION_SIMULATION: ("constructive algorithms",),
        Topic.GREEDY: ("greedy",),
        Topic.BINARY_SEARCH: ("binary search",),
        Topic.DYNAMIC_PROGRAMMING: ("dp",),
        Topic.GRAPH: ("graphs",),
    }[topic]
    payload: dict[str, object] = {
        "schema_version": "1.2",
        "problem_id": problem_id,
        "title": "Largest value",
        "statement_en": "Read two integers and print the larger one.",
        "source_url": "https://codeforces.com/problemset/problem/1000/A",
        "attribution": "Codeforces problem statement; imported through CodeContests.",
        "source": "codeforces",
        "cf_contest_id": 1000,
        "cf_index": "A",
        "cf_tags": list(tags),
        "source_split": "validation",
        "is_description_translated": False,
        "input_file": "",
        "output_file": "",
        "topic": topic.value,
        "rating": rating,
        "language": "cpp17",
        "time_limit_ms": 1000,
        "memory_limit_mb": 256,
        "public_tests": [
            {
                "schema_version": "1.2",
                "test_id": "public-1",
                "input_data": "1 2\n",
                "expected_output": "2\n",
            }
        ],
        "hidden_tests": [
            {
                "schema_version": "1.2",
                "test_id": "hidden-1",
                "input_data": "4 3\n",
                "expected_output": "4\n",
            }
        ],
        "generated_tests": [],
    }
    payload["content_hash"] = sha256_json(payload)
    return payload


def record(**changes: object) -> ProblemRecord:
    payload = record_payload()
    problem_id = changes.get("problem_id")
    if isinstance(problem_id, str):
        match = re.fullmatch(r"cf-(\d+)-(.+)", problem_id)
        if match:
            contest_id, index = match.groups()
            payload["cf_contest_id"] = int(contest_id)
            payload["cf_index"] = index.upper()
            payload["source_url"] = (
                f"https://codeforces.com/problemset/problem/{contest_id}/{index.upper()}"
            )
    payload.update(changes)
    payload["content_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    return ProblemRecord.model_validate(payload)


def trace(problem_id: str) -> SolutionTrace:
    return SolutionTrace(
        trace_id=f"{problem_id}-gold",
        problem_id=problem_id,
        steps=(
            ReasoningStep(
                step_id="understand",
                step_number=1,
                stage=ReasoningStage.PROBLEM_UNDERSTANDING,
                claim="The task asks for the maximum of two integers.",
                rationale="The statement defines two input values.",
                status=StepStatus.CORRECT,
            ),
        ),
        problem_understanding="Compare two integers.",
        algorithm="Use one maximum comparison.",
        correctness_argument="The maximum is the requested value.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("The inputs can be equal.",),
        code="#include <iostream>\nint main() {}\n",
    )


def bundle(problem: ProblemRecord | None = None) -> ProblemBundle:
    problem = problem or record()
    reference = "#include <iostream>\nint main() { return 0; }\n"
    return ProblemBundle(
        record=problem,
        oracle=ProblemOracle(
            problem_id=problem.problem_id,
            accepted_algorithm_families=("comparison",),
            key_invariants=("The greater value is output.",),
            complexity_ceiling="O(1)",
            known_traps=("Equal values.",),
            adversarial_cases=("4 3",),
            decisive_facts=("Only two values are provided.",),
            reference_solution_hash=sha256_json(reference),
        ),
        reference_cpp=reference,
        gold_trace=trace(problem.problem_id),
    )


def test_canonical_json_and_hash_are_independent_of_mapping_order() -> None:
    first = {"answer": [3, {"z": "é", "a": True}], "count": 2}
    second = {"count": 2, "answer": [3, {"a": True, "z": "é"}]}

    assert canonical_json_bytes(first) == b'{"answer":[3,{"a":true,"z":"\xc3\xa9"}],"count":2}'
    assert sha256_json(first) == sha256_json(second)


def test_artifact_store_creates_hash_addressed_json_once(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    created = store.create("run", {"schema_version": "1.2", "answer": 7})

    assert created.path == Path("run") / f"{created.content_hash}.json"
    assert store.read_json(created.path) == {"answer": 7, "schema_version": "1.2"}
    with pytest.raises(ArtifactExistsError):
        store.create("run", {"answer": 7, "schema_version": "1.2"})


def test_artifact_store_rejects_traversal_and_requested_overwrite(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(UnsafeArtifactPathError):
        store.write_json("../outside.json", {"schema_version": "1.2"})
    store.write_json("safe/value.json", {"schema_version": "1.2"})
    with pytest.raises(ArtifactExistsError):
        store.write_json("safe/value.json", {"schema_version": "1.2"})


def test_bundle_validation_requires_formal_provenance_and_unambiguous_topic() -> None:
    valid = record()
    validate_problem_record(valid)
    assert determine_primary_topic(("greedy", "math")) is Topic.GREEDY

    with pytest.raises(BundleValidationError, match="hidden"):
        validate_problem_record(record(hidden_tests=()))
    with pytest.raises(BundleValidationError, match="unambiguous"):
        validate_problem_record(record(cf_tags=("greedy", "dp")))
    with pytest.raises(BundleValidationError, match="resource"):
        validate_problem_record(record(time_limit_ms=20_000))


def test_catalog_loads_bundles_rejects_duplicate_ids_and_redacts_secrets(tmp_path: Path) -> None:
    first = bundle()
    second_record = record(problem_id="cf-1001-a")
    second = bundle(second_record)
    for dirname, item in (("first", first), ("second", second)):
        directory = tmp_path / dirname
        directory.mkdir()
        problem_json = canonical_json_bytes(item.record.model_dump(mode="json"))
        oracle_json = canonical_json_bytes(item.oracle.model_dump(mode="json"))
        trace_json = canonical_json_bytes(item.gold_trace.model_dump(mode="json"))
        (directory / "problem.json").write_bytes(problem_json)
        (directory / "oracle.json").write_bytes(oracle_json)
        (directory / "reference.cpp").write_text(item.reference_cpp, encoding="utf-8")
        (directory / "gold_trace.json").write_bytes(trace_json)

    catalog = ProblemCatalog.from_directory(tmp_path)
    public = catalog.get_public_detail(first.record.problem_id)
    assert [summary.problem_id for summary in catalog.list_problems()] == [
        "cf-1000-a",
        "cf-1001-a",
    ]
    assert public["problem_id"] == first.record.problem_id
    assert "hidden_tests" not in public
    assert "generated_tests" not in public
    with pytest.raises(BundleValidationError, match="duplicate"):
        ProblemCatalog((first, bundle(record(problem_id=first.record.problem_id))))


def test_bundle_rejects_mismatched_oracle_reference_and_gold_trace() -> None:
    item = bundle()
    with pytest.raises(BundleValidationError, match="reference"):
        ProblemBundle(
            record=item.record,
            oracle=item.oracle,
            reference_cpp="int main() {}",
            gold_trace=item.gold_trace,
        )
    with pytest.raises(BundleValidationError, match="gold trace"):
        ProblemBundle(
            record=item.record,
            oracle=item.oracle,
            reference_cpp=item.reference_cpp,
            gold_trace=trace("another-problem"),
        )


def test_codecontests_json_and_jsonl_import_reject_invalid_entries_and_selects_quotas(
    tmp_path: Path,
) -> None:
    entries: list[dict[str, object]] = []
    topics = list(Topic)
    ratings = (1300, 1700, 2100)
    for topic in topics:
        for rating in ratings:
            for number in range(2):
                entries.append(
                    _formal_payload(1000 + len(entries), topic=topic, rating=rating)
                )
    json_path = tmp_path / "records.json"
    json_path.write_text(json.dumps(entries), encoding="utf-8")
    jsonl_path = tmp_path / "records.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")

    assert len(load_codecontests_json(json_path, split="validation")) == 30
    assert len(load_codecontests_json(jsonl_path, split="validation")) == 30
    selected = select_formal_problems(load_codecontests_json(json_path, split="validation"))
    assert len(selected) == 30
    assert {item.topic for item in selected} == set(topics)
    with pytest.raises(CodeContestsImportError, match="quota"):
        select_formal_problems(selected[:-1])


def test_selection_manifest_must_match_the_frozen_quota_and_component_hashes() -> None:
    bundles: list[ProblemBundle] = []
    counter = 1000
    for topic in Topic:
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                problem = ProblemRecord.model_validate(_formal_payload(counter, topic, rating))
                bundles.append(bundle(problem))
                counter += 1
    manifest = build_selection_manifest(bundles).model_dump(mode="json")

    assert validate_selection_manifest(manifest, bundles) == tuple(bundles)
    manifest["bundles"] = manifest["bundles"][:-1]
    with pytest.raises(CodeContestsImportError, match="bundles"):
        validate_selection_manifest(manifest, bundles)


def _formal_payload(contest_id: int, topic: Topic, rating: int) -> dict[str, object]:
    payload = record_payload(problem_id=f"cf-{contest_id}-a", topic=topic, rating=rating)
    payload["cf_contest_id"] = contest_id
    payload["cf_index"] = "A"
    payload["source_url"] = f"https://codeforces.com/problemset/problem/{contest_id}/A"
    payload["content_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    return payload
