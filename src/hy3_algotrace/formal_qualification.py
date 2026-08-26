"""Same-process, fail-closed Task 7 to Task 6 formal qualification bridge."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .artifacts import ArtifactExistsError, ArtifactStore, ArtifactStoreError, sha256_json
from .benchmark import formal_attempt_profile_is_valid
from .benchmark_models import (
    BenchmarkConfig,
    BlindPublicExample,
    FormalIntegrationCandidate,
    HumanConfirmedLabel,
    HumanConfirmedLabelSet,
    HumanDecisionChange,
    HumanDecisionSet,
    HumanRereviewAgreement,
    HumanReviewCandidate,
    HumanReviewExport,
    HumanReviewMapping,
    HumanReviewReplay,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    SampleKind,
)
from .contracts import JudgeEvidence, ProblemRecord, SolutionTrace
from .corpus import (
    CorpusManifest,
    CorpusSample,
    CorpusSampleKind,
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
from .human_review import build_blind_batch
from .hy3_client import build_cache_key, generation_input
from .prompts import GENERATOR_SYSTEM_PROMPT

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
    natural_materialization_path: Path
    data_root: Path
    judge_cases_path: Path
    judge_report_path: Path
    raw_judge_evidence_path: Path
    candidate_path: Path
    human_review_export_path: Path
    human_review_mapping_path: Path
    human_decisions_path: Path
    human_review_replay_path: Path
    benchmark_artifact_root: Path
    output_root: Path


type JsonScalar = str | int | float | bool | None
type JsonScalarType = Literal["string", "integer", "number", "boolean", "null"]


class NaturalMaterializationParameter(BaseModel):
    """One type-preserving JSON scalar used by a natural generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    json_type: JsonScalarType
    value: JsonScalar

    @model_validator(mode="after")
    def validate_json_type(self) -> Self:
        if self.json_type != _json_scalar_type(self.value):
            raise ValueError("natural materialization parameter JSON type does not match")
        return self


class NaturalMaterializationEntry(BaseModel):
    """Content and request provenance for one immutable natural output."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,255}$")
    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    trace_path: str = Field(min_length=1, max_length=1_024)
    trace_byte_length: int = Field(gt=0, strict=True)
    trace_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parsed_trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_path: str = Field(min_length=1, max_length=1_024)
    source_byte_length: int = Field(gt=0, strict=True)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    problem_record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1, max_length=256)
    endpoint_identity: str = Field(min_length=1, max_length=2_048)
    generator_prompt_version: str = Field(min_length=1, max_length=128)
    generator_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_parameters: tuple[NaturalMaterializationParameter, ...]
    model_visible_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation_event_hashes: tuple[str, ...] = Field(min_length=1)

    @field_validator("trace_path", "source_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("natural materialization paths must be safe and relative")
        return value

    @field_validator("generation_event_hashes")
    @classmethod
    def validate_event_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values) or any(
            _SHA256.fullmatch(value) is None for value in values
        ):
            raise ValueError("natural generation event hashes must be unique SHA-256 values")
        return values


class NaturalMaterializationManifest(BaseModel):
    """Content-addressed immutable provenance for all sixty natural outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["natural_hy3_materialization_manifest"] = "natural_hy3_materialization_manifest"
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[NaturalMaterializationEntry, ...] = Field(min_length=60, max_length=60)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ids = tuple(entry.sample_id for entry in self.entries)
        if len(set(ids)) != 60:
            raise ValueError("natural materialization requires 60 unique sample IDs")
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        if self.content_hash != sha256_json(payload):
            raise ValueError("natural materialization content_hash does not match")
        return self


def _json_scalar_type(value: JsonScalar) -> JsonScalarType:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _typed_parameter_identity(
    parameters: Sequence[Any],
) -> tuple[tuple[str, JsonScalarType, JsonScalar], ...]:
    return tuple(
        (parameter.name, _json_scalar_type(parameter.value), parameter.value)
        for parameter in parameters
    )


