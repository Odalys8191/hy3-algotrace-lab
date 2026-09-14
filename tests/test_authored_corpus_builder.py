from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from hy3_algotrace.contracts import OutputComparison, SolutionTrace, StepStatus
from hy3_algotrace.corpus import CorpusManifest, CorpusSampleKind, ProjectBundleManifest
from hy3_algotrace.dataset_models import CandidateReviewSet

REPO = Path(__file__).resolve().parents[1]


def test_trace_stages_contain_the_claimed_proof_and_complexity(tmp_path):
    from hy3_algotrace.contracts import ReasoningStage

    inputs = _inputs(tmp_path)
    pid = next(iter(inputs["specs"]))
    spec = inputs["specs"][pid]
    module = _load(REPO / "scripts/prepare_authored_corpus.py", "stage_builder")
    trace = module._trace(pid, f"{pid}-gold", spec, spec["code"])
    stages = {step.stage: step for step in trace.steps}
    assert spec["proof"] in stages[ReasoningStage.CORRECTNESS_ARGUMENT].claim
    assert spec["time"] in stages[ReasoningStage.COMPLEXITY_ANALYSIS].claim
    assert spec["space"] in stages[ReasoningStage.COMPLEXITY_ANALYSIS].claim
    assert set(stages) == set(ReasoningStage)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(root: Path) -> dict[str, Any]:
    support = _load(REPO / "tests/test_dataset_corpus.py", "authoring_test_support")
    chain, records = support._verified_selection_chain(root, hidden_input_data="PRIVATE_SENTINEL")
    reviews = {}
    for split in ("validation", "test"):
        review_set = CandidateReviewSet.model_validate_json(
            (root / f"formal-chain-reviews-{split}.json").read_bytes()
        )
        reviews.update({artifact.review.problem_id: artifact for artifact in review_set.artifacts})
    spec = {
        "code": "int main(){int a=1;return 0;}\n",
        "algorithm": "Return the value.",
        "proof": "The return value is zero.",
        "time": "O(1)",
        "space": "O(1)",
        "steps": ["Read input.", "Preserve the value.", "Return the value.", "Use exact integers."],
        "invariants": ["The value is preserved."],
        "traps": ["Changing the value."],
        "edges": ["Zero."],
        "mutants": [
            {
                "old": "return 0",
                "new": "return 1",
                "claim": "One equals zero.",
                "taxonomy": "algorithm_logic",
            },
            {
                "old": "return 0",
                "new": "return 2",
                "claim": "Two equals zero.",
                "taxonomy": "boundary_error",
            },
        ],
    }
    return dict(
        selection=chain.selection,
        records=records,
        reviews=reviews,
        specs={pid: json.loads(json.dumps(spec)) for pid in records},
        source_files={
            "prepare_authored_corpus.py": b"# builder\n",
            "formal_authoring_specs_a.py": b"# original sources\n",
        },
    )


def test_builder_creates_hash_linked_105_controls_and_preserves_private_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inputs = _inputs(tmp_path)
    module = _load(REPO / "scripts/prepare_authored_corpus.py", "authored_builder")
    real_temporary_directory = module.tempfile.TemporaryDirectory
    temporary_roots: list[object] = []
    expected_temporary_root = Path(module.tempfile.gettempdir()).resolve()

    def portable_temporary_directory(*args, **kwargs):
        temporary_roots.append(kwargs.get("dir"))
        assert kwargs.get("dir") == expected_temporary_root
        return real_temporary_directory(*args, **kwargs)

    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", portable_temporary_directory)
    output = tmp_path / "authored-v1"
    result = module.assemble_authored_corpus(out_dir=output, **inputs)
    assert temporary_roots == [expected_temporary_root]
    corpus = CorpusManifest.model_validate_json((output / "corpus-pending.json").read_bytes())
    bundles = ProjectBundleManifest.model_validate_json(
        (output / "bundle-manifest.json").read_bytes()
    )
    assert len(corpus.samples) == 105
    assert result["sample_count"] == 105
    assert corpus.natural_run_config.target_sample_count == 60
    assert corpus.natural_run_config.model_name == "hy3"
    assert corpus.natural_run_config.endpoint_url == "https://tokenhub.tencentmaas.com/v1"
    cells = set()
    selected = {entry.problem_id: entry for entry in inputs["selection"].entries}
    for sample in corpus.samples:
        trace = SolutionTrace.model_validate_json((output / sample.trace.path).read_bytes())
        assert len({step.stage for step in trace.steps}) >= 4
        if sample.kind is CorpusSampleKind.GOLD:
            assert all(step.status is StepStatus.CORRECT for step in trace.steps)
        else:
            assert sample.first_error_step_id == "s2"
            assert trace.steps[1].status is StepStatus.INCORRECT
        if sample.kind is CorpusSampleKind.PARADOX:
            row = selected[sample.problem_id]
            cells.add((row.topic, row.rating_band))
        assert "PRIVATE_SENTINEL" not in (output / sample.trace.path).read_text()
    assert len(cells) == 15
    for bundle in bundles.bundles:
        gold = next(
            sample
            for sample in corpus.samples
            if sample.problem_id == bundle.problem_id and sample.kind is CorpusSampleKind.GOLD
        )
        assert (output / gold.trace.path).read_bytes() == (
            output / bundle.gold_trace.path
        ).read_bytes()
        assert bundle.authoring_attestation.human_review_performed is False
        assert bundle.checker_json is None
    assert not (output / "corpus/natural").exists()
    assert "PRIVATE_SENTINEL" not in (output / "authored-provenance.json").read_text()
    assert (output / "private/problem-records" / f"{corpus.samples[0].problem_id}.json").is_file()
    first_bytes = (output / "corpus-pending.json").read_bytes()
    with pytest.raises(module.AuthoringBuildError, match="exists"):
        module.assemble_authored_corpus(out_dir=output, **inputs)
    assert (output / "corpus-pending.json").read_bytes() == first_bytes


