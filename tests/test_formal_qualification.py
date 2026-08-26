from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
import os
import pickle
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from hy3_algotrace.artifacts import ArtifactStore, canonical_json_bytes, sha256_json
from hy3_algotrace.benchmark_models import (
    BenchmarkConfig,
    BenchmarkParameter,
    BenchmarkSampleSpec,
    BlindPublicExample,
    FormalIntegrationCandidate,
    HumanConfirmedLabel,
    HumanConfirmedLabelSet,
    HumanDecision,
    HumanDecisionSet,
    HumanReviewCandidate,
    HumanReviewRound,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    SampleKind,
    VerifiedDataEvidence,
)
from hy3_algotrace.contracts import JudgeEvidence, JudgeStatus, PerTestEvidence, SolutionTrace
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
    FormalCorpusJudgeValidationReport,
    FormalCorpusJudgeValidationResult,
    JudgeCaseKind,
    JudgeSourceCase,
    validate_formal_corpus_judge_cases,
)
from hy3_algotrace.human_review import (
    build_blind_batch,
    persist_blind_batch,
    persist_decisions,
    replay_decisions,
    select_delayed_rereview,
)
from hy3_algotrace.hy3_client import build_cache_key, generation_input
from hy3_algotrace.prompts import GENERATOR_PROMPT_VERSION, GENERATOR_SYSTEM_PROMPT

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


def _formal_cli_command(environment: dict[str, str]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "hy3_algotrace.formal_qualification",
        "--selection",
        environment["HY3_FORMAL_SELECTION"],
        "--acquisition",
        environment["HY3_FORMAL_ACQUISITION"],
        "--acquisition-validation",
        environment["HY3_FORMAL_ACQUISITION_VALIDATION"],
        "--validation-raw",
        environment["HY3_FORMAL_VALIDATION_RAW"],
        "--test-raw",
        environment["HY3_FORMAL_TEST_RAW"],
        "--validation-format",
        environment["HY3_FORMAL_VALIDATION_FORMAT"],
        "--test-format",
        environment["HY3_FORMAL_TEST_FORMAT"],
        "--validation-reviews",
        environment["HY3_FORMAL_VALIDATION_REVIEWS"],
        "--test-reviews",
        environment["HY3_FORMAL_TEST_REVIEWS"],
        "--review-manifest",
        environment["HY3_FORMAL_REVIEW_MANIFEST"],
        "--bundles",
        environment["HY3_FORMAL_BUNDLES"],
        "--corpus",
        environment["HY3_FORMAL_CORPUS"],
        "--natural-materialization",
        environment["HY3_FORMAL_NATURAL_MATERIALIZATION"],
        "--data-root",
        environment["HY3_FORMAL_DATA_ROOT"],
        "--judge-cases",
        environment["HY3_FORMAL_JUDGE_CASES"],
        "--judge-report",
        environment["HY3_FORMAL_JUDGE_EVIDENCE"],
        "--judge-raw-evidence",
        environment["HY3_FORMAL_JUDGE_RAW_EVIDENCE"],
        "--candidate",
        environment["HY3_FORMAL_BENCHMARK_CANDIDATE"],
        "--human-review-export",
        environment["HY3_FORMAL_HUMAN_REVIEW_EXPORT"],
        "--human-review-mapping",
        environment["HY3_FORMAL_HUMAN_REVIEW_MAPPING"],
        "--human-decisions",
        environment["HY3_FORMAL_HUMAN_DECISIONS"],
        "--human-review-replay",
        environment["HY3_FORMAL_HUMAN_REVIEW_REPLAY"],
        "--benchmark-root",
        environment["HY3_FORMAL_BENCHMARK_ROOT"],
        "--output-root",
        environment["HY3_FORMAL_QUALIFICATION_ROOT"],
    ]