class FormalQualificationReport(BaseModel):
    """Safe immutable hash summary; deserializing it never restores eligibility."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["formal_qualification_report"] = "formal_qualification_report"
    benchmark_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    natural_materialization_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_labels_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    human_review_provenance_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
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
        natural_materialization_hash: str,
        judge_evidence_hash: str,
        candidate_hash: str,
        config_hash: str,
        observation_hashes: tuple[str, ...],
        human_label_hashes: tuple[str, ...],
        human_review_provenance_hash: str,
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
            "natural_materialization_hash": natural_materialization_hash,
            "judge_evidence_hash": judge_evidence_hash,
            "candidate_hash": candidate_hash,
            "config_hash": config_hash,
            "observations_hash": sha256_json(list(observation_hashes)),
            "human_labels_hash": sha256_json(list(human_label_hashes)),
            "human_review_provenance_hash": human_review_provenance_hash,
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
    except ArtifactStoreError as error:
        raise FormalQualificationError("formal qualification failed closed") from error
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
    corpus_payload = _read_mapping(inputs.corpus_manifest_path)
    corpus = _validate_model(CorpusManifest, corpus_payload)
    audit = lint_corpus_manifest(
        corpus_payload,
        root=inputs.data_root,
        selection=selection,
        bundle_manifest=bundle_manifest,
    )
    if corpus.status is not CorpusStatus.COMPLETE or len(corpus.samples) != 165:
        raise FormalQualificationError("formal corpus must contain all 165 samples")
    if audit.materialized_counts != audit.expected_counts:
        raise FormalQualificationError("formal corpus counts are incomplete")
    materialization = _read_model(
        NaturalMaterializationManifest, inputs.natural_materialization_path
    )
    _require_canonical_input_path(
        inputs.natural_materialization_path,
        root=inputs.data_root,
        relative=Path("natural-materialization") / f"{materialization.content_hash}.json",
    )

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
        materialization=materialization,
        selected_records=_selected_problem_records(selection, cases),
    )


def _qualify_benchmark_chain(
    *,
    inputs: FormalQualificationInputs,
    corpus: CorpusManifest,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
    judge_payload: Mapping[str, Any],
    judge_result: FormalCorpusJudgeValidationResult,
    materialization: NaturalMaterializationManifest,
    selected_records: Mapping[str, ProblemRecord],
) -> FormalQualificationReport:
    if (
        not isinstance(judge_result, FormalCorpusJudgeValidationResult)
        or not judge_result._is_verified()
    ):
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
    review_export = _read_model(HumanReviewExport, inputs.human_review_export_path)
    review_mapping = _read_model(HumanReviewMapping, inputs.human_review_mapping_path)
    decisions = _read_model(HumanDecisionSet, inputs.human_decisions_path)
    review_replay = _read_model(HumanReviewReplay, inputs.human_review_replay_path)
    review_root = Path("human-review") / review_export.batch_id
    _require_canonical_input_path(
        inputs.human_review_export_path,
        root=inputs.benchmark_artifact_root,
        relative=review_root / "export.json",
    )
    _require_canonical_input_path(
        inputs.human_review_mapping_path,
        root=inputs.benchmark_artifact_root,
        relative=review_root / "mapping.json",
    )
    _require_canonical_input_path(
        inputs.human_decisions_path,
        root=inputs.benchmark_artifact_root,
        relative=review_root / "decisions" / f"{decisions.decision_set_id}.json",
    )
    _require_canonical_input_path(
        inputs.human_review_replay_path,
        root=inputs.benchmark_artifact_root,
        relative=review_root / "replays" / f"{review_replay.replay_id}.json",
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
    if (
        config.model != natural_config.model_name
        or config.endpoint_identity != natural_config.endpoint_url
        or config.generator_prompt_version != natural_config.prompt_version
        or _typed_parameter_identity(config.model_parameters)
        != _typed_parameter_identity(natural_config.model_parameters)
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
    human_review_provenance_hash = _validate_human_review_chain(
        export=review_export,
        mapping=review_mapping,
        decisions=decisions,
        replay=review_replay,
        corpus=corpus,
        selected_records=selected_records,
        observations=observations,
        labels=labels,
        data_root=inputs.data_root,
    )

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
    _validate_natural_materialization(
        manifest=materialization,
        corpus=corpus,
        selected_records=selected_records,
        config=config,
        events=events,
        event_hashes=ledger.event_hashes,
        data_root=inputs.data_root,
    )
    return FormalQualificationReport.create(
        benchmark_id=config.benchmark_id,
        selection_hash=config.selection_hash,
        bundle_manifest_hash=bundle_manifest.content_hash,
        corpus_hash=config.corpus_hash,
        natural_materialization_hash=materialization.content_hash,
        judge_evidence_hash=judge_artifact_hash,
        candidate_hash=sha256_json(candidate.model_dump(mode="json")),
        config_hash=candidate.config_hash,
        observation_hashes=candidate.observation_hashes,
        human_label_hashes=candidate.human_label_hashes,
        human_review_provenance_hash=human_review_provenance_hash,
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


def _selected_problem_records(
    selection: FrozenSelectionManifest,
    cases: tuple[JudgeSourceCase, ...],
) -> Mapping[str, ProblemRecord]:
    records: dict[str, ProblemRecord] = {}
    for case in cases:
        existing = records.setdefault(case.problem.problem_id, case.problem)
        if existing != case.problem:
            raise FormalQualificationError("Judge cases disagree on selected problem records")
    expected_ids = tuple(entry.problem_id for entry in selection.entries)
    if set(records) != set(expected_ids):
        raise FormalQualificationError("Judge cases do not cover every selected problem record")
    return {problem_id: records[problem_id] for problem_id in expected_ids}


def _validate_natural_materialization(
    *,
    manifest: NaturalMaterializationManifest,
    corpus: CorpusManifest,
    selected_records: Mapping[str, ProblemRecord],
    config: BenchmarkConfig,
    events: tuple[LedgerEvent, ...],
    event_hashes: tuple[str, ...],
    data_root: Path,
) -> None:
    natural_config = corpus.natural_run_config
    if (
        natural_config.materialization_manifest_hash != manifest.content_hash
        or manifest.selection_manifest_hash != corpus.selection_manifest_hash
    ):
        raise FormalQualificationError("natural materialization identity does not match corpus")
    actual_prompt_hash = hashlib.sha256(GENERATOR_SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if natural_config.prompt_hash != actual_prompt_hash:
        raise FormalQualificationError("natural generator prompt hash is not repository-authentic")
    natural_samples = tuple(
        sample for sample in corpus.samples if sample.kind is CorpusSampleKind.NATURAL
    )
    if tuple(entry.sample_id for entry in manifest.entries) != tuple(
        sample.sample_id for sample in natural_samples
    ):
        raise FormalQualificationError("natural materialization must follow canonical corpus order")
    if len(events) != len(event_hashes):
        raise FormalQualificationError("natural materialization ledger hashes are incomplete")
    parameters = {parameter.name: parameter.value for parameter in natural_config.model_parameters}
    parameter_identity = _typed_parameter_identity(natural_config.model_parameters)
    hashed_events = tuple(zip(events, event_hashes, strict=True))
    for entry, sample in zip(manifest.entries, natural_samples, strict=True):
        record = selected_records.get(sample.problem_id)
        if record is None:
            raise FormalQualificationError("natural sample problem is outside verified selection")
        trace_snapshot = read_trusted_file(
            data_root / sample.trace.path,
            logical_id=f"natural-trace-{sample.sample_id}",
            max_bytes=sample.trace.byte_length,
        )
        source_snapshot = read_trusted_file(
            data_root / sample.cpp_source.path,
            logical_id=f"natural-source-{sample.sample_id}",
            max_bytes=sample.cpp_source.byte_length,
        )
        if (trace_snapshot.byte_length, trace_snapshot.sha256) != (
            sample.trace.byte_length,
            sample.trace.sha256,
        ) or (source_snapshot.byte_length, source_snapshot.sha256) != (
            sample.cpp_source.byte_length,
            sample.cpp_source.sha256,
        ):
            raise FormalQualificationError("natural corpus bytes changed after lint")
        trace = SolutionTrace.model_validate_json(trace_snapshot.contents)
        source = source_snapshot.contents.decode("utf-8")
        visible_input = generation_input(record)
        expected_event_hashes = tuple(
            event_hash
            for event, event_hash in hashed_events
            if event.sample_id == sample.sample_id
            and event.operation == natural_config.prompt_version
        )
        expected_entry_identity = (
            sample.sample_id,
            sample.problem_id,
            sample.trace.path,
            sample.trace.byte_length,
            sample.trace.sha256,
            sha256_json(trace.model_dump(mode="json")),
            sample.cpp_source.path,
            sample.cpp_source.byte_length,
            sample.cpp_source.sha256,
            sha256_json(record.model_dump(mode="json")),
            natural_config.model_name,
            natural_config.endpoint_url,
            natural_config.prompt_version,
            actual_prompt_hash,
            parameter_identity,
            sha256_json(visible_input),
            build_cache_key(
                model=natural_config.model_name,
                endpoint=natural_config.endpoint_url,
                prompt_version=natural_config.prompt_version,
                parameters=parameters,
                canonical_input=visible_input,
            ),
            expected_event_hashes,
        )
        observed_entry_identity = (
            entry.sample_id,
            entry.problem_id,
            entry.trace_path,
            entry.trace_byte_length,
            entry.trace_sha256,
            entry.parsed_trace_hash,
            entry.source_path,
            entry.source_byte_length,
            entry.source_sha256,
            entry.problem_record_hash,
            entry.model_name,
            entry.endpoint_identity,
            entry.generator_prompt_version,
            entry.generator_prompt_hash,
            _typed_parameter_identity(entry.model_parameters),
            entry.model_visible_input_hash,
            entry.request_cache_key,
            entry.generation_event_hashes,
        )
        if (
            trace.trace_id != sample.sample_id
            or trace.problem_id != sample.problem_id
            or trace.code != source
            or observed_entry_identity != expected_entry_identity
        ):
            raise FormalQualificationError("natural materialization row is inconsistent")
    if tuple(sample.sample_id for sample in natural_samples) != config.generation_sample_ids:
        raise FormalQualificationError(
            "natural materialization does not match benchmark generation"
        )


def _validate_human_review_chain(
    *,
    export: HumanReviewExport,
    mapping: HumanReviewMapping,
    decisions: HumanDecisionSet,
    replay: HumanReviewReplay,
    corpus: CorpusManifest,
    selected_records: Mapping[str, ProblemRecord],
    observations: tuple[MetricObservation, ...],
    labels: HumanConfirmedLabelSet,
    data_root: Path,
) -> str:
    if (
        len(export.items) != 165
        or len(mapping.entries) != 165
        or export.batch_id != mapping.batch_id
        or decisions.batch_id != export.batch_id
        or replay.batch_id != export.batch_id
        or replay.source_decision_set_id != decisions.decision_set_id
    ):
        raise FormalQualificationError("human-review batch identities are incomplete")
    candidates: list[HumanReviewCandidate] = []
    for sample in corpus.samples:
        record = selected_records.get(sample.problem_id)
        if record is None:
            raise FormalQualificationError("human-review problem is outside verified selection")
        snapshot = read_trusted_file(
            data_root / sample.trace.path,
            logical_id=f"human-review-trace-{sample.sample_id}",
            max_bytes=sample.trace.byte_length,
        )
        if (snapshot.byte_length, snapshot.sha256) != (
            sample.trace.byte_length,
            sample.trace.sha256,
        ):
            raise FormalQualificationError("human-review trace changed after corpus lint")
        trace = SolutionTrace.model_validate_json(snapshot.contents)
        candidates.append(
            HumanReviewCandidate(
                sample_id=sample.sample_id,
                problem_id=sample.problem_id,
                trace_id=trace.trace_id,
                statement=record.statement_en,
                public_examples=tuple(
                    BlindPublicExample(
                        input_data=test.input_data,
                        output_data=test.expected_output,
                    )
                    for test in record.public_tests
                ),
                trace=trace,
            )
        )
    expected_export, expected_mapping = build_blind_batch(
        batch_id=export.batch_id,
        candidates=tuple(candidates),
        blind_ids=tuple(item.blind_id for item in export.items),
    )
    if export != expected_export or mapping != expected_mapping:
        raise FormalQualificationError("human-review blind export or mapping is inconsistent")
    mapping_ids = tuple(entry.blind_id for entry in mapping.entries)
    initial_ids = tuple(decision.blind_id for decision in decisions.initial_decisions)
    if initial_ids != mapping_ids or len(initial_ids) != 165:
        raise FormalQualificationError(
            "human-review initial decisions must be complete and ordered"
        )
    initial_by_blind = {decision.blind_id: decision for decision in decisions.initial_decisions}
    delayed_by_blind = {decision.blind_id: decision for decision in decisions.delayed_decisions}
    if any(
        delayed.reviewer_id != initial_by_blind[delayed.blind_id].reviewer_id
        for delayed in decisions.delayed_decisions
    ):
        raise FormalQualificationError("delayed rereview reviewer identity changed")
    final_by_blind = {
        blind_id: delayed_by_blind.get(blind_id, initial)
        for blind_id, initial in initial_by_blind.items()
    }
    expected_labels = tuple(
        HumanConfirmedLabel(
            sample_id=entry.sample_id,
            final_correct=final_by_blind[entry.blind_id].final_correct,
            process_valid=final_by_blind[entry.blind_id].process_valid,
            first_error_step=final_by_blind[entry.blind_id].first_error_step,
            taxonomy=final_by_blind[entry.blind_id].taxonomy,
        )
        for entry in mapping.entries
    )
    changes = tuple(
        HumanDecisionChange(
            blind_id=delayed.blind_id,
            initial_decision_id=initial_by_blind[delayed.blind_id].decision_id,
            delayed_decision_id=delayed.decision_id,
            changed_fields=tuple(
                field
                for field in (
                    "final_correct",
                    "process_valid",
                    "first_error_step",
                    "taxonomy",
                )
                if getattr(initial_by_blind[delayed.blind_id], field) != getattr(delayed, field)
            ),
        )
        for delayed in decisions.delayed_decisions
        if any(
            getattr(initial_by_blind[delayed.blind_id], field) != getattr(delayed, field)
            for field in (
                "final_correct",
                "process_valid",
                "first_error_step",
                "taxonomy",
            )
        )
    )
    rereviewed_count = len(decisions.delayed_decisions)
    agreement = HumanRereviewAgreement(
        rereviewed_count=rereviewed_count,
        unchanged_count=rereviewed_count - len(changes),
        agreement=(rereviewed_count - len(changes)) / rereviewed_count,
        changes=changes,
    )
    expected_replay = HumanReviewReplay(
        replay_id=replay.replay_id,
        batch_id=export.batch_id,
        source_decision_set_id=decisions.decision_set_id,
        observations=observations,
        human_labels=expected_labels,
        rereview_agreement=agreement,
    )
    if replay != expected_replay or expected_labels != labels.labels:
        raise FormalQualificationError("human-review replay does not match benchmark artifacts")
    return sha256_json(
        {
            "export_hash": sha256_json(export.model_dump(mode="json")),
            "mapping_hash": sha256_json(mapping.model_dump(mode="json")),
            "decisions_hash": sha256_json(decisions.model_dump(mode="json")),
            "replay_hash": sha256_json(replay.model_dump(mode="json")),
        }
    )


def _corpus_first_error_step(sample: CorpusSample, *, data_root: Path) -> int | None:
    if sample.first_error_step_id is None:
        return None
    trace_path = data_root / sample.trace.path
    snapshot = read_trusted_file(
        trace_path,
        logical_id=f"formal-trace-{sample.sample_id}",
        max_bytes=sample.trace.byte_length,
    )
    if snapshot.byte_length != sample.trace.byte_length or snapshot.sha256 != sample.trace.sha256:
        raise FormalQualificationError("corpus trace changed after validation")
    trace = SolutionTrace.model_validate_json(snapshot.contents)
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
    if not formal_attempt_profile_is_valid(config, observations, events):
        raise FormalQualificationError("formal attempt profile contains an invalid event sequence")


def _require_canonical_input_path(path: Path, *, root: Path, relative: Path) -> None:
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise FormalQualificationError("formal candidate path is not canonical")
    resolved_root = root.resolve(strict=True)
    expected = resolved_root / relative
    component = resolved_root
    for part in relative.parts:
        component /= part
        if component.is_symlink():
            raise FormalQualificationError("formal candidate path is not canonical")
    resolved_expected = expected.resolve(strict=True)
    if path != expected or not resolved_expected.is_relative_to(resolved_root):
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
    parser.add_argument("--natural-materialization", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--judge-cases", type=Path, required=True)
    parser.add_argument("--judge-report", type=Path, required=True)
    parser.add_argument("--judge-raw-evidence", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--human-review-export", type=Path, required=True)
    parser.add_argument("--human-review-mapping", type=Path, required=True)
    parser.add_argument("--human-decisions", type=Path, required=True)
    parser.add_argument("--human-review-replay", type=Path, required=True)
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
                natural_materialization_path=arguments.natural_materialization,
                data_root=arguments.data_root,
                judge_cases_path=arguments.judge_cases,
                judge_report_path=arguments.judge_report,
                raw_judge_evidence_path=arguments.judge_raw_evidence,
                candidate_path=arguments.candidate,
                human_review_export_path=arguments.human_review_export,
                human_review_mapping_path=arguments.human_review_mapping,
                human_decisions_path=arguments.human_decisions,
                human_review_replay_path=arguments.human_review_replay,
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
