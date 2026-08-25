"""Same-process, fail-closed Task 7 to Task 6 formal qualification bridge."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .artifacts import ArtifactExistsError, ArtifactStore, sha256_json
from .benchmark_models import (
    BenchmarkConfig,
    FormalIntegrationCandidate,
    HumanConfirmedLabelSet,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    SampleKind,
)
from .contracts import JudgeEvidence, SolutionTrace
from .corpus import (
    CorpusManifest,
    CorpusSample,
    CorpusStatus,
    ProjectBundleManifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from .dataset_models import (
    AcquisitionManifest,
    AcquisitionValidationReport,
    DatasetFormat,
    FrozenSelectionManifest,
    ReviewArtifactManifest,
    read_trusted_file,
    verify_frozen_selection_chain,
)
from .differential import (
    FormalCorpusJudgeValidationResult,
    JudgeSourceCase,
    validate_persisted_formal_judge_evidence,
)

_MAX_JSON_BYTES = 256 * 1024 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NONOFFICIAL_DISCLOSURE = (
    "Hy3 AlgoTrace Lab is a personal activity project and not an official Tencent release."
)


class FormalQualificationError(RuntimeError):
    """Raised when any persisted input cannot support formal qualification."""


@dataclass(frozen=True, slots=True)
class FormalQualificationInputs:
    """Complete external inputs; persisted receipts are deliberately not accepted."""

    selection_path: Path
    acquisition_path: Path
    acquisition_validation_path: Path
    raw_asset_paths: Mapping[str, Path]
    data_formats: Mapping[str, DatasetFormat]
    review_artifact_paths: Mapping[str, Path]
    review_manifest_path: Path
    bundle_manifest_path: Path
    corpus_manifest_path: Path
    data_root: Path
    judge_cases_path: Path
    judge_report_path: Path
    raw_judge_evidence_path: Path
    candidate_path: Path
    benchmark_artifact_root: Path
    output_root: Path


class FormalQualificationReport(BaseModel):
    """Safe immutable hash summary; deserializing it never restores eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["formal_qualification_report"] = "formal_qualification_report"
    benchmark_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_labels_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    ledger_index_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_count: Literal[165] = 165
    controlled_judge_case_count: Literal[105] = 105
    remote_attempts_used: int = Field(ge=390, le=500, strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_hash(self) -> Self:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        if self.content_hash != sha256_json(payload):
            raise ValueError("formal qualification content_hash does not match")
        return self

    @classmethod
    def create(
        cls,
        *,
        benchmark_id: str,
        selection_hash: str,
        bundle_manifest_hash: str,
        corpus_hash: str,
        judge_evidence_hash: str,
        candidate_hash: str,
        config_hash: str,
        observation_hashes: tuple[str, ...],
        human_label_hashes: tuple[str, ...],
        ledger_index_hash: str,
        remote_attempts_used: int,
    ) -> FormalQualificationReport:
        payload: dict[str, Any] = {
            "schema_version": "1.2",
            "kind": "formal_qualification_report",
            "benchmark_hash": sha256_json(benchmark_id),
            "selection_hash": selection_hash,
            "bundle_manifest_hash": bundle_manifest_hash,
            "corpus_hash": corpus_hash,
            "judge_evidence_hash": judge_evidence_hash,
            "candidate_hash": candidate_hash,
            "config_hash": config_hash,
            "observations_hash": sha256_json(list(observation_hashes)),
            "human_labels_hash": sha256_json(list(human_label_hashes)),
            "ledger_index_hash": ledger_index_hash,
            "sample_count": 165,
            "controlled_judge_case_count": 105,
            "remote_attempts_used": remote_attempts_used,
        }
        return cls(**payload, content_hash=sha256_json(payload))


def qualify_formal_run(inputs: FormalQualificationInputs) -> Path:
    """Replay the complete chain and create one safe content-addressed report."""

    try:
        report = _qualify_formal_run(inputs)
        output = ArtifactStore(inputs.output_root).write_json(
            Path("formal-qualification") / f"{report.content_hash}.json",
            report.model_dump(mode="json"),
        )
        return inputs.output_root.resolve(strict=True) / output.path
    except ArtifactExistsError:
        raise
    except FormalQualificationError:
        raise
    except (OSError, TypeError, ValueError, ValidationError) as error:
        raise FormalQualificationError("formal qualification failed closed") from error


def _qualify_formal_run(inputs: FormalQualificationInputs) -> FormalQualificationReport:
    acquisition = _read_model(AcquisitionManifest, inputs.acquisition_path)
    acquisition_validation = _read_model(
        AcquisitionValidationReport, inputs.acquisition_validation_path
    )
    review_manifest = _read_model(ReviewArtifactManifest, inputs.review_manifest_path)
    selection_chain = verify_frozen_selection_chain(
        _read_mapping(inputs.selection_path),
        raw_asset_paths=inputs.raw_asset_paths,
        data_formats=inputs.data_formats,
        review_artifact_paths=inputs.review_artifact_paths,
        review_manifest=review_manifest,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    selection = selection_chain.selection
    bundle_manifest = lint_project_bundles(
        _read_mapping(inputs.bundle_manifest_path),
        root=inputs.data_root,
        selection=selection,
    )
    corpus = _read_model(CorpusManifest, inputs.corpus_manifest_path)
    audit = lint_corpus_manifest(
        _read_mapping(inputs.corpus_manifest_path),
        root=inputs.data_root,
        selection=selection,
        bundle_manifest=bundle_manifest,
    )
    if corpus.status is not CorpusStatus.COMPLETE or len(corpus.samples) != 165:
        raise FormalQualificationError("formal corpus must contain all 165 samples")
    if audit.materialized_counts != audit.expected_counts:
        raise FormalQualificationError("formal corpus counts are incomplete")

    raw_cases = _read_list(inputs.judge_cases_path)
    if len(raw_cases) != 105:
        raise FormalQualificationError("formal Judge case count must be exactly 105")
    cases = tuple(_validate_model(JudgeSourceCase, value) for value in raw_cases)
    raw_evidence_payload = _read_mapping(inputs.raw_judge_evidence_path)
    raw_evidence = {
        case_id: _validate_model(JudgeEvidence, value)
        for case_id, value in raw_evidence_payload.items()
        if isinstance(case_id, str)
    }
    if len(raw_evidence) != len(raw_evidence_payload):
        raise FormalQualificationError("raw JudgeEvidence keys must be strings")
    judge_payload = _read_mapping(inputs.judge_report_path)
    judge_result = validate_persisted_formal_judge_evidence(
        judge_payload,
        corpus=corpus,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
        raw_evidence=raw_evidence,
    )
    return _qualify_benchmark_chain(
        inputs=inputs,
        corpus=corpus,
        selection=selection,
        bundle_manifest=bundle_manifest,
        judge_payload=judge_payload,
        judge_result=judge_result,
    )


def _qualify_benchmark_chain(
    *,
    inputs: FormalQualificationInputs,
    corpus: CorpusManifest,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
    judge_payload: Mapping[str, Any],
    judge_result: FormalCorpusJudgeValidationResult,
) -> FormalQualificationReport:
    if judge_result.formal_eligibility is not True:
        raise FormalQualificationError("ephemeral Judge replay result is absent")
    store = ArtifactStore(inputs.benchmark_artifact_root)
    candidate_payload = _read_mapping(inputs.candidate_path)
    candidate = _validate_model(FormalIntegrationCandidate, candidate_payload)
    base = Path("benchmarks") / candidate.benchmark_id
    _require_canonical_input_path(
        inputs.candidate_path,
        root=inputs.benchmark_artifact_root,
        relative=base / "formal-candidate.json",
    )
    config_payload = store.read_json(base / "config.json")
    config = _validate_model(BenchmarkConfig, config_payload)
    if (
        candidate.benchmark_id != config.benchmark_id
        or candidate.config_hash != sha256_json(config.model_dump(mode="json"))
        or config.selection_hash != judge_result.evidence_manifest.selection_manifest_hash
        or config.selection_hash != corpus.selection_manifest_hash
        or config.corpus_hash != corpus.content_hash
        or not config.formal
    ):
        raise FormalQualificationError("candidate, config, selection, or corpus identity mismatch")
    evidence = config.verified_data_evidence
    judge_artifact_hash = sha256_json(dict(judge_payload))
    if (
        evidence is None
        or evidence.artifact_hash != judge_artifact_hash
        or evidence.selection_hash != config.selection_hash
        or evidence.corpus_hash != config.corpus_hash
    ):
        raise FormalQualificationError("benchmark verified-data identity mismatch")
    natural_config = corpus.natural_run_config
    benchmark_parameters = {
        parameter.name: parameter.value for parameter in config.model_parameters
    }
    natural_parameters = {
        parameter.name: parameter.value for parameter in natural_config.model_parameters
    }
    if (
        config.model != natural_config.model_name
        or config.endpoint_identity != natural_config.endpoint_url
        or config.generator_prompt_version != natural_config.prompt_version
        or benchmark_parameters != natural_parameters
    ):
        raise FormalQualificationError("benchmark generation identity does not match corpus")
    if (
        len(config.ordered_sample_ids) != 165
        or tuple(sample.sample_id for sample in corpus.samples) != config.ordered_sample_ids
    ):
        raise FormalQualificationError("benchmark sample order does not match corpus")

    selection_by_id = {entry.problem_id: entry for entry in selection.entries}
    for spec in config.sample_specs:
        selected = selection_by_id.get(spec.problem_id)
        if selected is None or (spec.topic, spec.rating_band) != (
            selected.topic,
            selected.rating_band,
        ):
            raise FormalQualificationError("benchmark stratum does not match frozen selection")
    corpus_by_id = {sample.sample_id: sample for sample in corpus.samples}
    observations = _load_observations(
        store=store,
        base=base,
        config=config,
        candidate=candidate,
        corpus_by_id=corpus_by_id,
        data_root=inputs.data_root,
    )
    labels_payload = store.read_json(base / "human-labels.json")
    labels = _validate_model(HumanConfirmedLabelSet, labels_payload)
    if (
        labels.benchmark_id != config.benchmark_id
        or tuple(label.sample_id for label in labels.labels) != config.ordered_sample_ids
    ):
        raise FormalQualificationError("human labels must be complete and ordered")
    if (
        len(labels.labels) != 165
        or tuple(sha256_json(label.model_dump(mode="json")) for label in labels.labels)
        != candidate.human_label_hashes
    ):
        raise FormalQualificationError("human label hashes do not match candidate")
    for observation, label in zip(observations, labels.labels, strict=True):
        if (
            label.sample_id,
            label.final_correct,
            label.process_valid,
            label.first_error_step,
            label.taxonomy,
        ) != (
            observation.sample_id,
            observation.gold_final_correct,
            observation.gold_process_valid,
            observation.gold_first_error_step,
            observation.gold_taxonomy,
        ):
            raise FormalQualificationError("human labels do not match frozen gold fields")

    ledger_payload = store.read_json(base / "ledger-index.json")
    ledger = _validate_model(LedgerIndex, ledger_payload)
    if (
        ledger.benchmark_id != config.benchmark_id
        or sha256_json(ledger.model_dump(mode="json")) != candidate.ledger_index_hash
    ):
        raise FormalQualificationError("ledger index identity or hash mismatch")
    events = _load_ledger_events(
        store=store,
        base=base,
        ledger=ledger,
        expected_attempts=candidate.remote_attempts_used,
    )
    if (
        len(events) != candidate.remote_attempts_used
        or candidate.remote_attempts_used > config.remote_attempt_budget
        or candidate.remote_attempts_used > 500
    ):
        raise FormalQualificationError("formal attempt total exceeds its frozen limit")
    _validate_formal_attempt_profile(config, observations, events)
    return FormalQualificationReport.create(
        benchmark_id=config.benchmark_id,
        selection_hash=config.selection_hash,
        bundle_manifest_hash=bundle_manifest.content_hash,
        corpus_hash=config.corpus_hash,
        judge_evidence_hash=judge_artifact_hash,
        candidate_hash=sha256_json(candidate.model_dump(mode="json")),
        config_hash=candidate.config_hash,
        observation_hashes=candidate.observation_hashes,
        human_label_hashes=candidate.human_label_hashes,
        ledger_index_hash=candidate.ledger_index_hash,
        remote_attempts_used=candidate.remote_attempts_used,
    )


def _load_observations(
    *,
    store: ArtifactStore,
    base: Path,
    config: BenchmarkConfig,
    candidate: FormalIntegrationCandidate,
    corpus_by_id: Mapping[str, CorpusSample],
    data_root: Path,
) -> tuple[MetricObservation, ...]:
    expected_paths = tuple(
        base / "observations" / f"{sample_id}.json" for sample_id in config.ordered_sample_ids
    )
    observed_paths = store.list_json(base / "observations")
    if len(observed_paths) != 165 or set(observed_paths) != set(expected_paths):
        raise FormalQualificationError("observation artifact set is not exactly the frozen 165")
    observations: list[MetricObservation] = []
    for index, (path, spec) in enumerate(zip(expected_paths, config.sample_specs, strict=True)):
        payload = store.read_json(path)
        observation = _validate_model(MetricObservation, payload)
        if sha256_json(observation.model_dump(mode="json")) != candidate.observation_hashes[index]:
            raise FormalQualificationError("observation hash does not match candidate")
        sample = corpus_by_id[spec.sample_id]
        if sample.problem_id != spec.problem_id:
            raise FormalQualificationError("benchmark problem identity does not match corpus")
        expected_kind = SampleKind(sample.kind.value)
        if (
            observation.sample_id,
            observation.problem_id,
            observation.sample_kind,
            observation.topic,
            observation.rating_band,
        ) != (
            spec.sample_id,
            spec.problem_id,
            spec.sample_kind,
            spec.topic,
            spec.rating_band,
        ) or expected_kind is not spec.sample_kind:
            raise FormalQualificationError("observation violates frozen sample identity")
        first_error_step = _corpus_first_error_step(sample, data_root=data_root)
        expected_gold = (
            sample.final_expected_correct,
            sample.primary_error is None,
            first_error_step,
            sample.primary_error,
        )
        actual_gold = (
            observation.gold_final_correct,
            observation.gold_process_valid,
            observation.gold_first_error_step,
            observation.gold_taxonomy,
        )
        if actual_gold != expected_gold:
            raise FormalQualificationError("observation gold fields do not match corpus")
        if observation.primary_review_agreement is None or (
            observation.arbitration_used is not (observation.primary_review_agreement is False)
        ):
            raise FormalQualificationError("formal reviewer/arbitration relationship is invalid")
        observations.append(observation)
    return tuple(observations)


def _corpus_first_error_step(sample: CorpusSample, *, data_root: Path) -> int | None:
    if sample.first_error_step_id is None:
        return None
    trace_path = data_root / sample.trace.path
    trace = _read_model(SolutionTrace, trace_path)
    return next(
        step.step_number for step in trace.steps if step.step_id == sample.first_error_step_id
    )


def _load_ledger_events(
    *,
    store: ArtifactStore,
    base: Path,
    ledger: LedgerIndex,
    expected_attempts: int,
) -> tuple[LedgerEvent, ...]:
    if (
        len(ledger.event_paths) != expected_attempts
        or len(set(ledger.event_paths)) != expected_attempts
        or len(set(ledger.event_hashes)) != expected_attempts
        or any(_SHA256.fullmatch(digest) is None for digest in ledger.event_hashes)
    ):
        raise FormalQualificationError("ledger index must be complete and unique")
    expected_paths = tuple(
        base / "ledger" / f"{sequence:06d}.json" for sequence in range(1, expected_attempts + 1)
    )
    if (
        tuple(PurePosixPath(path) for path in ledger.event_paths)
        != tuple(PurePosixPath(path.as_posix()) for path in expected_paths)
        or store.list_json(base / "ledger") != expected_paths
    ):
        raise FormalQualificationError("ledger paths must be safe, canonical, and ordered")
    events: list[LedgerEvent] = []
    for sequence, (path, digest) in enumerate(
        zip(expected_paths, ledger.event_hashes, strict=True), start=1
    ):
        event = _validate_model(LedgerEvent, store.read_json(path))
        if event.sequence != sequence or sha256_json(event.model_dump(mode="json")) != digest:
            raise FormalQualificationError("ledger event sequence or hash mismatch")
        events.append(event)
    return tuple(events)


def _validate_formal_attempt_profile(
    config: BenchmarkConfig,
    observations: tuple[MetricObservation, ...],
    events: tuple[LedgerEvent, ...],
) -> None:
    known = set(config.ordered_sample_ids)
    natural = set(config.generation_sample_ids)
    arbitrated = {row.sample_id for row in observations if row.arbitration_used}
    allowed = {
        config.generator_prompt_version,
        config.logic_review_prompt_version,
        config.adversarial_review_prompt_version,
        config.arbiter_prompt_version,
    }
    for event in events:
        if (
            event.benchmark_id != config.benchmark_id
            or event.sample_id not in known
            or event.operation not in allowed
            or event.phase not in {"request", "schema_repair"}
            or (
                event.operation == config.generator_prompt_version
                and event.sample_id not in natural
            )
            or (
                event.operation == config.arbiter_prompt_version
                and event.sample_id not in arbitrated
            )
        ):
            raise FormalQualificationError("formal attempt profile contains an invalid event")
    required = [
        (sample_id, config.logic_review_prompt_version) for sample_id in config.audit_sample_ids
    ]
    required.extend(
        (sample_id, config.adversarial_review_prompt_version)
        for sample_id in config.audit_sample_ids
    )
    required.extend(
        (sample_id, config.generator_prompt_version) for sample_id in config.generation_sample_ids
    )
    required.extend((sample_id, config.arbiter_prompt_version) for sample_id in arbitrated)
    counts = Counter(
        (event.sample_id, event.operation)
        for event in events
        if event.phase == "request" and event.retry_number == 1
    )
    if any(counts[item] != 1 for item in required):
        raise FormalQualificationError("formal attempt profile is missing a required request")


def _require_canonical_input_path(path: Path, *, root: Path, relative: Path) -> None:
    if path.resolve(strict=True) != (root.resolve(strict=True) / relative):
        raise FormalQualificationError("formal candidate path is not canonical")


def _read_model[ModelT: BaseModel](model: type[ModelT], path: Path) -> ModelT:
    return _validate_model(model, _read_json(path))


def _validate_model[ModelT: BaseModel](model: type[ModelT], value: Any) -> ModelT:
    return model.model_validate_json(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _read_mapping(path: Path) -> Mapping[str, Any]:
    value = _read_json(path)
    if not isinstance(value, Mapping):
        raise FormalQualificationError("formal JSON input must be an object")
    return cast(Mapping[str, Any], value)


def _read_list(path: Path) -> list[Any]:
    value = _read_json(path)
    if not isinstance(value, list):
        raise FormalQualificationError("formal JSON input must be an array")
    return value


def _read_json(path: Path) -> Any:
    snapshot = read_trusted_file(path, logical_id="formal-input", max_bytes=_MAX_JSON_BYTES)
    return json.loads(snapshot.contents)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hy3_algotrace.formal_qualification",
        description=_NONOFFICIAL_DISCLOSURE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--acquisition", type=Path, required=True)
    parser.add_argument("--acquisition-validation", type=Path, required=True)
    parser.add_argument("--validation-raw", type=Path, required=True)
    parser.add_argument("--test-raw", type=Path, required=True)
    parser.add_argument("--validation-format", choices=tuple(DatasetFormat), required=True)
    parser.add_argument("--test-format", choices=tuple(DatasetFormat), required=True)
    parser.add_argument("--validation-reviews", type=Path, required=True)
    parser.add_argument("--test-reviews", type=Path, required=True)
    parser.add_argument("--review-manifest", type=Path, required=True)
    parser.add_argument("--bundles", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--judge-cases", type=Path, required=True)
    parser.add_argument("--judge-report", type=Path, required=True)
    parser.add_argument("--judge-raw-evidence", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--benchmark-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        output = qualify_formal_run(
            FormalQualificationInputs(
                selection_path=arguments.selection,
                acquisition_path=arguments.acquisition,
                acquisition_validation_path=arguments.acquisition_validation,
                raw_asset_paths={
                    "validation": arguments.validation_raw,
                    "test": arguments.test_raw,
                },
                data_formats={
                    "validation": DatasetFormat(arguments.validation_format),
                    "test": DatasetFormat(arguments.test_format),
                },
                review_artifact_paths={
                    "validation": arguments.validation_reviews,
                    "test": arguments.test_reviews,
                },
                review_manifest_path=arguments.review_manifest,
                bundle_manifest_path=arguments.bundles,
                corpus_manifest_path=arguments.corpus,
                data_root=arguments.data_root,
                judge_cases_path=arguments.judge_cases,
                judge_report_path=arguments.judge_report,
                raw_judge_evidence_path=arguments.judge_raw_evidence,
                candidate_path=arguments.candidate,
                benchmark_artifact_root=arguments.benchmark_root,
                output_root=arguments.output_root,
            )
        )
    except (ArtifactExistsError, FormalQualificationError):
        print("formal qualification failed closed", file=sys.stderr)
        return 2
    print(f"formal qualification report:{output}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