def _build_fixture(root: Path, *, benchmark_id: str = "formal-integration") -> FormalFixture:
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
    natural_parameters = (
        FrozenModelParameter(name="max_tokens", value=4096),
        FrozenModelParameter(name="temperature", value=0.2),
        FrozenModelParameter(name="top_k", value=1),
    )
    ordered_samples = tuple(
        sorted(
            (*controlled, *natural),
            key=lambda sample: (
                list(CorpusSampleKind).index(sample.kind),
                sample.problem_id,
                sample.sample_id,
            ),
        )
    )
    planned_events: list[LedgerEvent] = []
    generation_event_hashes: dict[str, tuple[str, ...]] = {}
    for sample in ordered_samples:
        if sample.kind is CorpusSampleKind.NATURAL:
            generation_event = LedgerEvent(
                benchmark_id=benchmark_id,
                sequence=len(planned_events) + 1,
                sample_id=sample.sample_id,
                operation=GENERATOR_PROMPT_VERSION,
                phase="request",
                retry_number=1,
            )
            planned_events.append(generation_event)
            generation_event_hashes[sample.sample_id] = (
                sha256_json(generation_event.model_dump(mode="json")),
            )
        for operation in ("logic-review-v1", "adversarial-review-v1"):
            planned_events.append(
                LedgerEvent(
                    benchmark_id=benchmark_id,
                    sequence=len(planned_events) + 1,
                    sample_id=sample.sample_id,
                    operation=operation,
                    phase="request",
                    retry_number=1,
                )
            )
    natural_entries: list[dict[str, Any]] = []
    parameter_payload = [
        {
            "name": parameter.name,
            "json_type": "integer" if isinstance(parameter.value, int) else "number",
            "value": parameter.value,
        }
        for parameter in natural_parameters
    ]
    for sample in ordered_samples:
        if sample.kind is not CorpusSampleKind.NATURAL:
            continue
        trace_path = data_root / sample.trace.path
        trace = SolutionTrace.model_validate_json(trace_path.read_text(encoding="utf-8"))
        visible_input = generation_input(records[sample.problem_id])
        natural_entries.append(
            {
                "sample_id": sample.sample_id,
                "problem_id": sample.problem_id,
                "trace_path": sample.trace.path,
                "trace_byte_length": sample.trace.byte_length,
                "trace_sha256": sample.trace.sha256,
                "parsed_trace_hash": sha256_json(trace.model_dump(mode="json")),
                "source_path": sample.cpp_source.path,
                "source_byte_length": sample.cpp_source.byte_length,
                "source_sha256": sample.cpp_source.sha256,
                "problem_record_hash": sha256_json(
                    records[sample.problem_id].model_dump(mode="json")
                ),
                "model_name": "hy3-formal-model",
                "endpoint_identity": "https://api.example.invalid/v1",
                "generator_prompt_version": GENERATOR_PROMPT_VERSION,
                "generator_prompt_hash": hashlib.sha256(
                    GENERATOR_SYSTEM_PROMPT.encode("utf-8")
                ).hexdigest(),
                "model_parameters": parameter_payload,
                "model_visible_input_hash": sha256_json(visible_input),
                "request_cache_key": build_cache_key(
                    model="hy3-formal-model",
                    endpoint="https://api.example.invalid/v1",
                    prompt_version=GENERATOR_PROMPT_VERSION,
                    parameters={
                        parameter.name: parameter.value for parameter in natural_parameters
                    },
                    canonical_input=visible_input,
                ),
                "generation_event_hashes": generation_event_hashes[sample.sample_id],
            }
        )
    materialization_payload = {
        "schema_version": "1.2",
        "kind": "natural_hy3_materialization_manifest",
        "selection_manifest_hash": selection.content_hash,
        "entries": natural_entries,
    }
    materialization_hash = sha256_json(materialization_payload)
    materialization_payload["content_hash"] = materialization_hash
    materialization_path = data_root / "natural-materialization" / f"{materialization_hash}.json"
    _write_json(materialization_path, materialization_payload)
    natural_config = NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=tuple(entry.problem_id for entry in selection.entries),
        prompt_version=GENERATOR_PROMPT_VERSION,
        prompt_hash=hashlib.sha256(GENERATOR_SYSTEM_PROMPT.encode("utf-8")).hexdigest(),
        model_name="hy3-formal-model",
        endpoint_url="https://api.example.invalid/v1",
        model_parameters=natural_parameters,
        credential_env_var="HY3_API_KEY",
        status=NaturalRunStatus.COMPLETE,
        materialization_manifest_hash=materialization_hash,
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
        for sample in corpus.samples
        if sample.kind is not CorpusSampleKind.NATURAL
    )
    raw_evidence = {
        case.case_id: JudgeEvidence(
            compile_status=JudgeStatus.AC,
            verdict=(JudgeStatus.WA if case.kind is JudgeCaseKind.MUTANT else JudgeStatus.AC),
            tests=tuple(
                PerTestEvidence(
                    test_id=test.test_id,
                    status=(
                        JudgeStatus.WA
                        if case.kind is JudgeCaseKind.MUTANT and index == 0
                        else JudgeStatus.AC
                    ),
                    diagnostics="credential=sk-private-formal-value",
                    counterexample_input=(
                        test.input_data
                        if case.kind is JudgeCaseKind.MUTANT and index == 0
                        else None
                    ),
                )
                for index, test in enumerate(
                    (*case.problem.hidden_tests, *case.problem.generated_tests)
                )
            ),
            diagnostics="private endpoint https://secret.example.invalid/v1",
            first_counterexample_input=(
                case.problem.hidden_tests[0].input_data
                if case.kind is JudgeCaseKind.MUTANT
                else None
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
        benchmark_id=benchmark_id,
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
        generator_prompt_version=GENERATOR_PROMPT_VERSION,
        logic_review_prompt_version="logic-review-v1",
        adversarial_review_prompt_version="adversarial-review-v1",
        arbiter_prompt_version="arbiter-v1",
        model_parameters=(
            BenchmarkParameter(name="max_tokens", value=4096),
            BenchmarkParameter(name="temperature", value=0.2),
            BenchmarkParameter(name="top_k", value=1),
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
    blind_ids = tuple(f"blind-{index:03d}" for index in range(1, 166))
    review_candidates = tuple(
        HumanReviewCandidate(
            sample_id=sample.sample_id,
            problem_id=sample.problem_id,
            trace_id=sample.sample_id,
            statement=records[sample.problem_id].statement_en,
            public_examples=tuple(
                BlindPublicExample(
                    input_data=test.input_data,
                    output_data=test.expected_output,
                )
                for test in records[sample.problem_id].public_tests
            ),
            trace=SolutionTrace.model_validate_json(
                (data_root / sample.trace.path).read_text(encoding="utf-8")
            ),
        )
        for sample in corpus.samples
    )
    review_export, review_mapping = build_blind_batch(
        batch_id=f"{benchmark_id}-blind",
        candidates=review_candidates,
        blind_ids=blind_ids,
    )
    export_ref, mapping_ref = persist_blind_batch(artifacts, review_export, review_mapping)
    labels_by_sample = {label.sample_id: label for label in labels.labels}
    initial_time = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    initial_decisions = tuple(
        HumanDecision(
            decision_id=f"initial-{index:03d}",
            blind_id=mapping.blind_id,
            reviewer_id="human-reviewer-1",
            round=HumanReviewRound.INITIAL,
            decided_at=initial_time + timedelta(minutes=index),
            final_correct=labels_by_sample[mapping.sample_id].final_correct,
            process_valid=labels_by_sample[mapping.sample_id].process_valid,
            first_error_step=labels_by_sample[mapping.sample_id].first_error_step,
            taxonomy=labels_by_sample[mapping.sample_id].taxonomy,
        )
        for index, mapping in enumerate(review_mapping.entries, start=1)
    )
    initial_by_blind = {decision.blind_id: decision for decision in initial_decisions}
    delayed_ids = select_delayed_rereview(blind_ids, seed=73)
    delayed_decisions = tuple(
        HumanDecision(
            decision_id=f"delayed-{index:03d}",
            blind_id=blind_id,
            reviewer_id=initial_by_blind[blind_id].reviewer_id,
            round=HumanReviewRound.DELAYED,
            decided_at=initial_by_blind[blind_id].decided_at + timedelta(days=14),
            final_correct=initial_by_blind[blind_id].final_correct,
            process_valid=initial_by_blind[blind_id].process_valid,
            first_error_step=initial_by_blind[blind_id].first_error_step,
            taxonomy=initial_by_blind[blind_id].taxonomy,
        )
        for index, blind_id in enumerate(delayed_ids, start=1)
    )
    decision_set = HumanDecisionSet(
        batch_id=review_export.batch_id,
        decision_set_id="human-decisions-v1",
        sample_seed=73,
        initial_decisions=initial_decisions,
        delayed_decisions=delayed_decisions,
    )
    decisions_ref = persist_decisions(artifacts, decision_set)
    replay_id = "human-replay-v1"
    replay_decisions(
        artifacts,
        replay_id=replay_id,
        observations=observations,
        mapping=review_mapping,
        decision_set=decision_set,
    )
    replay_path = (
        benchmark_root / "human-review" / review_export.batch_id / "replays" / f"{replay_id}.json"
    )
    events = planned_events
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
        "natural_materialization_path": materialization_path,
        "data_root": data_root,
        "judge_cases_path": cases_path,
        "judge_report_path": judge_report_path,
        "raw_judge_evidence_path": raw_evidence_path,
        "candidate_path": candidate_path,
        "human_review_export_path": benchmark_root / export_ref.path,
        "human_review_mapping_path": benchmark_root / mapping_ref.path,
        "human_decisions_path": benchmark_root / decisions_ref.path,
        "human_review_replay_path": replay_path,
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
        "HY3_FORMAL_NATURAL_MATERIALIZATION": str(materialization_path),
        "HY3_FORMAL_DATA_ROOT": str(data_root),
        "HY3_FORMAL_JUDGE_CASES": str(cases_path),
        "HY3_FORMAL_JUDGE_EVIDENCE": str(judge_report_path),
        "HY3_FORMAL_JUDGE_RAW_EVIDENCE": str(raw_evidence_path),
        "HY3_FORMAL_BENCHMARK_CANDIDATE": str(candidate_path),
        "HY3_FORMAL_HUMAN_REVIEW_EXPORT": str(benchmark_root / export_ref.path),
        "HY3_FORMAL_HUMAN_REVIEW_MAPPING": str(benchmark_root / mapping_ref.path),
        "HY3_FORMAL_HUMAN_DECISIONS": str(benchmark_root / decisions_ref.path),
        "HY3_FORMAL_HUMAN_REVIEW_REPLAY": str(replay_path),
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


def _rehash_judge_chain(fixture: FormalFixture, raw_evidence: dict[str, Any]) -> None:
    evidence_path = Path(fixture.inputs["raw_judge_evidence_path"])
    _write_json(evidence_path, raw_evidence)
    judge_path = Path(fixture.inputs["judge_report_path"])
    judge_report = json.loads(judge_path.read_text(encoding="utf-8"))
    for case in judge_report["cases"]:
        case["judge_evidence_hash"] = sha256_json(raw_evidence[case["case_id"]])
    judge_report["content_hash"] = sha256_json(
        {key: value for key, value in judge_report.items() if key != "content_hash"}
    )
    _write_json(judge_path, judge_report)
    candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    config_path = fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"] / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["verified_data_evidence"]["artifact_hash"] = sha256_json(judge_report)
    _write_json(config_path, config)
    candidate["config_hash"] = sha256_json(config)
    _write_json(fixture.candidate_path, candidate)


def _replace_materialization_hash(fixture: FormalFixture, digest: str) -> None:
    corpus_path = Path(fixture.inputs["corpus_manifest_path"])
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    natural_config = corpus["natural_run_config"]
    natural_config["materialization_manifest_hash"] = digest
    natural_config["content_hash"] = sha256_json(
        {key: value for key, value in natural_config.items() if key != "content_hash"}
    )
    corpus["content_hash"] = sha256_json(
        {key: value for key, value in corpus.items() if key != "content_hash"}
    )
    _write_json(corpus_path, corpus)
    judge_path = Path(fixture.inputs["judge_report_path"])
    judge_report = json.loads(judge_path.read_text(encoding="utf-8"))
    judge_report["corpus_manifest_hash"] = corpus["content_hash"]
    judge_report["content_hash"] = sha256_json(
        {key: value for key, value in judge_report.items() if key != "content_hash"}
    )
    _write_json(judge_path, judge_report)
    candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    config_path = fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"] / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["corpus_hash"] = corpus["content_hash"]
    config["verified_data_evidence"]["corpus_hash"] = corpus["content_hash"]
    config["verified_data_evidence"]["artifact_hash"] = sha256_json(judge_report)
    _write_json(config_path, config)
    candidate["config_hash"] = sha256_json(config)
    _write_json(fixture.candidate_path, candidate)


def _rewrite_natural_materialization(fixture: FormalFixture, mutation: str) -> None:
    path = Path(fixture.inputs["natural_materialization_path"])
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "order":
        manifest["entries"] = list(reversed(manifest["entries"]))
    else:
        entry = manifest["entries"][0]
        if mutation == "trace":
            entry["parsed_trace_hash"] = "0" * 64
        elif mutation == "source":
            entry["source_sha256"] = "0" * 64
        elif mutation == "request":
            entry["request_cache_key"] = "0" * 64
        elif mutation == "input":
            entry["model_visible_input_hash"] = "0" * 64
        elif mutation == "prompt":
            entry["generator_prompt_hash"] = "0" * 64
        elif mutation == "events":
            entry["generation_event_hashes"] = ["0" * 64]
        else:
            top_k = next(
                parameter for parameter in entry["model_parameters"] if parameter["name"] == "top_k"
            )
            top_k["json_type"] = "boolean"
            top_k["value"] = True
    manifest["content_hash"] = sha256_json(
        {key: value for key, value in manifest.items() if key != "content_hash"}
    )
    replacement = path.parent / f"{manifest['content_hash']}.json"
    _write_json(replacement, manifest)
    fixture.inputs["natural_materialization_path"] = replacement
    fixture.script_environment["HY3_FORMAL_NATURAL_MATERIALIZATION"] = str(replacement)
    _replace_materialization_hash(fixture, manifest["content_hash"])


def test_formal_bridge_rejects_unresolved_natural_materialization_digest(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    _replace_materialization_hash(fixture, "1" * 64)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize(
    "mutation",
    ("order", "trace", "source", "request", "input", "prompt", "events", "parameters"),
)
def test_formal_bridge_rejects_rehashed_natural_materialization_forgery(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path / mutation)
    _rewrite_natural_materialization(fixture, mutation)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


def test_formal_bridge_rejects_bare_human_labels_without_review_replay(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    for name in (
        "human_review_export_path",
        "human_review_mapping_path",
        "human_decisions_path",
        "human_review_replay_path",
    ):
        Path(fixture.inputs[name]).unlink()
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize(
    "mutation",
    ("export", "mapping", "decisions", "reviewer", "timestamp", "replay", "path"),
)
def test_formal_bridge_rejects_human_review_provenance_forgery(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path / mutation)
    if mutation == "path":
        source = Path(fixture.inputs["human_review_export_path"])
        replacement = fixture.benchmark_root / "human-review" / "wrong-export.json"
        _write_json(replacement, json.loads(source.read_text(encoding="utf-8")))
        fixture.inputs["human_review_export_path"] = replacement
    else:
        key = {
            "export": "human_review_export_path",
            "mapping": "human_review_mapping_path",
            "decisions": "human_decisions_path",
            "reviewer": "human_decisions_path",
            "timestamp": "human_decisions_path",
            "replay": "human_review_replay_path",
        }[mutation]
        path = Path(fixture.inputs[key])
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "export":
            payload["items"][0]["statement"] = "forged public statement"
        elif mutation == "mapping":
            payload["entries"][0], payload["entries"][1] = (
                payload["entries"][1],
                payload["entries"][0],
            )
        elif mutation == "decisions":
            payload["initial_decisions"].pop()
        elif mutation == "reviewer":
            payload["delayed_decisions"][0]["reviewer_id"] = "substitute-reviewer"
        elif mutation == "timestamp":
            blind_id = payload["delayed_decisions"][0]["blind_id"]
            initial = next(
                item for item in payload["initial_decisions"] if item["blind_id"] == blind_id
            )
            payload["delayed_decisions"][0]["decided_at"] = initial["decided_at"]
        else:
            payload["observations"] = list(reversed(payload["observations"]))
        _write_json(path, payload)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize("substitute", (True, 1.0), ids=("bool-for-int", "float-for-int"))
def test_formal_bridge_rejects_json_scalar_type_substitution_in_parameters(
    tmp_path: Path, substitute: bool | float
) -> None:
    fixture = _build_fixture(tmp_path)
    candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    config_path = fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"] / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    top_k = next(
        parameter for parameter in config["model_parameters"] if parameter["name"] == "top_k"
    )
    top_k["value"] = substitute
    _write_json(config_path, config)
    candidate["config_hash"] = sha256_json(config)
    _write_json(fixture.candidate_path, candidate)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


def test_formal_bridge_rejects_aggregate_only_judge_evidence_with_rehashed_chain(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    raw_path = Path(fixture.inputs["raw_judge_evidence_path"])
    raw_evidence = json.loads(raw_path.read_text(encoding="utf-8"))
    first_case = next(iter(raw_evidence))
    raw_evidence[first_case]["tests"] = []
    _rehash_judge_chain(fixture, raw_evidence)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize(
    "mutation",
    (
        "missing",
        "duplicate",
        "reordered",
        "unknown",
        "not-run",
        "infrastructure-error",
        "aggregate-verdict",
        "counterexample-exposure",
    ),
)
def test_formal_bridge_rejects_noncanonical_per_test_judge_execution_shape(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path / mutation)
    raw_path = Path(fixture.inputs["raw_judge_evidence_path"])
    raw_evidence = json.loads(raw_path.read_text(encoding="utf-8"))
    case_id = next(
        case_id for case_id, evidence in raw_evidence.items() if evidence["verdict"] == "wa"
    )
    evidence = raw_evidence[case_id]
    if mutation == "missing":
        evidence["tests"].pop()
    elif mutation == "duplicate":
        evidence["tests"][1] = dict(evidence["tests"][0])
    elif mutation == "reordered":
        evidence["tests"] = list(reversed(evidence["tests"]))
    elif mutation == "unknown":
        evidence["tests"][1]["test_id"] = "unknown-final-test"
    elif mutation == "not-run":
        evidence["tests"][1]["status"] = "not_run"
    elif mutation == "infrastructure-error":
        evidence["tests"][1]["status"] = "infrastructure_error"
    elif mutation == "aggregate-verdict":
        evidence["tests"][0]["status"] = "ac"
        evidence["tests"][0]["counterexample_input"] = None
        evidence["first_counterexample_input"] = None
    else:
        evidence["tests"][0]["counterexample_input"] = None
        evidence["tests"][1]["counterexample_input"] = "3\n"
    _rehash_judge_chain(fixture, raw_evidence)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


def _rewrite_ledger_sequence(fixture: FormalFixture, mutation: str) -> None:
    candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    base = fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"]
    config_path = base / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["remote_attempt_budget"] = 500
    _write_json(config_path, config)
    candidate["config_hash"] = sha256_json(config)
    ledger_path = base / "ledger-index.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    events = [
        json.loads((fixture.benchmark_root / path).read_text(encoding="utf-8"))
        for path in ledger["event_paths"]
    ]
    if mutation == "retry-999":
        retry_999 = {**events[0], "retry_number": 999}
        events.insert(1, retry_999)
    elif mutation == "retry-gap":
        retry_two = {**events[0], "retry_number": 2}
        events.insert(0, retry_two)
    elif mutation == "repair-before-request":
        repair = {**events[0], "phase": "schema_repair", "retry_number": 1}
        events.insert(0, repair)
    elif mutation == "repeated-repair":
        repair = {**events[0], "phase": "schema_repair", "retry_number": 1}
        events[1:1] = [repair, repair.copy()]
    elif mutation == "operation-order":
        events[0], events[1] = events[1], events[0]
    else:
        first_sample = events[0]["sample_id"]
        first_block_end = next(
            index for index, event in enumerate(events) if event["sample_id"] != first_sample
        )
        second_sample = events[first_block_end]["sample_id"]
        second_block_end = next(
            index
            for index, event in enumerate(events[first_block_end:], start=first_block_end)
            if event["sample_id"] != second_sample
        )
        events[:second_block_end] = (
            events[first_block_end:second_block_end] + events[:first_block_end]
        )
    event_paths: list[str] = []
    event_hashes: list[str] = []
    relative_base = Path("benchmarks") / candidate["benchmark_id"] / "ledger"
    for sequence, event in enumerate(events, start=1):
        event["sequence"] = sequence
        relative_path = relative_base / f"{sequence:06d}.json"
        _write_json(fixture.benchmark_root / relative_path, event)
        event_paths.append(relative_path.as_posix())
        event_hashes.append(sha256_json(event))
    ledger["event_paths"] = event_paths
    ledger["event_hashes"] = event_hashes
    _write_json(ledger_path, ledger)
    candidate["ledger_index_hash"] = sha256_json(ledger)
    candidate["remote_attempts_used"] = len(events)
    _write_json(fixture.candidate_path, candidate)


def test_complete_same_process_chain_creates_one_nonleaking_content_addressed_report(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    report_path = module.qualify_formal_run(fixture.bridge_inputs())

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["benchmark_hash"] == sha256_json("formal-integration")
    assert "benchmark_id" not in report
    assert report["sample_count"] == 165
    assert report["controlled_judge_case_count"] == 105
    assert report["remote_attempts_used"] == 390
    assert report["natural_materialization_hash"]
    assert report["human_review_provenance_hash"]
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
        GENERATOR_SYSTEM_PROMPT.strip(),
        "api.example.invalid",
        "human-reviewer-1",
        "formal-integration-blind",
        "generator_prompt",
        "model_visible_input",
        "response",
        "reviewer_id",
        '"endpoint',
        '"code',
        "counterexample",
        "formal_eligible",
        "formal_evidence_verified",
    ):
        assert forbidden not in serialized
    with pytest.raises(Exception, match="already exists"):
        module.qualify_formal_run(fixture.bridge_inputs())


def test_report_hashes_credential_shaped_outward_benchmark_identity(tmp_path: Path) -> None:
    benchmark_id = "sk-private-formal-value"
    fixture = _build_fixture(tmp_path, benchmark_id=benchmark_id)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    report_path = module.qualify_formal_run(fixture.bridge_inputs())

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["benchmark_hash"] == sha256_json(benchmark_id)
    assert benchmark_id not in report_path.read_text(encoding="utf-8")
    assert "benchmark_id" not in report


def test_formal_bridge_uses_one_corpus_manifest_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    corpus_path = Path(fixture.inputs["corpus_manifest_path"])
    original_read_json = module._read_json
    swapped = False

    def read_then_replace(path: Path) -> Any:
        nonlocal swapped
        payload = original_read_json(path)
        if path == corpus_path and not swapped:
            swapped = True
            replacement = dict(payload)
            replacement["content_hash"] = "f" * 64
            _write_json(corpus_path, replacement)
        return payload

    monkeypatch.setattr(module, "_read_json", read_then_replace)

    report_path = module.qualify_formal_run(fixture.bridge_inputs())

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["corpus_hash"] != "f" * 64


def test_formal_bridge_loads_natural_materialization_manifest_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    materialization_path = Path(fixture.inputs["natural_materialization_path"])
    original_read_json = module._read_json
    reads = 0

    def counted_read(path: Path) -> Any:
        nonlocal reads
        if path == materialization_path:
            reads += 1
        return original_read_json(path)

    monkeypatch.setattr(module, "_read_json", counted_read)

    module.qualify_formal_run(fixture.bridge_inputs())

    assert reads == 1


def test_formal_bridge_revalidates_trace_snapshot_after_lint_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    corpus = json.loads(Path(fixture.inputs["corpus_manifest_path"]).read_text(encoding="utf-8"))
    sample = next(item for item in corpus["samples"] if item["first_error_step_id"] is not None)
    trace_path = Path(fixture.inputs["data_root"]) / sample["trace"]["path"]
    original_lint = module.lint_corpus_manifest

    def lint_then_replace(*args: Any, **kwargs: Any) -> Any:
        audit = original_lint(*args, **kwargs)
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        trace["algorithm"] = "post-lint unvalidated replacement"
        _write_json(trace_path, trace)
        return audit

    monkeypatch.setattr(module, "lint_corpus_manifest", lint_then_replace)

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize("transfer", ("pickle", "copy", "deepcopy"))
def test_formal_judge_capability_rejects_serialization_and_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transfer: str,
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    original_replay = module.validate_persisted_formal_judge_evidence
    captured: list[FormalCorpusJudgeValidationResult] = []

    def capture_replay(*args: Any, **kwargs: Any) -> FormalCorpusJudgeValidationResult:
        result = original_replay(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(module, "validate_persisted_formal_judge_evidence", capture_replay)
    module.qualify_formal_run(fixture.bridge_inputs())
    capability = captured[0]

    with pytest.raises(TypeError):
        if transfer == "pickle":
            pickle.dumps(capability)
        elif transfer == "copy":
            copy.copy(capability)
        else:
            copy.deepcopy(capability)


def test_formal_bridge_rejects_forged_deserialized_judge_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _build_fixture(tmp_path)
    module = importlib.import_module("hy3_algotrace.formal_qualification")
    evidence_payload = json.loads(
        Path(fixture.inputs["judge_report_path"]).read_text(encoding="utf-8")
    )
    forged = object.__new__(FormalCorpusJudgeValidationResult)
    object.__setattr__(
        forged,
        "evidence_manifest",
        FormalCorpusJudgeValidationReport.model_validate_json(json.dumps(evidence_payload)),
    )
    object.__setattr__(forged, "formal_eligibility", True)
    monkeypatch.setattr(
        module,
        "validate_persisted_formal_judge_evidence",
        lambda *args, **kwargs: forged,
    )

    with pytest.raises(module.FormalQualificationError):
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


@pytest.mark.parametrize(
    "name",
    (
        "observation",
        "labels",
        "label-mismatch",
        "attempts",
        "identity",
        "stratum",
        "natural-config",
        "problem-id",
    ),
)
def test_formal_bridge_rejects_independent_benchmark_chain_mutations(
    tmp_path: Path, name: str
) -> None:
    module = importlib.import_module("hy3_algotrace.formal_qualification")
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
    elif name == "stratum":
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
    else:
        config_path = base / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        first_spec = config["sample_specs"][0]
        first_problem = first_spec["problem_id"]
        second_problem = next(
            spec["problem_id"]
            for spec in config["sample_specs"]
            if spec["problem_id"] != first_problem
            and spec["topic"] == first_spec["topic"]
            and spec["rating_band"] == first_spec["rating_band"]
        )
        candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
        for index, spec in enumerate(config["sample_specs"]):
            if spec["problem_id"] not in {first_problem, second_problem}:
                continue
            spec["problem_id"] = (
                second_problem if spec["problem_id"] == first_problem else first_problem
            )
            observation_path = base / "observations" / f"{spec['sample_id']}.json"
            observation = json.loads(observation_path.read_text(encoding="utf-8"))
            observation["problem_id"] = spec["problem_id"]
            _write_json(observation_path, observation)
            candidate["observation_hashes"][index] = sha256_json(observation)
        _write_json(config_path, config)
        candidate["config_hash"] = sha256_json(config)
        _write_json(fixture.candidate_path, candidate)
    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize("mutation", ("judge-case-order", "judge-evidence-order"))
def test_formal_bridge_rejects_reordered_controlled_judge_encodings(
    tmp_path: Path, mutation: str
) -> None:
    fixture = _build_fixture(tmp_path / mutation)
    if mutation == "judge-case-order":
        path = Path(fixture.inputs["judge_cases_path"])
        cases = json.loads(path.read_text(encoding="utf-8"))
        _write_json(path, list(reversed(cases)))
    else:
        path = Path(fixture.inputs["judge_report_path"])
        evidence = json.loads(path.read_text(encoding="utf-8"))
        evidence["cases"] = list(reversed(evidence["cases"]))
        evidence["content_hash"] = sha256_json(
            {key: value for key, value in evidence.items() if key != "content_hash"}
        )
        _write_json(path, evidence)
        candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
        config_path = (
            fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"] / "config.json"
        )
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["verified_data_evidence"]["artifact_hash"] = sha256_json(evidence)
        _write_json(config_path, config)
        candidate["config_hash"] = sha256_json(config)
        _write_json(fixture.candidate_path, candidate)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


@pytest.mark.parametrize(
    "mutation",
    (
        "retry-999",
        "retry-gap",
        "repair-before-request",
        "repeated-repair",
        "operation-order",
        "sample-order",
    ),
)
def test_formal_bridge_rejects_impossible_attempt_sequences(tmp_path: Path, mutation: str) -> None:
    fixture = _build_fixture(tmp_path / mutation)
    _rewrite_ledger_sequence(fixture, mutation)
    module = importlib.import_module("hy3_algotrace.formal_qualification")

    with pytest.raises(module.FormalQualificationError):
        module.qualify_formal_run(fixture.bridge_inputs())


def test_missing_nested_benchmark_input_is_safe_exit_two_across_public_gates(
    tmp_path: Path,
) -> None:
    fixture = _build_fixture(tmp_path)
    candidate = json.loads(fixture.candidate_path.read_text(encoding="utf-8"))
    config_path = fixture.benchmark_root / "benchmarks" / candidate["benchmark_id"] / "config.json"
    config_path.unlink()

    direct = subprocess.run(
        _formal_cli_command(fixture.script_environment),
        cwd=REPOSITORY_ROOT,
        env=fixture.script_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    readiness = subprocess.run(
        ["sh", "scripts/formal-readiness.sh"],
        cwd=REPOSITORY_ROOT,
        env=fixture.script_environment,
        check=False,
        capture_output=True,
        text=True,
    )
    release = subprocess.run(
        ["sh", "scripts/formal-release-gate.sh"],
        cwd=REPOSITORY_ROOT,
        env=fixture.script_environment,
        check=False,
        capture_output=True,
        text=True,
    )

    for result in (direct, readiness, release):
        assert result.returncode == 2
        assert "formal qualification failed closed" in result.stderr
        assert "Traceback" not in result.stderr


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


def test_public_formal_cli_help_contains_required_nonofficial_disclosure() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "hy3_algotrace.formal_qualification", "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "personal activity project and not an official Tencent release" in result.stdout
