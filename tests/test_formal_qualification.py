from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from hy3_algotrace.artifacts import ArtifactStore, canonical_json_bytes, sha256_json
from hy3_algotrace.benchmark_models import (
    BenchmarkConfig,
    BenchmarkParameter,
    BenchmarkSampleSpec,
    FormalIntegrationCandidate,
    HumanConfirmedLabel,
    HumanConfirmedLabelSet,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    SampleKind,
    VerifiedDataEvidence,
)
from hy3_algotrace.contracts import JudgeEvidence, JudgeStatus, PerTestEvidence
from hy3_algotrace.corpus import (
    CorpusSampleKind,
    CorpusStatus,
    FrozenModelParameter,
    NaturalRunConfig,
    NaturalRunStatus,
    build_corpus_manifest,
    build_project_bundle_manifest,
)
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    ConversionTool,
    DatasetFormat,
    ReviewArtifactAsset,
    ReviewArtifactManifest,
    SelectionReplayReceipt,
    validate_acquired_assets,
)
from hy3_algotrace.differential import (
    JudgeCaseKind,
    JudgeSourceCase,
    validate_formal_corpus_judge_cases,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _corpus_support() -> ModuleType:
    path = REPOSITORY_ROOT / "tests/test_dataset_corpus.py"
    spec = importlib.util.spec_from_file_location("formal_corpus_test_support", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class FormalFixture:
    root: Path
    inputs: dict[str, Any]
    candidate_path: Path
    benchmark_root: Path
    output_root: Path
    script_environment: dict[str, str]

    def bridge_inputs(self) -> object:
        module = importlib.import_module("hy3_algotrace.formal_qualification")
        return module.FormalQualificationInputs(**self.inputs)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _build_fixture(root: Path) -> FormalFixture:
    support = _corpus_support()
    data_root = root / "formal-data"
    data_root.mkdir(parents=True)
    selection_chain, records = support._verified_selection_chain(data_root)
    selection = selection_chain.selection

    raw_paths = {
        split: data_root / f"formal-chain-{split}.json" for split in ("validation", "test")
    }
    acquisition = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=tuple(
            AcquisitionAsset(
                split=split,
                url=f"https://example.invalid/codecontests-{split}.json",
                byte_length=len(raw_paths[split].read_bytes()),
                sha256=hashlib.sha256(raw_paths[split].read_bytes()).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            )
            for split in ("validation", "test")
        ),
        converter=ConversionTool(name="formal-chain-json", version="1"),
        third_party_terms_acknowledged=True,
    )
    acquisition_validation = validate_acquired_assets(acquisition, raw_paths)
    review_paths = {
        split: data_root / f"formal-chain-reviews-{split}.json" for split in ("validation", "test")
    }
    review_manifest = ReviewArtifactManifest.create(
        tuple(
            ReviewArtifactAsset(
                split=split,
                logical_id=f"codecontests-review-{split}",
                byte_length=len(review_paths[split].read_bytes()),
                sha256=hashlib.sha256(review_paths[split].read_bytes()).hexdigest(),
            )
            for split in ("validation", "test")
        )
    )
    bundle_manifest = build_project_bundle_manifest(
        selection, support._bundle_entries(data_root, selection)
    )
    baseline_controlled = support._controlled_samples(data_root, selection, bundle_manifest)
    bundles_by_id = {bundle.problem_id: bundle for bundle in bundle_manifest.bundles}
    controlled = tuple(
        sample for sample in baseline_controlled if sample.kind is not CorpusSampleKind.PARADOX
    ) + tuple(
        support._sample(
            data_root,
            sample_id=f"{entry.problem_id}-paradox-formal",
            problem_id=entry.problem_id,
            kind=CorpusSampleKind.PARADOX,
            code_text=(data_root / bundles_by_id[entry.problem_id].reference_cpp.path).read_text(
                encoding="utf-8"
            ),
        )
        for entry in selection.entries[::2]
    )
    natural = tuple(
        support._sample(
            data_root,
            sample_id=f"{entry.problem_id}-natural-{number}",
            problem_id=entry.problem_id,
            kind=CorpusSampleKind.NATURAL,
        )
        for entry in selection.entries
        for number in (1, 2)
    )
    natural_config = NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=tuple(entry.problem_id for entry in selection.entries),
        prompt_version="natural-v1",
        prompt_hash="f" * 64,
        model_name="hy3-formal-model",
        endpoint_url="https://api.example.invalid/v1",
        model_parameters=(
            FrozenModelParameter(name="max_tokens", value=4096),
            FrozenModelParameter(name="temperature", value=0.2),
        ),
        credential_env_var="HY3_API_KEY",
        status=NaturalRunStatus.COMPLETE,
        materialization_manifest_hash="1" * 64,
    )
    corpus = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=(*controlled, *natural),
        natural_run_config=natural_config,
        status=CorpusStatus.COMPLETE,
    )
    controlled_kinds = {
        CorpusSampleKind.GOLD: JudgeCaseKind.GOLD,
        CorpusSampleKind.CONTROLLED_WRONG: JudgeCaseKind.MUTANT,
        CorpusSampleKind.PARADOX: JudgeCaseKind.PARADOX,
    }
    cases = tuple(
        JudgeSourceCase(
            case_id=sample.sample_id,
            kind=controlled_kinds[sample.kind],
            problem=records[sample.problem_id],
            cpp_source=(data_root / sample.cpp_source.path).read_text(encoding="utf-8"),
        )
        for sample in controlled
    )
    raw_evidence = {
        case.case_id: JudgeEvidence(
            compile_status=JudgeStatus.AC,
            verdict=(JudgeStatus.WA if case.kind is JudgeCaseKind.MUTANT else JudgeStatus.AC),
            tests=(
                PerTestEvidence(
                    test_id="protected-test",
                    status=(
                        JudgeStatus.WA if case.kind is JudgeCaseKind.MUTANT else JudgeStatus.AC
                    ),
                    diagnostics="credential=sk-private-formal-value",
                    counterexample_input="hidden input 92731",
                ),
            ),
            diagnostics="private endpoint https://secret.example.invalid/v1",
            first_counterexample_input=(
                "hidden input 92731" if case.kind is JudgeCaseKind.MUTANT else None
            ),
        )
        for case in cases
    }

    class PersistedEvidenceJudge:
        def judge(self, _problem: object, cpp_source: str) -> JudgeEvidence:
            matching = next(case for case in cases if case.cpp_source == cpp_source)
            return raw_evidence[matching.case_id]

    judge_report = validate_formal_corpus_judge_cases(
        corpus=corpus,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
        judge=PersistedEvidenceJudge(),
    ).evidence_manifest

    selection_path = root / "selection.json"
    acquisition_path = root / "acquisition.json"
    acquisition_validation_path = root / "acquisition-validation.json"
    review_manifest_path = root / "review-manifest.json"
    bundles_path = root / "bundles.json"
    corpus_path = root / "corpus.json"
    cases_path = root / "judge-cases.json"
    judge_report_path = root / "judge-report.json"
    raw_evidence_path = root / "judge-raw-evidence.json"
    for path, value in (
        (selection_path, selection.model_dump(mode="json")),
        (acquisition_path, acquisition.model_dump(mode="json")),
        (acquisition_validation_path, acquisition_validation.model_dump(mode="json")),
        (review_manifest_path, review_manifest.model_dump(mode="json")),
        (bundles_path, bundle_manifest.model_dump(mode="json")),
        (corpus_path, corpus.model_dump(mode="json")),
        (cases_path, [case.model_dump(mode="json") for case in cases]),
        (judge_report_path, judge_report.model_dump(mode="json")),
        (
            raw_evidence_path,
            {
                case_id: evidence.model_dump(mode="json")
                for case_id, evidence in raw_evidence.items()
            },
        ),
    ):
        _write_json(path, value)

    selection_by_id = {entry.problem_id: entry for entry in selection.entries}
    sample_kind = {
        CorpusSampleKind.GOLD: SampleKind.GOLD,
        CorpusSampleKind.CONTROLLED_WRONG: SampleKind.CONTROLLED_WRONG,
        CorpusSampleKind.PARADOX: SampleKind.PARADOX,
        CorpusSampleKind.NATURAL: SampleKind.NATURAL,
    }
    specs = tuple(
        BenchmarkSampleSpec(
            sample_id=sample.sample_id,
            problem_id=sample.problem_id,
            sample_kind=sample_kind[sample.kind],
            topic=selection_by_id[sample.problem_id].topic,
            rating_band=selection_by_id[sample.problem_id].rating_band,
        )
        for sample in corpus.samples
    )
    config = BenchmarkConfig(
        benchmark_id="formal-integration",
        selection_hash=selection.content_hash,
        corpus_hash=corpus.content_hash,
        ordered_sample_ids=tuple(spec.sample_id for spec in specs),
        sample_specs=specs,
        generation_sample_ids=tuple(
            spec.sample_id for spec in specs if spec.sample_kind is SampleKind.NATURAL
        ),
        audit_sample_ids=tuple(spec.sample_id for spec in specs),
        model="hy3-formal-model",
        endpoint_identity="https://api.example.invalid/v1",
        generator_prompt_version="natural-v1",
        logic_review_prompt_version="logic-review-v1",
        adversarial_review_prompt_version="adversarial-review-v1",
        arbiter_prompt_version="arbiter-v1",
        model_parameters=(
            BenchmarkParameter(name="max_tokens", value=4096),
            BenchmarkParameter(name="temperature", value=0.2),
        ),
        code_revision="formal-revision",
        judge_image_digest=f"sha256:{'2' * 64}",
        metric_version="task6-metrics-v1",
        chart_version="task6-chart-v1",
        seed=41,
        bootstrap_replicates=1,
        remote_attempt_budget=390,
        formal=True,
        verified_data_evidence=VerifiedDataEvidence(
            evidence_kind="verified-task7-replay",
            artifact_path="judge-report.json",
            artifact_hash=sha256_json(judge_report.model_dump(mode="json")),
            selection_hash=selection.content_hash,
            corpus_hash=corpus.content_hash,
        ),
    )
    samples_by_id = {sample.sample_id: sample for sample in corpus.samples}
    observations = tuple(
        MetricObservation(
            sample_id=spec.sample_id,
            problem_id=spec.problem_id,
            sample_kind=spec.sample_kind,
            topic=spec.topic,
            rating_band=spec.rating_band,
            gold_final_correct=samples_by_id[spec.sample_id].final_expected_correct,
            gold_process_valid=samples_by_id[spec.sample_id].primary_error is None,
            gold_first_error_step=(
                None if samples_by_id[spec.sample_id].primary_error is None else 1
            ),
            gold_taxonomy=samples_by_id[spec.sample_id].primary_error,
            predicted_final_correct=samples_by_id[spec.sample_id].final_expected_correct,
            predicted_process_valid=samples_by_id[spec.sample_id].primary_error is None,
            predicted_first_error_step=(
                None if samples_by_id[spec.sample_id].primary_error is None else 1
            ),
            predicted_taxonomy=samples_by_id[spec.sample_id].primary_error,
            needs_human_review=False,
            primary_review_agreement=True,
            arbitration_used=False,
        )
        for spec in specs
    )
    labels = HumanConfirmedLabelSet(
        benchmark_id=config.benchmark_id,
        labels=tuple(
            HumanConfirmedLabel(
                sample_id=row.sample_id,
                final_correct=bool(row.gold_final_correct),
                process_valid=bool(row.gold_process_valid),
                first_error_step=row.gold_first_error_step,
                taxonomy=row.gold_taxonomy,
            )
            for row in observations
        ),
    )
    benchmark_root = root / "benchmark-artifacts"
    artifacts = ArtifactStore(benchmark_root)
    base = Path("benchmarks") / config.benchmark_id
    config_ref = artifacts.write_json(base / "config.json", config.model_dump(mode="json"))
    observation_refs = tuple(
        artifacts.write_json(
            base / "observations" / f"{row.sample_id}.json", row.model_dump(mode="json")
        )
        for row in observations
    )
    artifacts.write_json(base / "human-labels.json", labels.model_dump(mode="json"))
    events: list[LedgerEvent] = []
    for sample_id in config.ordered_sample_ids:
        if sample_id in config.generation_sample_ids:
            events.append(
                LedgerEvent(
                    benchmark_id=config.benchmark_id,
                    sequence=len(events) + 1,
                    sample_id=sample_id,
                    operation=config.generator_prompt_version,
                    phase="request",
                    retry_number=1,
                )
            )
        for operation in (
            config.logic_review_prompt_version,
            config.adversarial_review_prompt_version,
        ):
            events.append(
                LedgerEvent(
                    benchmark_id=config.benchmark_id,
                    sequence=len(events) + 1,
                    sample_id=sample_id,
                    operation=operation,
                    phase="request",
                    retry_number=1,
                )
            )
    event_refs = tuple(
        artifacts.write_json(
            base / "ledger" / f"{event.sequence:06d}.json", event.model_dump(mode="json")
        )
        for event in events
    )
    ledger = LedgerIndex(
        benchmark_id=config.benchmark_id,
        event_paths=tuple(str(ref.path) for ref in event_refs),
        event_hashes=tuple(ref.content_hash for ref in event_refs),
    )
    ledger_ref = artifacts.write_json(base / "ledger-index.json", ledger.model_dump(mode="json"))
    candidate = FormalIntegrationCandidate(
        benchmark_id=config.benchmark_id,
        config_hash=config_ref.content_hash,
        observation_hashes=tuple(ref.content_hash for ref in observation_refs),
        human_label_hashes=tuple(
            sha256_json(label.model_dump(mode="json")) for label in labels.labels
        ),
        ledger_index_hash=ledger_ref.content_hash,
        remote_attempts_used=len(events),
    )
    candidate_ref = artifacts.write_json(
        base / "formal-candidate.json", candidate.model_dump(mode="json")
    )
    candidate_path = benchmark_root / candidate_ref.path
    output_root = root / "qualification-output"
    output_root.mkdir()
    inputs = {
        "selection_path": selection_path,
        "acquisition_path": acquisition_path,
        "acquisition_validation_path": acquisition_validation_path,
        "raw_asset_paths": raw_paths,
        "data_formats": {"validation": DatasetFormat.JSON, "test": DatasetFormat.JSON},
        "review_artifact_paths": review_paths,
        "review_manifest_path": review_manifest_path,
        "bundle_manifest_path": bundles_path,
        "corpus_manifest_path": corpus_path,
        "data_root": data_root,
        "judge_cases_path": cases_path,
        "judge_report_path": judge_report_path,
        "raw_judge_evidence_path": raw_evidence_path,
        "candidate_path": candidate_path,
        "benchmark_artifact_root": benchmark_root,
        "output_root": output_root,
    }
    script_environment = {
        "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
        "HY3_FORMAL_SELECTION": str(selection_path),
        "HY3_FORMAL_ACQUISITION": str(acquisition_path),
        "HY3_FORMAL_ACQUISITION_VALIDATION": str(acquisition_validation_path),
        "HY3_FORMAL_VALIDATION_RAW": str(raw_paths["validation"]),
        "HY3_FORMAL_TEST_RAW": str(raw_paths["test"]),
        "HY3_FORMAL_VALIDATION_FORMAT": "json",
        "HY3_FORMAL_TEST_FORMAT": "json",
        "HY3_FORMAL_VALIDATION_REVIEWS": str(review_paths["validation"]),
        "HY3_FORMAL_TEST_REVIEWS": str(review_paths["test"]),
        "HY3_FORMAL_REVIEW_MANIFEST": str(review_manifest_path),
        "HY3_FORMAL_BUNDLES": str(bundles_path),
        "HY3_FORMAL_CORPUS": str(corpus_path),
        "HY3_FORMAL_DATA_ROOT": str(data_root),
        "HY3_FORMAL_JUDGE_CASES": str(cases_path),
        "HY3_FORMAL_JUDGE_EVIDENCE": str(judge_report_path),
        "HY3_FORMAL_JUDGE_RAW_EVIDENCE": str(raw_evidence_path),
        "HY3_FORMAL_BENCHMARK_CANDIDATE": str(candidate_path),
        "HY3_FORMAL_BENCHMARK_ROOT": str(benchmark_root),
        "HY3_FORMAL_QUALIFICATION_ROOT": str(output_root),
    }
    return FormalFixture(
        root=root,
        inputs=inputs,
        candidate_path=candidate_path,
        benchmark_root=benchmark_root,
        output_root=output_root,
        script_environment=script_environment,
    )


