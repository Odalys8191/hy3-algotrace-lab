"""Strict project-authored bundle and 30/60/15/60 corpus auditing."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator, model_validator

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import (
    ErrorTaxonomy,
    ProblemOracle,
    SolutionTrace,
    StepStatus,
)
from hy3_algotrace.dataset_models import (
    DATASET_SCHEMA_VERSION,
    DatasetModel,
    FrozenSelectionManifest,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_BUNDLE_PARTS = frozenset({"hidden", "hidden_tests", "private_tests", "generated_tests"})


class CorpusDataError(ValueError):
    """Raised when authored material or a corpus freeze is inconsistent."""


class ArtifactMediaType(StrEnum):
    JSON = "application/json"
    CPP = "text/x-c++src"


class ArtifactProvenance(StrEnum):
    PROJECT_AUTHORED = "project_authored"
    HY3_OUTPUT = "hy3_output"


class CorpusSampleKind(StrEnum):
    GOLD = "gold"
    CONTROLLED_WRONG = "controlled_wrong"
    PARADOX = "paradox"
    NATURAL = "natural"


class NaturalRunStatus(StrEnum):
    PENDING_CREDENTIALS = "pending_credentials"
    COMPLETE = "complete"


class CorpusStatus(StrEnum):
    PENDING_CREDENTIALS = "pending_credentials"
    COMPLETE = "complete"


class ArtifactRef(DatasetModel):
    """Content-addressed relative reference; artifact bytes are never embedded."""

    path: str = Field(min_length=1, max_length=1_024)
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: ArtifactMediaType
    provenance: ArtifactProvenance

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        candidate = PurePosixPath(value)
        if (
            value != value.strip()
            or "\\" in value
            or "\x00" in value
            or candidate.is_absolute()
            or not candidate.parts
            or any(part in {"", ".", ".."} for part in candidate.parts)
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("artifact path must be a safe relative POSIX path")
        return value

    @model_validator(mode="after")
    def validate_extension(self) -> Self:
        suffix = PurePosixPath(self.path).suffix.casefold()
        expected = ".json" if self.media_type is ArtifactMediaType.JSON else ".cpp"
        if suffix != expected:
            raise ValueError("artifact extension must match media_type")
        return self


class AuthoredBundleEntry(DatasetModel):
    """Project-authored material linked to one selected third-party statement."""

    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    selection_entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_cpp: ArtifactRef
    oracle: ArtifactRef
    gold_trace: ArtifactRef
    mutants: tuple[ArtifactRef, ...] = Field(min_length=2, max_length=2)
    authoring_attestation: Literal["project_authored"]
    third_party_submitted_code_included: Literal[False]

    @model_validator(mode="after")
    def validate_artifacts(self) -> Self:
        artifacts = (self.reference_cpp, self.oracle, self.gold_trace, *self.mutants)
        if any(
            artifact.provenance is not ArtifactProvenance.PROJECT_AUTHORED for artifact in artifacts
        ):
            raise ValueError("bundle artifacts must be project-authored")
        if self.reference_cpp.media_type is not ArtifactMediaType.CPP or any(
            mutant.media_type is not ArtifactMediaType.CPP for mutant in self.mutants
        ):
            raise ValueError("reference and mutant artifacts must be C++")
        if self.oracle.media_type is not ArtifactMediaType.JSON or (
            self.gold_trace.media_type is not ArtifactMediaType.JSON
        ):
            raise ValueError("oracle and gold trace artifacts must be JSON")
        expected_prefix = ("problems", self.problem_id)
        for artifact in artifacts:
            parts = PurePosixPath(artifact.path).parts
            if parts[:2] != expected_prefix:
                raise ValueError("bundle artifact path must be scoped to its problem ID")
            if {part.casefold() for part in parts}.intersection(_FORBIDDEN_BUNDLE_PARTS):
                raise ValueError("public authored bundle must not contain hidden test material")
        if len({artifact.path for artifact in artifacts}) != len(artifacts):
            raise ValueError("bundle artifact paths must be unique")
        source_hashes = [self.reference_cpp.sha256, *(item.sha256 for item in self.mutants)]
        if len(set(source_hashes)) != 3:
            raise ValueError("reference and mutant source hashes must be distinct")
        return self


class ProjectBundleManifest(DatasetModel):
    """Frozen manifest of exactly thirty project-authored bundles."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["project_authored_problem_bundles"] = "project_authored_problem_bundles"
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundles: tuple[AuthoredBundleEntry, ...] = Field(min_length=30, max_length=30)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ids = [bundle.problem_id for bundle in self.bundles]
        if len(set(ids)) != 30:
            raise ValueError("bundle manifest requires 30 unique problem IDs")
        if ids != sorted(ids):
            raise ValueError("bundle manifest problem IDs must be sorted")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("bundle manifest content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)


type FrozenParameterValue = str | int | float | bool | None


class FrozenModelParameter(DatasetModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    value: FrozenParameterValue

    @field_validator("value")
    @classmethod
    def reject_nonfinite(cls, value: FrozenParameterValue) -> FrozenParameterValue:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("model parameter floats must be finite")
        return value


class NaturalRunConfig(DatasetModel):
    """Immutable configuration for two natural Hy3 generations per problem."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["natural_hy3_run_config"] = "natural_hy3_run_config"
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    problem_ids: tuple[str, ...] = Field(min_length=30, max_length=30)
    samples_per_problem: Literal[2] = 2
    target_sample_count: Literal[60] = 60
    prompt_version: str = Field(min_length=1, max_length=128)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_name: str = Field(min_length=1, max_length=256)
    endpoint_url: str = Field(min_length=1, max_length=2_048)
    model_parameters: tuple[FrozenModelParameter, ...]
    credential_env_var: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,127}$")
    status: NaturalRunStatus
    pending_reason: str = Field(default="", max_length=1_000)
    materialization_manifest_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("prompt_version", "model_name", "pending_reason")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("run configuration text must be trimmed and contain no NUL")
        return value

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("natural run endpoint must be an HTTPS URL without credentials")
        return value

    @model_validator(mode="after")
    def validate_run(self) -> Self:
        if len(set(self.problem_ids)) != 30:
            raise ValueError("natural run requires 30 unique problem IDs")
        names = [parameter.name for parameter in self.model_parameters]
        if len(set(names)) != len(names) or names != sorted(names):
            raise ValueError("model parameters must have unique names in sorted order")
        if self.status is NaturalRunStatus.PENDING_CREDENTIALS:
            if not self.pending_reason or self.materialization_manifest_hash is not None:
                raise ValueError("pending run requires a reason and no materialization hash")
        elif self.pending_reason or self.materialization_manifest_hash is None:
            raise ValueError("complete run requires a materialization hash and no pending reason")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("natural run config content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)

    @classmethod
    def create(
        cls,
        *,
        selection_manifest_hash: str,
        problem_ids: tuple[str, ...],
        prompt_version: str,
        prompt_hash: str,
        model_name: str,
        endpoint_url: str,
        model_parameters: tuple[FrozenModelParameter, ...],
        credential_env_var: str,
        status: NaturalRunStatus,
        pending_reason: str = "",
        materialization_manifest_hash: str | None = None,
    ) -> NaturalRunConfig:
        canonical_parameters = tuple(sorted(model_parameters, key=lambda parameter: parameter.name))
        payload: dict[str, Any] = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "kind": "natural_hy3_run_config",
            "selection_manifest_hash": selection_manifest_hash,
            "problem_ids": list(problem_ids),
            "samples_per_problem": 2,
            "target_sample_count": 60,
            "prompt_version": prompt_version,
            "prompt_hash": prompt_hash,
            "model_name": model_name,
            "endpoint_url": endpoint_url,
            "model_parameters": [
                parameter.model_dump(mode="json") for parameter in canonical_parameters
            ],
            "credential_env_var": credential_env_var,
            "status": status.value,
            "pending_reason": pending_reason,
            "materialization_manifest_hash": materialization_manifest_hash,
        }
        return cls(
            selection_manifest_hash=selection_manifest_hash,
            problem_ids=problem_ids,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            model_name=model_name,
            endpoint_url=endpoint_url,
            model_parameters=canonical_parameters,
            credential_env_var=credential_env_var,
            status=status,
            pending_reason=pending_reason,
            materialization_manifest_hash=materialization_manifest_hash,
            content_hash=sha256_json(payload),
        )


class CorpusSample(DatasetModel):
    """One hash-linked authored or natural reasoning/code sample."""

    sample_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,255}$")
    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    kind: CorpusSampleKind
    trace: ArtifactRef
    cpp_source: ArtifactRef
    final_expected_correct: bool
    primary_error: ErrorTaxonomy | None = None
    first_error_step_id: str | None = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_sample(self) -> Self:
        if self.trace.media_type is not ArtifactMediaType.JSON:
            raise ValueError("sample trace must be JSON")
        if self.cpp_source.media_type is not ArtifactMediaType.CPP:
            raise ValueError("sample code must be C++")
        expected_provenance = (
            ArtifactProvenance.HY3_OUTPUT
            if self.kind is CorpusSampleKind.NATURAL
            else ArtifactProvenance.PROJECT_AUTHORED
        )
        if (
            self.trace.provenance is not expected_provenance
            or self.cpp_source.provenance is not expected_provenance
        ):
            raise ValueError("sample artifact provenance does not match its kind")
        has_error = self.primary_error is not None and self.first_error_step_id is not None
        partial_error = (self.primary_error is None) != (self.first_error_step_id is None)
        if partial_error:
            raise ValueError("primary_error and first_error_step_id must appear together")
        if self.kind is CorpusSampleKind.GOLD:
            if not self.final_expected_correct or has_error:
                raise ValueError("gold samples must be correct with no primary error")
        elif self.kind is CorpusSampleKind.CONTROLLED_WRONG:
            if self.final_expected_correct or not has_error:
                raise ValueError(
                    "controlled wrong samples require primary_error and first_error_step_id"
                )
        elif self.kind is CorpusSampleKind.PARADOX:
            if not self.final_expected_correct or not has_error:
                raise ValueError("paradox samples must be correct and identify their process error")
        prefix = ("corpus", self.kind.value)
        for artifact in (self.trace, self.cpp_source):
            if PurePosixPath(artifact.path).parts[:2] != prefix:
                raise ValueError("sample artifact path must be scoped to its corpus kind")
        return self


class CorpusManifest(DatasetModel):
    """Frozen corpus: 105 controlled samples plus zero or sixty natural outputs."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["algotrace_formal_corpus"] = "algotrace_formal_corpus"
    selection_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CorpusStatus
    natural_run_config: NaturalRunConfig
    samples: tuple[CorpusSample, ...] = Field(min_length=105, max_length=165)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        ids = [sample.sample_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus sample IDs must be unique")
        expected_order = sorted(
            self.samples,
            key=lambda sample: (
                list(CorpusSampleKind).index(sample.kind),
                sample.problem_id,
                sample.sample_id,
            ),
        )
        if list(self.samples) != expected_order:
            raise ValueError("corpus samples must use canonical kind/problem/sample order")
        counts = Counter(sample.kind for sample in self.samples)
        expected_natural = 0 if self.status is CorpusStatus.PENDING_CREDENTIALS else 60
        expected = {
            CorpusSampleKind.GOLD: 30,
            CorpusSampleKind.CONTROLLED_WRONG: 60,
            CorpusSampleKind.PARADOX: 15,
            CorpusSampleKind.NATURAL: expected_natural,
        }
        if any(counts[kind] != count for kind, count in expected.items()):
            raise ValueError("corpus counts must be exactly 30/60/15/0-or-60")
        expected_run_status = (
            NaturalRunStatus.PENDING_CREDENTIALS
            if self.status is CorpusStatus.PENDING_CREDENTIALS
            else NaturalRunStatus.COMPLETE
        )
        if self.natural_run_config.status is not expected_run_status:
            raise ValueError("corpus and natural run statuses must agree")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("corpus manifest content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)


class CorpusAuditReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["algotrace_corpus_audit"] = "algotrace_corpus_audit"
    corpus_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: CorpusStatus
    materialized_counts: dict[str, int]
    expected_counts: dict[str, int]
    credentials_pending: bool
    formal_eligibility: Literal[False] = False
    judge_evidence_pending: Literal[True] = True


def build_project_bundle_manifest(
    selection: FrozenSelectionManifest,
    bundles: Iterable[AuthoredBundleEntry],
) -> ProjectBundleManifest:
    """Bind exactly one project-authored bundle to every frozen selection row."""

    materialized = tuple(sorted(bundles, key=lambda bundle: bundle.problem_id))
    expected = {entry.problem_id: entry for entry in selection.entries}
    if set(bundle.problem_id for bundle in materialized) != set(expected):
        raise CorpusDataError("bundle problem IDs must exactly match frozen selection")
    for bundle in materialized:
        expected_hash = sha256_json(expected[bundle.problem_id].model_dump(mode="json"))
        if bundle.selection_entry_hash != expected_hash:
            raise CorpusDataError(f"bundle selection entry hash mismatch: {bundle.problem_id}")
    payload: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "project_authored_problem_bundles",
        "selection_manifest_hash": selection.content_hash,
        "bundles": [bundle.model_dump(mode="json") for bundle in materialized],
    }
    return ProjectBundleManifest(
        selection_manifest_hash=selection.content_hash,
        bundles=materialized,
        content_hash=sha256_json(payload),
    )


def lint_project_bundles(
    payload: Mapping[str, Any],
    *,
    root: Path | str,
    selection: FrozenSelectionManifest,
) -> ProjectBundleManifest:
    """Validate manifest linkage and every referenced project-authored byte."""

    manifest = _parse_model(ProjectBundleManifest, payload, "bundle manifest")
    expected = build_project_bundle_manifest(selection, manifest.bundles)
    if manifest != expected:
        raise CorpusDataError("bundle manifest does not match frozen selection")
    _verify_artifacts(
        root,
        (
            artifact
            for bundle in manifest.bundles
            for artifact in (
                bundle.reference_cpp,
                bundle.oracle,
                bundle.gold_trace,
                *bundle.mutants,
            )
        ),
    )
    for bundle in manifest.bundles:
        _lint_bundle_contents(Path(root), bundle)
    return manifest


def build_corpus_manifest(
    *,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
    samples: Iterable[CorpusSample],
    natural_run_config: NaturalRunConfig,
    status: CorpusStatus,
) -> CorpusManifest:
    """Freeze controlled samples and either a pending or complete natural run."""

    if bundle_manifest.selection_manifest_hash != selection.content_hash:
        raise CorpusDataError("bundle manifest does not match selection")
    if natural_run_config.selection_manifest_hash != selection.content_hash:
        raise CorpusDataError("natural run config does not match selection")
    expected_problem_ids = tuple(entry.problem_id for entry in selection.entries)
    if natural_run_config.problem_ids != expected_problem_ids:
        raise CorpusDataError("natural run problem IDs must exactly match frozen selection")
    materialized = tuple(
        sorted(
            samples,
            key=lambda sample: (
                list(CorpusSampleKind).index(sample.kind),
                sample.problem_id,
                sample.sample_id,
            ),
        )
    )
    _validate_sample_distribution(materialized, selection, status=status)
    payload: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "algotrace_formal_corpus",
        "selection_manifest_hash": selection.content_hash,
        "bundle_manifest_hash": bundle_manifest.content_hash,
        "status": status.value,
        "natural_run_config": natural_run_config.model_dump(mode="json"),
        "samples": [sample.model_dump(mode="json") for sample in materialized],
    }
    return CorpusManifest(
        selection_manifest_hash=selection.content_hash,
        bundle_manifest_hash=bundle_manifest.content_hash,
        status=status,
        natural_run_config=natural_run_config,
        samples=materialized,
        content_hash=sha256_json(payload),
    )


def lint_corpus_manifest(
    payload: Mapping[str, Any],
    *,
    root: Path | str,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
) -> CorpusAuditReport:
    """Audit corpus hashes, counts, labels, linkage, and pending semantics."""

    manifest = _parse_model(CorpusManifest, payload, "corpus manifest")
    expected = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=manifest.samples,
        natural_run_config=manifest.natural_run_config,
        status=manifest.status,
    )
    if manifest != expected:
        raise CorpusDataError("corpus manifest does not match frozen inputs")
    validate_corpus_bundle_links(manifest, bundle_manifest)
    _verify_artifacts(
        root,
        (artifact for sample in manifest.samples for artifact in (sample.trace, sample.cpp_source)),
    )
    for sample in manifest.samples:
        _lint_sample_contents(Path(root), sample)
    counts = Counter(sample.kind.value for sample in manifest.samples)
    expected_counts = {
        "gold": 30,
        "controlled_wrong": 60,
        "paradox": 15,
        "natural": 60,
    }
    return CorpusAuditReport(
        corpus_manifest_hash=manifest.content_hash,
        status=manifest.status,
        materialized_counts={key: counts[key] for key in expected_counts},
        expected_counts=expected_counts,
        credentials_pending=manifest.status is CorpusStatus.PENDING_CREDENTIALS,
    )


def validate_corpus_bundle_links(
    corpus: CorpusManifest,
    bundle_manifest: ProjectBundleManifest,
) -> None:
    """Bind controlled corpus sources/traces to the authored bundle bytes."""

    if corpus.bundle_manifest_hash != bundle_manifest.content_hash:
        raise CorpusDataError("corpus does not match project bundle manifest")
    samples_by_problem: dict[str, list[CorpusSample]] = {}
    for sample in corpus.samples:
        samples_by_problem.setdefault(sample.problem_id, []).append(sample)
    for bundle in bundle_manifest.bundles:
        samples = samples_by_problem.get(bundle.problem_id, [])
        gold = [sample for sample in samples if sample.kind is CorpusSampleKind.GOLD]
        if len(gold) != 1 or gold[0].cpp_source.sha256 != bundle.reference_cpp.sha256:
            raise CorpusDataError(
                f"gold source does not match authored reference: {bundle.problem_id}"
            )
        if gold[0].trace.sha256 != bundle.gold_trace.sha256:
            raise CorpusDataError(f"gold trace does not match authored bundle: {bundle.problem_id}")
        wrong_hashes = {
            sample.cpp_source.sha256
            for sample in samples
            if sample.kind is CorpusSampleKind.CONTROLLED_WRONG
        }
        if wrong_hashes != {mutant.sha256 for mutant in bundle.mutants}:
            raise CorpusDataError(
                f"controlled wrong sources do not match authored mutants: {bundle.problem_id}"
            )
        if any(
            sample.cpp_source.sha256 != bundle.reference_cpp.sha256
            for sample in samples
            if sample.kind is CorpusSampleKind.PARADOX
        ):
            raise CorpusDataError(
                f"paradox source does not match authored reference: {bundle.problem_id}"
            )


def _validate_sample_distribution(
    samples: tuple[CorpusSample, ...],
    selection: FrozenSelectionManifest,
    *,
    status: CorpusStatus,
) -> None:
    selected_ids = {entry.problem_id for entry in selection.entries}
    if any(sample.problem_id not in selected_ids for sample in samples):
        raise CorpusDataError("corpus contains a problem outside frozen selection")
    by_problem_kind = Counter((sample.problem_id, sample.kind) for sample in samples)
    for problem_id in selected_ids:
        if by_problem_kind[(problem_id, CorpusSampleKind.GOLD)] != 1:
            raise CorpusDataError("corpus requires one gold sample per problem")
        if by_problem_kind[(problem_id, CorpusSampleKind.CONTROLLED_WRONG)] != 2:
            raise CorpusDataError("corpus requires two controlled wrong samples per problem")
        expected_natural = 2 if status is CorpusStatus.COMPLETE else 0
        if by_problem_kind[(problem_id, CorpusSampleKind.NATURAL)] != expected_natural:
            raise CorpusDataError(
                "complete corpus requires two natural outputs per problem; pending requires zero"
            )
    paradox_problem_ids = {
        sample.problem_id for sample in samples if sample.kind is CorpusSampleKind.PARADOX
    }
    if len(paradox_problem_ids) != 15 or any(
        by_problem_kind[(problem_id, CorpusSampleKind.PARADOX)] != 1
        for problem_id in paradox_problem_ids
    ):
        raise CorpusDataError("corpus requires fifteen paradox samples on distinct problems")


def _verify_artifacts(root: Path | str, artifacts: Iterable[ArtifactRef]) -> None:
    root_path = Path(root)
    if root_path.is_symlink() or not root_path.is_dir():
        raise CorpusDataError("artifact root must be a regular non-symlink directory")
    materialized = tuple(artifacts)
    paths = [artifact.path for artifact in materialized]
    if len(paths) != len(set(paths)):
        raise CorpusDataError("artifact paths must be unique across the manifest")
    for artifact in materialized:
        candidate = root_path
        for part in PurePosixPath(artifact.path).parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise CorpusDataError(f"artifact symlink is forbidden: {artifact.path}")
        if not candidate.is_file():
            raise CorpusDataError(f"artifact file is missing: {artifact.path}")
        size = candidate.stat().st_size
        if size != artifact.byte_length:
            raise CorpusDataError(f"artifact byte length mismatch: {artifact.path}")
        if _sha256_file(candidate) != artifact.sha256:
            raise CorpusDataError(f"artifact SHA-256 mismatch: {artifact.path}")


def _lint_bundle_contents(root: Path, bundle: AuthoredBundleEntry) -> None:
    reference_cpp = _read_utf8_artifact(root, bundle.reference_cpp, "reference C++")
    if not reference_cpp.strip():
        raise CorpusDataError(f"reference C++ is empty: {bundle.problem_id}")
    oracle = _read_contract_artifact(
        root,
        bundle.oracle,
        ProblemOracle,
        "oracle",
    )
    gold_trace = _read_contract_artifact(
        root,
        bundle.gold_trace,
        SolutionTrace,
        "gold trace",
    )
    if oracle.problem_id != bundle.problem_id or gold_trace.problem_id != bundle.problem_id:
        raise CorpusDataError(f"bundle JSON problem ID mismatch: {bundle.problem_id}")
    if oracle.reference_solution_hash != sha256_json(reference_cpp):
        raise CorpusDataError(f"oracle reference hash mismatch: {bundle.problem_id}")
    if gold_trace.code != reference_cpp:
        raise CorpusDataError(f"gold trace code differs from reference: {bundle.problem_id}")
    if any(
        step.status in {StepStatus.INCORRECT, StepStatus.UNSUPPORTED} for step in gold_trace.steps
    ):
        raise CorpusDataError(f"gold trace contains an erroneous step: {bundle.problem_id}")
    for mutant in bundle.mutants:
        if not _read_utf8_artifact(root, mutant, "mutant C++").strip():
            raise CorpusDataError(f"mutant C++ is empty: {bundle.problem_id}")


def _lint_sample_contents(root: Path, sample: CorpusSample) -> None:
    cpp_source = _read_utf8_artifact(root, sample.cpp_source, "sample C++")
    trace = _read_contract_artifact(
        root,
        sample.trace,
        SolutionTrace,
        "sample trace",
    )
    if trace.trace_id != sample.sample_id or trace.problem_id != sample.problem_id:
        raise CorpusDataError(f"sample trace identity mismatch: {sample.sample_id}")
    if trace.code != cpp_source:
        raise CorpusDataError(f"sample trace code mismatch: {sample.sample_id}")
    erroneous = {
        step.step_id
        for step in trace.steps
        if step.status in {StepStatus.INCORRECT, StepStatus.UNSUPPORTED}
    }
    if sample.first_error_step_id is None:
        if erroneous:
            raise CorpusDataError(
                f"sample trace has an unlabeled material error: {sample.sample_id}"
            )
    elif sample.first_error_step_id not in erroneous:
        raise CorpusDataError(
            f"sample first error step is not erroneous in trace: {sample.sample_id}"
        )


def _read_utf8_artifact(root: Path, artifact: ArtifactRef, label: str) -> str:
    try:
        return (root / artifact.path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise CorpusDataError(f"{label} is not valid UTF-8: {artifact.path}") from error


def _read_contract_artifact[ModelT: ProblemOracle | SolutionTrace](
    root: Path,
    artifact: ArtifactRef,
    model: type[ModelT],
    label: str,
) -> ModelT:
    text = _read_utf8_artifact(root, artifact, label)
    try:
        return cast(ModelT, model.model_validate_json(text))
    except ValidationError as error:
        raise CorpusDataError(f"{label} is invalid: {artifact.path}") from error


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise CorpusDataError(f"cannot read artifact: {path}") from error
    return digest.hexdigest()


def _parse_model[ModelT: ProjectBundleManifest | CorpusManifest](
    model: type[ModelT],
    payload: Mapping[str, Any],
    label: str,
) -> ModelT:
    try:
        return cast(
            ModelT,
            model.model_validate_json(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            ),
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise CorpusDataError(f"{label} is invalid") from error