@pytest.mark.parametrize("problem", ["bad_mutation", "missing_spec", "wrong_record", "comparison"])
def test_builder_rejects_invalid_sources_before_creating_output(
    tmp_path: Path, problem: str
) -> None:
    inputs = _inputs(tmp_path)
    module = _load(REPO / "scripts/prepare_authored_corpus.py", "authored_builder")
    pid = next(iter(inputs["specs"]))
    if problem == "bad_mutation":
        inputs["specs"][pid]["mutants"][0]["old"] = "not present"
    elif problem == "missing_spec":
        inputs["specs"].pop(pid)
    elif problem == "wrong_record":
        inputs["records"][pid] = inputs["records"][pid].model_copy(update={"title": "forged"})
    else:
        artifact = inputs["reviews"][pid]
        inputs["reviews"][pid] = artifact.model_copy(
            update={
                "review": artifact.review.model_copy(
                    update={"output_comparison": OutputComparison.CASE_INSENSITIVE}
                )
            }
        )
    output = tmp_path / "must-not-exist"
    with pytest.raises(module.AuthoringBuildError):
        module.assemble_authored_corpus(out_dir=output, **inputs)
    assert not output.exists()


def test_builder_preserves_one_pinned_case_insensitive_checker(tmp_path):
    from hy3_algotrace.artifacts import sha256_json
    from hy3_algotrace.corpus import bundle_output_comparisons
    from hy3_algotrace.dataset_models import CandidateReviewArtifact, FrozenSelectionManifest

    inputs = _inputs(tmp_path)
    pid = inputs["selection"].entries[0].problem_id
    old = inputs["reviews"][pid]
    review = CandidateReviewArtifact.create(
        raw_row_hash=old.raw_row_hash,
        review=old.review.model_copy(
            update={"output_comparison": OutputComparison.CASE_INSENSITIVE}
        ),
    )
    inputs["reviews"][pid] = review
    selection = inputs["selection"].model_dump(mode="json")
    selection["entries"][0]["review_hash"] = review.content_hash
    selection["content_hash"] = sha256_json(
        {k: v for k, v in selection.items() if k != "content_hash"}
    )
    inputs["selection"] = FrozenSelectionManifest.model_validate_json(json.dumps(selection))
    module = _load(REPO / "scripts/prepare_authored_corpus.py", "builder_comparison")
    output = tmp_path / "comparison"
    module.assemble_authored_corpus(out_dir=output, **inputs)
    bundles = ProjectBundleManifest.model_validate_json(
        (output / "bundle-manifest.json").read_bytes()
    )
    comparisons = bundle_output_comparisons(bundles, output)
    assert comparisons[pid] is OutputComparison.CASE_INSENSITIVE
    assert sum(value is OutputComparison.EXACT for value in comparisons.values()) == 29
    for path in (output / "private/problem-records").glob("*.json"):
        assert path.stat().st_mode & 0o077 == 0
    assert output.stat().st_mode & 0o077 == 0


def test_builder_rejects_forbidden_spec_before_publication(tmp_path):
    inputs = _inputs(tmp_path)
    inputs["specs"][next(iter(inputs["specs"]))]["proof"] = "Use hidden_tests to infer the answer."
    module = _load(REPO / "scripts/prepare_authored_corpus.py", "builder_privacy")
    output = tmp_path / "invalid"
    with pytest.raises(module.AuthoringBuildError):
        module.assemble_authored_corpus(out_dir=output, **inputs)
    assert not output.exists()