def test_complete_same_process_chain_creates_one_nonleaking_content_addressed_report(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    report_path = module.qualify_formal_run(fixture.bridge_inputs())

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["benchmark_id"] == "formal-integration"
    assert report["sample_count"] == 165
    assert report["controlled_judge_case_count"] == 105
    assert report["remote_attempts_used"] == 390
    assert report_path == fixture.output_root / "formal-qualification" / (
        report["content_hash"] + ".json"
    )
    serialized = report_path.read_text(encoding="utf-8")
    for forbidden in (
        "Print the input integer",
        "protected-test",
        "hidden input 92731",
        "sk-private-formal-value",
        "secret.example.invalid",
        "counterexample",
        "formal_eligible",
        "formal_evidence_verified",
    ):
        assert forbidden not in serialized
    with pytest.raises(Exception, match="already exists"):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize(
    "mutation",
    ("missing", "tampered", "forged-receipt", "missing-case", "duplicate-case"),
)
def test_formal_bridge_fails_closed_for_missing_tampered_or_forged_task7_chain(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path)
    inputs = dict(fixture.inputs)
    if mutation == "missing":
        Path(inputs["bundle_manifest_path"]).unlink()
    elif mutation == "tampered":
        artifact = Path(inputs["data_root"]) / "problems/cf-5000-a/reference.cpp"
        artifact.write_text("tampered source", encoding="utf-8")
    elif mutation == "forged-receipt":
        receipt_payload = {
            "schema_version": "1.2",
            "kind": "verified_selection_replay_receipt",
            "selection_manifest_hash": "a" * 64,
            "acquisition_manifest_hash": "b" * 64,
            "acquisition_validation_hash": "c" * 64,
            "review_manifest_hash": "d" * 64,
            "formal_eligibility": False,
            "capability_persisted": False,
        }
        receipt = SelectionReplayReceipt(
            **receipt_payload, content_hash=sha256_json(receipt_payload)
        )
        forged = tmp_path / "forged-receipt.json"
        _write_json(forged, receipt.model_dump(mode="json"))
        inputs["selection_path"] = forged
    else:
        cases_path = Path(inputs["judge_cases_path"])
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        cases.pop()
        if mutation == "duplicate-case":
            cases.append(cases[0])
        _write_json(cases_path, cases)

    module = importlib.import_module("hy3_algotrace.formal_qualification")
    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(module.FormalQualificationInputs(**inputs))
    assert not tuple(fixture.output_root.rglob("*.json"))


def test_formal_bridge_rejects_raw_evidence_mismatch_and_incomplete_benchmark_chain(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    evidence_path = Path(fixture.inputs["raw_judge_evidence_path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    first_case = next(iter(evidence))
    evidence[first_case]["diagnostics"] = "changed raw evidence"
    _write_json(evidence_path, evidence)
    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())

    incomplete = _build_fixture(tmp_path / "incomplete")
    ledger_path = incomplete.benchmark_root / "benchmarks/formal-integration/ledger-index.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["event_paths"].pop()
    ledger["event_hashes"].pop()
    _write_json(ledger_path, ledger)
    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(incomplete.bridge_inputs())


def test_formal_bridge_rejects_observation_label_attempt_and_identity_mismatches(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    for name in (
        "observation",
        "labels",
        "label-mismatch",
        "attempts",
        "identity",
        "stratum",
        "natural-config",
    ):
        fixture = _build_fixture(tmp_path / name)
        base = fixture.benchmark_root / "benchmarks/formal-integration"
        if name == "observation":
            next((base / "observations").iterdir()).unlink()
        elif name == "labels":
            labels_path = base / "human-labels.json"
            labels = json.loads(labels_path.read_text(encoding="utf-8"))
            labels["labels"].pop()
            _write_json(labels_path, labels)
        elif name == "label-mismatch":
            labels_path = base / "human-labels.json"
            labels = json.loads(labels_path.read_text(encoding="utf-8"))
            labels["labels"][0]["final_correct"] = False
            _write_json(labels_path, labels)
            candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
            candidate["human_label_hashes"] = [sha256_json(label) for label in labels["labels"]]
            _write_json(fixture.candidate_path, candidate)
        elif name == "attempts":
            candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
            candidate["remote_attempts_used"] = 501
            _write_json(fixture.candidate_path, candidate)
        elif name == "identity":
            config_path = base / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["corpus_hash"] = "3" * 64
            _write_json(config_path, config)
        elif name == "natural-config":
            config_path = base / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["model"] = "different-formal-model"
            _write_json(config_path, config)
            candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
            candidate["config_hash"] = sha256_json(config)
            _write_json(fixture.candidate_path, candidate)
        else:
            config_path = base / "config.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            first_problem = config["sample_specs"][0]["problem_id"]
            second_problem = next(
                spec["problem_id"]
                for spec in config["sample_specs"]
                if spec["topic"] != config["sample_specs"][0]["topic"]
                and spec["rating_band"] == config["sample_specs"][0]["rating_band"]
            )
            topics = {
                first_problem: next(
                    spec["topic"]
                    for spec in config["sample_specs"]
                    if spec["problem_id"] == first_problem
                ),
                second_problem: next(
                    spec["topic"]
                    for spec in config["sample_specs"]
                    if spec["problem_id"] == second_problem
                ),
            }
            candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
            for index, spec in enumerate(config["sample_specs"]):
                if spec["problem_id"] not in topics:
                    continue
                spec["topic"] = topics[
                    second_problem if spec["problem_id"] == first_problem else first_problem
                ]
                observation_path = base / "observations" / f"{spec['sample_id']}.json"
                observation = json.loads(observation_path.read_text(encoding="utf-8"))
                observation["topic"] = spec["topic"]
                _write_json(observation_path, observation)
                candidate["observation_hashes"][index] = sha256_json(observation)
            _write_json(config_path, config)
            candidate["config_hash"] = sha256_json(config)
            _write_json(fixture.candidate_path, candidate)
        with pytest.raises(module.FormalQualificationError):
            module.qualify_formal_run(fixture.bridge_inputs())


def test_formal_qualification_cli_and_release_scripts_propagate_fail_closed_statuses(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    ready = subprocess.run(
        ["sh", "scripts/formal-readiness.sh"],
        cwd=REPOSITORY_ROOT,
        env=fixture.script_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ready.returncode == 0
    assert "formal qualification report:" in ready.stdout
    propagated = subprocess.run(
        ["sh", "scripts/formal-release-gate.sh"],
        cwd=REPOSITORY_ROOT,
        env=fixture.script_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert propagated.returncode == 2

    missing_environment = {"PATH": os.environ["PATH"]}
    not_ready = subprocess.run(
        ["sh", "scripts/formal-readiness.sh"],
        cwd=REPOSITORY_ROOT,
        env=missing_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    blocked = subprocess.run(
        ["sh", "scripts/formal-release-gate.sh"],
        cwd=REPOSITORY_ROOT,
        env=missing_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert not_ready.returncode == 3
    assert blocked.returncode == 1
    assert "formal release gate blocked" in blocked.stderr
