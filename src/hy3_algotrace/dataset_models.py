"""Strict, fail-closed models and row-level tooling for formal dataset inputs.

The official CodeContests bytes remain external.  This module records their
provenance, converts verified rows, and reports eligibility without inventing
or padding candidates.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import weakref
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.catalog import problem_content_hash
from hy3_algotrace.codecontests import _map_codecontests_record
from hy3_algotrace.contracts import ProblemRecord, RatingBand, Topic

DATASET_SCHEMA_VERSION: Final[Literal["1.2"]] = "1.2"
_PROBLEM_ID_PATTERN = re.compile(r"^cf-(?P<contest>[1-9][0-9]*)-(?P<index>[a-z0-9]+)$")
_MAX_CONVERTER_DIAGNOSTICS = 2_000
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW
_LOGICAL_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")

_TOPIC_TAGS: Mapping[Topic, frozenset[str]] = {
    Topic.CONSTRUCTION_SIMULATION: frozenset({"constructive algorithms", "implementation"}),
    Topic.GREEDY: frozenset({"greedy"}),
    Topic.BINARY_SEARCH: frozenset({"binary search"}),
    Topic.DYNAMIC_PROGRAMMING: frozenset({"dp"}),
    Topic.GRAPH: frozenset({"graphs"}),
}


class DatasetDataError(ValueError):
    """Raised when external dataset material cannot be trusted or converted."""


class DatasetModel(BaseModel):
    """Strict base for Task 7 artifacts without changing shared contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


@dataclass(frozen=True, slots=True)
class TrustedFileSnapshot:
    """Bytes and observations obtained from one already-open regular file."""

    logical_id: str
    contents: bytes
    byte_length: int
    sha256: str


class DatasetFormat(StrEnum):
    JSON = "json"
    JSONL = "jsonl"
    PARQUET = "parquet"
    RIEGELI = "riegeli"


class CheckerKind(StrEnum):
    UNREVIEWED = "unreviewed"
    STANDARD = "standard"
    INTERACTIVE = "interactive"
    SPECIAL_JUDGE = "special_judge"
    MULTIPLE_ANSWER = "multiple_answer"
    TOLERANCE = "tolerance"


class QuotaStatus(StrEnum):
    FULFILLED = "fulfilled"
    UNFULFILLED = "unfulfilled_quota"


class ConversionTool(DatasetModel):
    """Pinned identity of the tool that produced row-level JSON."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)

    @field_validator("name", "version")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("tool identity must be a trimmed single-line string")
        return value


class AcquisitionAsset(DatasetModel):
    """One externally stored raw split pinned by length and SHA-256."""

    split: Literal["validation", "test"]
    url: str = Field(min_length=1, max_length=2_048)
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: str = Field(min_length=1, max_length=512)
    attribution: str = Field(min_length=1, max_length=1_024)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("raw asset URL must be a pinned HTTPS URL")
        return value

    @field_validator("license", "attribution")
    @classmethod
    def validate_prose(cls, value: str) -> str:
        if value != value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("license and attribution must be trimmed single-line strings")
        return value


class AcquisitionManifest(DatasetModel):
    """Complete provenance envelope for the only allowed formal splits."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_raw_acquisition"] = "codecontests_raw_acquisition"
    dataset: Literal["google-deepmind/code_contests"]
    assets: tuple[AcquisitionAsset, ...] = Field(min_length=2, max_length=2)
    converter: ConversionTool
    third_party_terms_acknowledged: Literal[True]

    @model_validator(mode="after")
    def require_both_splits(self) -> Self:
        if [asset.split for asset in self.assets] != ["validation", "test"]:
            raise ValueError("assets must contain one validation and one test split in order")
        return self

    @property
    def content_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class ValidatedAsset(DatasetModel):
    split: Literal["validation", "test"]
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AcquisitionValidationReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_acquisition_validation"] = "codecontests_acquisition_validation"
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid: Literal[True] = True
    assets: tuple[ValidatedAsset, ...] = Field(min_length=2, max_length=2)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if [asset.split for asset in self.assets] != ["validation", "test"]:
            raise ValueError("validated assets must contain validation and test in order")
        if len({asset.logical_id for asset in self.assets}) != 2:
            raise ValueError("validated asset logical identifiers must be unique")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("acquisition validation content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)


class CandidateReview(DatasetModel):
    """Human annotation for checker semantics and any ambiguous primary topic."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    checker_reviewed: bool
    checker_kind: CheckerKind
    reviewer: str = Field(min_length=1, max_length=256)
    reviewed_at: datetime
    evidence_url: str = Field(min_length=1, max_length=2_048)
    primary_topic: Topic | None = None
    primary_topic_reviewed: bool = False
    notes: str = Field(default="", max_length=2_000)

    @field_validator("reviewer", "notes")
    @classmethod
    def validate_review_text(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("review text must be trimmed and contain no NUL")
        return value

    @model_validator(mode="after")
    def validate_decisions(self) -> Self:
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        if self.checker_reviewed == (self.checker_kind is CheckerKind.UNREVIEWED):
            raise ValueError("checker_reviewed must agree with checker_kind")
        if self.primary_topic_reviewed != (self.primary_topic is not None):
            raise ValueError("primary_topic_reviewed must agree with primary_topic")
        match = _PROBLEM_ID_PATTERN.fullmatch(self.problem_id)
        assert match is not None
        expected_url = (
            "https://codeforces.com/problemset/problem/"
            f"{match.group('contest')}/{match.group('index').upper()}"
        )
        if self.evidence_url != expected_url:
            raise ValueError("checker evidence URL must match the Codeforces problem ID")
        return self

    @property
    def content_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class CandidateReviewArtifact(DatasetModel):
    """Canonical human review bound to the exact raw CodeContests row."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_checker_review"] = "codecontests_checker_review"
    raw_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review: CandidateReview
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("raw_row_hash", "content_hash")
    @classmethod
    def reject_zero_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("review artifact hashes cannot be all-zero")
        return value

    @model_validator(mode="after")
    def validate_artifact(self) -> Self:
        if self.content_hash != self.expected_content_hash():
            raise ValueError("review artifact content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)

    @classmethod
    def create(
        cls,
        *,
        raw_row_hash: str,
        review: CandidateReview,
    ) -> CandidateReviewArtifact:
        payload = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "kind": "codecontests_checker_review",
            "raw_row_hash": raw_row_hash,
            "review": review.model_dump(mode="json"),
        }
        return cls(
            raw_row_hash=raw_row_hash,
            review=review,
            content_hash=sha256_json(payload),
        )


class CandidateReviewSet(DatasetModel):
    """Canonical review artifact file for one source split."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_checker_review_set"] = "codecontests_checker_review_set"
    split: Literal["validation", "test"]
    artifacts: tuple[CandidateReviewArtifact, ...]
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_set(self) -> Self:
        problem_ids = [artifact.review.problem_id for artifact in self.artifacts]
        if len(problem_ids) != len(set(problem_ids)):
            raise ValueError("review artifact problem IDs must be unique")
        if problem_ids != sorted(problem_ids):
            raise ValueError("review artifacts must use canonical problem-ID order")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("review set content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)

    @classmethod
    def create(
        cls,
        *,
        split: Literal["validation", "test"],
        artifacts: Iterable[CandidateReviewArtifact],
    ) -> CandidateReviewSet:
        materialized = tuple(sorted(artifacts, key=lambda artifact: artifact.review.problem_id))
        payload = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "kind": "codecontests_checker_review_set",
            "split": split,
            "artifacts": [artifact.model_dump(mode="json") for artifact in materialized],
        }
        return cls(
            split=split,
            artifacts=materialized,
            content_hash=sha256_json(payload),
        )


class ReviewArtifactAsset(DatasetModel):
    """Trusted root observation for one separately reviewed split artifact."""

    split: Literal["validation", "test"]
    logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("sha256")
    @classmethod
    def reject_zero_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("review artifact SHA-256 cannot be all-zero")
        return value


class ReviewArtifactManifest(DatasetModel):
    """Caller-approved byte roots for validation/test human review files."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_checker_review_manifest"] = "codecontests_checker_review_manifest"
    assets: tuple[ReviewArtifactAsset, ...] = Field(min_length=2, max_length=2)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if [asset.split for asset in self.assets] != ["validation", "test"]:
            raise ValueError("review assets must contain validation and test in order")
        if len({asset.logical_id for asset in self.assets}) != 2:
            raise ValueError("review asset logical identifiers must be unique")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("review artifact manifest content_hash does not match")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)

    @classmethod
    def create(cls, assets: Iterable[ReviewArtifactAsset]) -> ReviewArtifactManifest:
        materialized = tuple(assets)
        payload = {
            "schema_version": DATASET_SCHEMA_VERSION,
            "kind": "codecontests_checker_review_manifest",
            "assets": [asset.model_dump(mode="json") for asset in materialized],
        }
        return cls(assets=materialized, content_hash=sha256_json(payload))


class CandidateAssessment(DatasetModel):
    row_number: int = Field(gt=0)
    problem_id: str | None = Field(default=None, min_length=1)
    raw_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record: ProblemRecord | None = None
    review: CandidateReview | None = None
    review_artifact_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    eligible: bool
    reasons: tuple[str, ...] = ()
    reason_detail: str = Field(default="", max_length=2_000)

    @field_validator("raw_row_hash", "review_artifact_hash")
    @classmethod
    def reject_zero_raw_row_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("raw row hash cannot be all-zero")
        return value

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.eligible:
            if self.record is None or self.review is None or self.reasons:
                raise ValueError("eligible assessment requires record/review and no reasons")
        elif not self.reasons:
            raise ValueError("rejected assessment requires at least one reason")
        if self.record is not None and self.problem_id != self.record.problem_id:
            raise ValueError("assessment problem ID does not match record")
        if self.review_artifact_hash is not None:
            if self.review is None:
                raise ValueError("review artifact hash requires a review")
            expected = CandidateReviewArtifact.create(
                raw_row_hash=self.raw_row_hash,
                review=self.review,
            ).content_hash
            if self.review_artifact_hash != expected:
                raise ValueError("assessment review artifact hash does not match")
        return self


class CandidateConversionReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_candidate_conversion"] = "codecontests_candidate_conversion"
    split: Literal["validation", "test"]
    data_format: DatasetFormat
    source_logical_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$")
    source_byte_length: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    converter: ConversionTool
    assessments: tuple[CandidateAssessment, ...]

    @property
    def eligible(self) -> tuple[CandidateAssessment, ...]:
        return tuple(item for item in self.assessments if item.eligible)

    @property
    def rejected(self) -> tuple[CandidateAssessment, ...]:
        return tuple(item for item in self.assessments if not item.eligible)

    @property
    def content_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class QuotaCell(DatasetModel):
    topic: Topic
    rating_band: RatingBand
    required: Literal[2] = 2
    eligible_problem_ids: tuple[str, ...]
    eligible_count: int = Field(ge=0)
    fulfilled: bool

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        if self.eligible_count != len(self.eligible_problem_ids):
            raise ValueError("quota cell count must match problem IDs")
        if self.fulfilled != (self.eligible_count >= self.required):
            raise ValueError("quota cell fulfilled flag must match count")
        if tuple(sorted(self.eligible_problem_ids)) != self.eligible_problem_ids:
            raise ValueError("quota cell problem IDs must be sorted")
        return self


class EligibilityQuotaReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_eligibility_quota"] = "codecontests_eligibility_quota"
    source_conversion_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: QuotaStatus
    cells: tuple[QuotaCell, ...] = Field(min_length=15, max_length=15)
    eligible_total: int = Field(ge=0)
    rejected_total: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        expected_cells = [(topic, band) for topic in Topic for band in RatingBand]
        actual_cells = [(cell.topic, cell.rating_band) for cell in self.cells]
        if actual_cells != expected_cells:
            raise ValueError("quota report must contain every topic/rating cell in order")
        expected_status = (
            QuotaStatus.FULFILLED
            if all(cell.fulfilled for cell in self.cells)
            else QuotaStatus.UNFULFILLED
        )
        if self.status is not expected_status:
            raise ValueError("quota report status must match cell counts")
        if self.eligible_total != sum(cell.eligible_count for cell in self.cells):
            raise ValueError("eligible_total must match quota cells")
        return self

    @property
    def content_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class FrozenSelectionEntry(DatasetModel):
    """Hash-linked identity of one reviewed row in the frozen 30."""

    problem_id: str = Field(pattern=r"^cf-[1-9][0-9]*-[a-z0-9]+$")
    source_split: Literal["validation", "test"]
    topic: Topic
    rating_band: RatingBand
    rating: int = Field(ge=1200, le=2400)
    raw_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("raw_row_hash", "review_hash")
    @classmethod
    def reject_zero_evidence_hash(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("selection evidence hashes cannot be all-zero")
        return value

    @model_validator(mode="after")
    def validate_rating_band(self) -> Self:
        expected = (
            RatingBand.FOUNDATION
            if 1200 <= self.rating <= 1500
            else RatingBand.INTERMEDIATE
            if 1600 <= self.rating <= 1900
            else RatingBand.ADVANCED
        )
        if self.rating_band is not expected:
            raise ValueError("selection entry rating band does not match rating")
        return self


class FrozenSelectionManifest(DatasetModel):
    """Exact immutable 5×3×2 selection; never synthesized from sparse cells."""

    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["formal_codecontests_selection_v2"] = "formal_codecontests_selection_v2"
    acquisition_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_validation_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    quota_report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entries: tuple[FrozenSelectionEntry, ...] = Field(min_length=30, max_length=30)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_freeze(self) -> Self:
        if len({entry.problem_id for entry in self.entries}) != 30:
            raise ValueError("selection entries must contain 30 unique problem IDs")
        cell_counts = {
            (topic, band): sum(
                entry.topic is topic and entry.rating_band is band for entry in self.entries
            )
            for topic in Topic
            for band in RatingBand
        }
        if any(count != 2 for count in cell_counts.values()):
            raise ValueError("selection must contain two entries in every topic/rating cell")
        expected_order = sorted(
            self.entries,
            key=lambda entry: (
                list(Topic).index(entry.topic),
                list(RatingBand).index(entry.rating_band),
                entry.problem_id,
            ),
        )
        if list(self.entries) != expected_order:
            raise ValueError("selection entries must use canonical topic/rating/ID order")
        if self.content_hash != self.expected_content_hash():
            raise ValueError("selection content_hash does not match canonical content")
        return self

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)


_VERIFIED_SELECTION_TOKEN = object()
_VERIFIED_SELECTION_CAPABILITIES: weakref.WeakSet[Any] = weakref.WeakSet()


class VerifiedSelectionChain:
    """Ephemeral capability issued only after replaying the complete source chain."""

    __slots__ = ("selection", "__weakref__")
    selection: FrozenSelectionManifest

    def __init__(
        self,
        *,
        selection: FrozenSelectionManifest,
        _verification_token: object,
    ) -> None:
        if _verification_token is not _VERIFIED_SELECTION_TOKEN:
            raise ValueError("verified selection requires complete chain replay")
        object.__setattr__(self, "selection", selection)
        _VERIFIED_SELECTION_CAPABILITIES.add(self)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("verified selection capabilities are immutable")

    def _is_verified(self) -> bool:
        return self in _VERIFIED_SELECTION_CAPABILITIES


def validate_acquired_assets(
    manifest: AcquisitionManifest,
    asset_paths: Mapping[str, Path | str],
    *,
    logical_ids: Mapping[str, str] | None = None,
) -> AcquisitionValidationReport:
    """Verify external bytes against the frozen acquisition manifest."""

    if set(asset_paths) != {"validation", "test"}:
        raise DatasetDataError("asset paths must contain exactly validation and test")
    identifiers = logical_ids or {"validation": "validation", "test": "test"}
    if set(identifiers) != {"validation", "test"}:
        raise DatasetDataError("logical IDs must contain exactly validation and test")
    validated: list[ValidatedAsset] = []
    by_split = {asset.split: asset for asset in manifest.assets}
    for split in ("validation", "test"):
        expected = by_split[split]
        try:
            observed = read_trusted_file(
                asset_paths[split],
                logical_id=identifiers[split],
                max_bytes=expected.byte_length,
            )
        except DatasetDataError as error:
            if "byte limit" in str(error):
                raise DatasetDataError(f"{split} asset byte length mismatch") from error
            raise
        if observed.byte_length != expected.byte_length:
            raise DatasetDataError(
                f"{split} asset byte length mismatch: expected {expected.byte_length}, "
                f"found {observed.byte_length}"
            )
        if observed.sha256 != expected.sha256:
            raise DatasetDataError(f"{split} asset SHA-256 mismatch")
        validated.append(
            ValidatedAsset(
                split=split,
                logical_id=observed.logical_id,
                byte_length=observed.byte_length,
                sha256=observed.sha256,
            )
        )
    payload: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "codecontests_acquisition_validation",
        "manifest_hash": manifest.content_hash,
        "valid": True,
        "assets": [asset.model_dump(mode="json") for asset in validated],
    }
    return AcquisitionValidationReport(
        manifest_hash=manifest.content_hash,
        assets=tuple(validated),
        content_hash=sha256_json(payload),
    )


def convert_codecontests_file(
    path: Path | str,
    *,
    split: Literal["validation", "test"],
    data_format: DatasetFormat,
    reviews: Iterable[CandidateReview | CandidateReviewArtifact],
    converter: ConversionTool,
    acquisition_validation: AcquisitionValidationReport,
    converter_argv: Sequence[str] | None = None,
) -> CandidateConversionReport:
    """Convert one verified source file and retain a reason for every rejected row."""

    try:
        trusted_validation = AcquisitionValidationReport.model_validate_json(
            acquisition_validation.model_dump_json()
        )
    except ValidationError as error:
        raise DatasetDataError("acquisition validation report is invalid") from error
    observed_asset = next(
        (asset for asset in trusted_validation.assets if asset.split == split), None
    )
    if observed_asset is None:
        raise DatasetDataError("acquisition validation report is missing the split")
    source = read_trusted_file(
        path,
        logical_id=observed_asset.logical_id,
        max_bytes=observed_asset.byte_length,
    )
    if source.byte_length != observed_asset.byte_length or source.sha256 != observed_asset.sha256:
        raise DatasetDataError("raw source does not match acquisition validation report")
    review_by_id: dict[str, CandidateReview] = {}
    review_artifact_by_id: dict[str, CandidateReviewArtifact] = {}
    for supplied_review in reviews:
        if isinstance(supplied_review, CandidateReviewArtifact):
            artifact: CandidateReviewArtifact | None = supplied_review
            review = supplied_review.review
        else:
            artifact = None
            review = supplied_review
        if review.problem_id in review_by_id:
            raise DatasetDataError(f"duplicate checker review: {review.problem_id}")
        review_by_id[review.problem_id] = review
        if artifact is not None:
            review_artifact_by_id[review.problem_id] = artifact
    rows = _load_rows(
        source.contents,
        source_label=source.logical_id,
        data_format=data_format,
        converter_argv=converter_argv,
    )
    assessments: list[CandidateAssessment] = []
    seen_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            assessments.append(
                CandidateAssessment(
                    row_number=row_number,
                    raw_row_hash=sha256_json(row),
                    eligible=False,
                    reasons=("row_not_object",),
                )
            )
            continue
        assessment = _assess_row(
            row,
            row_number=row_number,
            split=split,
            reviews=review_by_id,
            seen_ids=seen_ids,
        )
        artifact = (
            review_artifact_by_id.get(assessment.problem_id)
            if assessment.problem_id is not None
            else None
        )
        if artifact is not None:
            if artifact.raw_row_hash != assessment.raw_row_hash:
                raise DatasetDataError(
                    f"review artifact raw row hash mismatch: {artifact.review.problem_id}"
                )
            assessment = assessment.model_copy(
                update={"review_artifact_hash": artifact.content_hash}
            )
        assessments.append(assessment)
        if assessment.problem_id is not None:
            seen_ids.add(assessment.problem_id)
    missing_review_rows = sorted(set(review_artifact_by_id).difference(seen_ids))
    if missing_review_rows:
        raise DatasetDataError(f"review artifacts do not match raw rows: {missing_review_rows}")
    return CandidateConversionReport(
        split=split,
        data_format=data_format,
        source_logical_id=source.logical_id,
        source_byte_length=source.byte_length,
        source_sha256=source.sha256,
        acquisition_validation_hash=trusted_validation.content_hash,
        converter=converter,
        assessments=tuple(assessments),
    )


def build_quota_report(
    conversion: CandidateConversionReport | Iterable[CandidateConversionReport],
) -> EligibilityQuotaReport:
    """Count all fifteen formal cells without selecting or padding records."""

    buckets: dict[tuple[Topic, RatingBand], list[str]] = {
        (topic, band): [] for topic in Topic for band in RatingBand
    }
    conversions = _materialize_conversions(conversion)
    known_ids: set[str] = set()
    for item in conversions:
        for assessment in item.eligible:
            assert assessment.record is not None
            if assessment.record.problem_id in known_ids:
                raise DatasetDataError(
                    f"duplicate eligible problem across conversions: {assessment.record.problem_id}"
                )
            known_ids.add(assessment.record.problem_id)
            buckets[(assessment.record.topic, assessment.record.rating_band)].append(
                assessment.record.problem_id
            )
    cells = tuple(
        QuotaCell(
            topic=topic,
            rating_band=band,
            eligible_problem_ids=tuple(sorted(buckets[(topic, band)])),
            eligible_count=len(buckets[(topic, band)]),
            fulfilled=len(buckets[(topic, band)]) >= 2,
        )
        for topic in Topic
        for band in RatingBand
    )
    status = (
        QuotaStatus.FULFILLED if all(cell.fulfilled for cell in cells) else QuotaStatus.UNFULFILLED
    )
    return EligibilityQuotaReport(
        source_conversion_hash=_conversion_set_hash(conversions),
        status=status,
        cells=cells,
        eligible_total=sum(cell.eligible_count for cell in cells),
        rejected_total=sum(len(item.rejected) for item in conversions),
    )


def freeze_selection(
    selected_problem_ids: Iterable[str],
    *,
    conversions: Iterable[CandidateConversionReport],
    quota: EligibilityQuotaReport,
    acquisition: AcquisitionManifest,
    acquisition_validation: AcquisitionValidationReport,
) -> FrozenSelectionManifest:
    """Freeze an explicit curator choice after, and only after, quota proof."""

    materialized = tuple(conversions)
    _validate_conversion_acquisition(
        materialized,
        acquisition,
        acquisition_validation,
    )
    if quota.status is not QuotaStatus.FULFILLED:
        raise DatasetDataError("cannot freeze selection while status is unfulfilled_quota")
    if quota.source_conversion_hash != _conversion_set_hash(materialized):
        raise DatasetDataError("quota report does not match candidate conversions")
    selected_ids = tuple(selected_problem_ids)
    if len(selected_ids) != 30 or len(set(selected_ids)) != 30:
        raise DatasetDataError("formal selection requires exactly 30 unique problem IDs")
    candidates = _eligible_candidates(materialized)
    unknown = sorted(set(selected_ids).difference(candidates))
    if unknown:
        raise DatasetDataError(f"selection contains ineligible or unknown candidates: {unknown}")
    selected = [candidates[problem_id] for problem_id in selected_ids]
    cell_counts: dict[tuple[Topic, RatingBand], int] = {
        (topic, band): 0 for topic in Topic for band in RatingBand
    }
    for assessment in selected:
        assert assessment.record is not None
        cell_counts[(assessment.record.topic, assessment.record.rating_band)] += 1
    if any(count != 2 for count in cell_counts.values()):
        raise DatasetDataError("selection must contain exactly two problems in every quota cell")
    selected.sort(
        key=lambda assessment: (
            list(Topic).index(_assessment_record(assessment).topic),
            list(RatingBand).index(_assessment_record(assessment).rating_band),
            _assessment_record(assessment).problem_id,
        )
    )
    entries = tuple(_selection_entry(assessment) for assessment in selected)
    payload: dict[str, Any] = {
        "schema_version": DATASET_SCHEMA_VERSION,
        "kind": "formal_codecontests_selection_v2",
        "acquisition_manifest_hash": acquisition.content_hash,
        "acquisition_validation_hash": acquisition_validation.content_hash,
        "quota_report_hash": quota.content_hash,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    return FrozenSelectionManifest(
        acquisition_manifest_hash=acquisition.content_hash,
        acquisition_validation_hash=acquisition_validation.content_hash,
        quota_report_hash=quota.content_hash,
        entries=entries,
        content_hash=sha256_json(payload),
    )


def validate_frozen_selection(
    payload: Mapping[str, Any],
    *,
    conversions: Iterable[CandidateConversionReport],
    quota: EligibilityQuotaReport,
    acquisition: AcquisitionManifest,
    acquisition_validation: AcquisitionValidationReport,
) -> FrozenSelectionManifest:
    """Validate a disk manifest against current pinned rows and reviews."""

    try:
        manifest = FrozenSelectionManifest.model_validate_json(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        )
    except (TypeError, ValueError, ValidationError) as error:
        raise DatasetDataError("frozen selection manifest is invalid") from error
    if manifest.acquisition_manifest_hash != acquisition.content_hash:
        raise DatasetDataError("selection acquisition manifest hash does not match")
    if manifest.acquisition_validation_hash != acquisition_validation.content_hash:
        raise DatasetDataError("selection acquisition validation hash does not match")
    expected = freeze_selection(
        (entry.problem_id for entry in manifest.entries),
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    if manifest.entries != expected.entries:
        raise DatasetDataError("selection candidate hashes do not match reviewed rows")
    if manifest.quota_report_hash != expected.quota_report_hash:
        raise DatasetDataError("selection quota report hash does not match")
    if manifest.content_hash != expected.content_hash:
        raise DatasetDataError("selection content hash does not match current inputs")
    return manifest


def verify_frozen_selection_chain(
    payload: Mapping[str, Any],
    *,
    raw_asset_paths: Mapping[str, Path | str],
    data_formats: Mapping[str, DatasetFormat],
    review_artifact_paths: Mapping[str, Path | str],
    review_manifest: ReviewArtifactManifest,
    acquisition: AcquisitionManifest,
    acquisition_validation: AcquisitionValidationReport,
    converter_argv_by_split: Mapping[str, Sequence[str] | None] | None = None,
) -> VerifiedSelectionChain:
    """Reobserve raw/review bytes and replay every derived selection artifact."""

    expected_splits = {"validation", "test"}
    if (
        set(raw_asset_paths) != expected_splits
        or set(data_formats) != expected_splits
        or set(review_artifact_paths) != expected_splits
    ):
        raise DatasetDataError(
            "verified selection replay requires raw, format, and review inputs for both splits"
        )
    converter_arguments = converter_argv_by_split or {
        "validation": None,
        "test": None,
    }
    if set(converter_arguments) != expected_splits:
        raise DatasetDataError("converter argv replay inputs must contain both splits")
    review_sets = _load_pinned_review_sets(review_artifact_paths, review_manifest)
    conversions: list[CandidateConversionReport] = []
    for split in ("validation", "test"):
        try:
            conversions.append(
                convert_codecontests_file(
                    raw_asset_paths[split],
                    split=split,
                    data_format=data_formats[split],
                    reviews=review_sets[split].artifacts,
                    converter=acquisition.converter,
                    acquisition_validation=acquisition_validation,
                    converter_argv=converter_arguments[split],
                )
            )
        except DatasetDataError as error:
            raise DatasetDataError(f"{split} raw source replay failed") from error
    materialized = tuple(conversions)
    quota = build_quota_report(materialized)
    manifest = validate_frozen_selection(
        payload,
        conversions=materialized,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    return VerifiedSelectionChain(
        selection=manifest,
        _verification_token=_VERIFIED_SELECTION_TOKEN,
    )


def _load_pinned_review_sets(
    paths: Mapping[str, Path | str],
    manifest: ReviewArtifactManifest,
) -> dict[str, CandidateReviewSet]:
    try:
        trusted_manifest = ReviewArtifactManifest.model_validate_json(manifest.model_dump_json())
    except ValidationError as error:
        raise DatasetDataError("review artifact manifest is invalid") from error
    expected_by_split = {asset.split: asset for asset in trusted_manifest.assets}
    result: dict[str, CandidateReviewSet] = {}
    for split in ("validation", "test"):
        expected = expected_by_split[split]
        try:
            observed = read_trusted_file(
                paths[split],
                logical_id=expected.logical_id,
                max_bytes=expected.byte_length,
            )
        except DatasetDataError as error:
            raise DatasetDataError(f"{split} review artifact byte length mismatch") from error
        if observed.byte_length != expected.byte_length:
            raise DatasetDataError(f"{split} review artifact byte length mismatch")
        if observed.sha256 != expected.sha256:
            raise DatasetDataError(f"{split} review artifact SHA-256 mismatch")
        try:
            review_set = CandidateReviewSet.model_validate_json(observed.contents)
        except (TypeError, ValueError, ValidationError) as error:
            raise DatasetDataError(f"{split} review artifact is invalid") from error
        if review_set.split != split:
            raise DatasetDataError(f"{split} review artifact split does not match")
        result[split] = review_set
    return result


def _assess_row(
    raw: Mapping[str, Any],
    *,
    row_number: int,
    split: Literal["validation", "test"],
    reviews: Mapping[str, CandidateReview],
    seen_ids: set[str],
) -> CandidateAssessment:
    raw_hash = sha256_json(raw)
    problem_id = _raw_problem_id(raw)
    review = reviews.get(problem_id) if problem_id is not None else None
    reasons: list[str] = []
    detail = ""
    if problem_id is not None and problem_id in seen_ids:
        reasons.append("duplicate_problem_id")

    tags_value = raw.get("cf_tags", raw.get("tags"))
    tags = (
        tuple(tag for tag in tags_value if isinstance(tag, str))
        if isinstance(tags_value, list)
        else ()
    )
    matched_topics = _matched_topics(tags)
    selected_topic: Topic | None = None
    if not matched_topics:
        reasons.append("target_topic_missing")
    elif len(matched_topics) == 1:
        selected_topic = matched_topics[0]
        if review is not None and review.primary_topic is not None:
            if review.primary_topic is not selected_topic:
                reasons.append("reviewed_primary_topic_not_supported")
    elif (
        review is not None
        and review.primary_topic_reviewed
        and review.primary_topic in matched_topics
    ):
        selected_topic = review.primary_topic
    else:
        reasons.append("ambiguous_primary_topic")

    generated = raw.get("generated_tests")
    if _test_collection_length(generated) == 0:
        reasons.append("generated_tests_missing")
    if (
        raw.get("is_description_translated") is not False
        or raw.get("untranslated_description") != ""
    ):
        reasons.append("translation_metadata_inconsistent")
    if review is None:
        reasons.append("checker_review_missing")
    elif not review.checker_reviewed:
        reasons.append("checker_review_missing")
    elif review.checker_kind is not CheckerKind.STANDARD:
        reasons.append("checker_not_standard")

    record: ProblemRecord | None = None
    if selected_topic is not None:
        try:
            record = _map_with_reviewed_topic(
                raw,
                split=split,
                selected_topic=selected_topic,
                original_tags=tags,
            )
        except (TypeError, ValueError) as error:
            reasons.append(_mapping_reason(error))
            detail = _bounded_text(str(error))
    if reasons:
        return CandidateAssessment(
            row_number=row_number,
            problem_id=problem_id,
            raw_row_hash=raw_hash,
            record=record,
            review=review,
            eligible=False,
            reasons=tuple(dict.fromkeys(reasons)),
            reason_detail=detail,
        )
    assert record is not None
    assert review is not None
    return CandidateAssessment(
        row_number=row_number,
        problem_id=record.problem_id,
        raw_row_hash=raw_hash,
        record=record,
        review=review,
        eligible=True,
    )


def _materialize_conversions(
    conversion: CandidateConversionReport | Iterable[CandidateConversionReport],
) -> tuple[CandidateConversionReport, ...]:
    if isinstance(conversion, CandidateConversionReport):
        return (conversion,)
    materialized = tuple(conversion)
    if not materialized:
        raise DatasetDataError("at least one candidate conversion is required")
    return materialized


def _conversion_set_hash(conversions: tuple[CandidateConversionReport, ...]) -> str:
    hashes = [item.content_hash for item in conversions]
    return hashes[0] if len(hashes) == 1 else sha256_json(hashes)


def _validate_conversion_acquisition(
    conversions: tuple[CandidateConversionReport, ...],
    acquisition: AcquisitionManifest,
    acquisition_validation: AcquisitionValidationReport,
) -> None:
    try:
        trusted_validation = AcquisitionValidationReport.model_validate_json(
            acquisition_validation.model_dump_json()
        )
    except ValidationError as error:
        raise DatasetDataError("acquisition validation report is invalid") from error
    if trusted_validation.manifest_hash != acquisition.content_hash:
        raise DatasetDataError("acquisition validation report does not match manifest")
    if tuple(conversion.split for conversion in conversions) != ("validation", "test"):
        raise DatasetDataError(
            "formal freeze requires exactly one validation and one test conversion in order"
        )
    if any(conversion.converter != acquisition.converter for conversion in conversions):
        raise DatasetDataError("conversion tool/version does not match acquisition manifest")
    asset_by_split = {asset.split: asset for asset in acquisition.assets}
    validated_by_split = {asset.split: asset for asset in trusted_validation.assets}
    for conversion in conversions:
        asset = asset_by_split[conversion.split]
        validated = validated_by_split[conversion.split]
        if validated.byte_length != asset.byte_length or validated.sha256 != asset.sha256:
            raise DatasetDataError(
                f"{conversion.split} validation report does not match acquisition asset"
            )
        if conversion.acquisition_validation_hash != trusted_validation.content_hash:
            raise DatasetDataError(
                f"{conversion.split} conversion validation linkage does not match"
            )
        if conversion.source_logical_id != validated.logical_id:
            raise DatasetDataError(
                f"{conversion.split} conversion logical ID is not validation-pinned"
            )
        if conversion.source_byte_length != validated.byte_length:
            raise DatasetDataError(
                f"{conversion.split} conversion source byte length is not acquisition-pinned"
            )
        if conversion.source_sha256 != validated.sha256:
            raise DatasetDataError(
                f"{conversion.split} conversion source SHA-256 is not acquisition-pinned"
            )


def _eligible_candidates(
    conversions: Iterable[CandidateConversionReport],
) -> dict[str, CandidateAssessment]:
    candidates: dict[str, CandidateAssessment] = {}
    for conversion in conversions:
        for assessment in conversion.eligible:
            assert assessment.problem_id is not None
            if assessment.problem_id in candidates:
                raise DatasetDataError(
                    f"duplicate eligible problem across conversions: {assessment.problem_id}"
                )
            candidates[assessment.problem_id] = assessment
    return candidates


def _assessment_record(assessment: CandidateAssessment) -> ProblemRecord:
    assert assessment.record is not None
    return assessment.record


def _selection_entry(assessment: CandidateAssessment) -> FrozenSelectionEntry:
    record = _assessment_record(assessment)
    assert assessment.review is not None
    return FrozenSelectionEntry(
        problem_id=record.problem_id,
        source_split=record.source_split,
        topic=record.topic,
        rating_band=record.rating_band,
        rating=record.rating,
        raw_row_hash=assessment.raw_row_hash,
        record_hash=sha256_json(record.model_dump(mode="json")),
        review_hash=assessment.review_artifact_hash or assessment.review.content_hash,
    )


def _map_with_reviewed_topic(
    raw: Mapping[str, Any],
    *,
    split: Literal["validation", "test"],
    selected_topic: Topic,
    original_tags: tuple[str, ...],
) -> ProblemRecord:
    narrowed = dict(raw)
    narrowed["cf_tags"] = [
        tag for tag in original_tags if tag.strip().casefold() in _TOPIC_TAGS[selected_topic]
    ]
    record = _map_codecontests_record(narrowed, split=split)
    provisional = record.model_copy(
        update={
            "cf_tags": original_tags,
            "topic": selected_topic,
            "content_hash": "0" * 64,
        }
    )
    return provisional.model_copy(update={"content_hash": problem_content_hash(provisional)})


def _mapping_reason(error: BaseException) -> str:
    message = str(error).casefold()
    if "translated" in message:
        return "translated_statement"
    if "source must" in message:
        return "non_codeforces_source"
    if "standard stdin/stdout" in message:
        return "nonstandard_io"
    if "private_tests" in message or "hidden tests" in message:
        return "hidden_tests_missing"
    if "time_limit" in message or "memory" in message or "resource" in message:
        return "invalid_resource_limits"
    if "cf_rating" in message or "rating" in message:
        return "rating_outside_frozen_bands"
    return "invalid_record"


def _raw_problem_id(raw: Mapping[str, Any]) -> str | None:
    contest_id = raw.get("cf_contest_id")
    index = raw.get("cf_index")
    if (
        isinstance(contest_id, int)
        and not isinstance(contest_id, bool)
        and contest_id > 0
        and isinstance(index, str)
        and re.fullmatch(r"[A-Za-z0-9]+", index)
    ):
        return f"cf-{contest_id}-{index.casefold()}"
    return None


def _matched_topics(tags: Iterable[str]) -> tuple[Topic, ...]:
    normalized = {tag.strip().casefold() for tag in tags if tag.strip()}
    return tuple(topic for topic in Topic if normalized.intersection(_TOPIC_TAGS[topic]))


def _test_collection_length(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, Mapping):
        inputs = value.get("input")
        outputs = value.get("output")
        if isinstance(inputs, list) and isinstance(outputs, list) and len(inputs) == len(outputs):
            return len(inputs)
    return 0


def _load_rows(
    contents: bytes,
    *,
    source_label: str,
    data_format: DatasetFormat,
    converter_argv: Sequence[str] | None,
) -> list[Any]:
    if data_format is DatasetFormat.JSON:
        return _load_json_rows(contents, source_label)
    if data_format is DatasetFormat.JSONL:
        return _load_jsonl_rows(contents, source_label)
    if data_format is DatasetFormat.PARQUET:
        return _load_parquet_rows(contents, source_label)
    if data_format is DatasetFormat.RIEGELI:
        return _convert_riegeli_rows(contents, converter_argv)
    raise DatasetDataError(f"unsupported dataset format: {data_format}")


def _load_json_rows(contents: bytes, source_label: str) -> list[Any]:
    try:
        payload = json.loads(contents.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DatasetDataError(f"invalid JSON dataset input: {source_label}") from error
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping) and isinstance(payload.get("problems"), list):
        return list(payload["problems"])
    raise DatasetDataError("JSON input must be an array or an object with a problems array")


def _load_jsonl_rows(contents: bytes, source_label: str) -> list[Any]:
    rows: list[Any] = []
    try:
        text = contents.decode("utf-8")
    except UnicodeError as error:
        raise DatasetDataError(f"cannot read JSONL dataset input: {source_label}") from error
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as error:
            raise DatasetDataError(f"invalid JSONL dataset input at line {line_number}") from error
    return rows


def _load_parquet_rows(contents: bytes, source_label: str) -> list[Any]:
    try:
        available = importlib.util.find_spec("pyarrow.parquet") is not None
    except ModuleNotFoundError:
        available = False
    if not available:
        raise DatasetDataError(
            "Parquet conversion requires optional pyarrow; install it in a converter "
            "environment or export verified JSONL first"
        )
    try:
        import pyarrow as arrow  # type: ignore[import-untyped]
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]

        return list(parquet.read_table(arrow.BufferReader(contents)).to_pylist())
    except Exception as error:
        raise DatasetDataError(
            f"unable to decode verified Parquet input: {source_label}"
        ) from error


def _convert_riegeli_rows(contents: bytes, converter_argv: Sequence[str] | None) -> list[Any]:
    if not converter_argv:
        raise DatasetDataError(
            "Riegeli conversion requires an external converter executable and argv "
            "containing {input} and {output}"
        )
    if converter_argv.count("{input}") != 1 or converter_argv.count("{output}") != 1:
        raise DatasetDataError(
            "external converter argv must contain {input} and {output} exactly once"
        )
    executable = converter_argv[0]
    resolved_executable = shutil.which(executable)
    if resolved_executable is None or not os.access(resolved_executable, os.X_OK):
        raise DatasetDataError(f"external converter executable is unavailable: {executable}")
    with tempfile.TemporaryDirectory(prefix="hy3-codecontests-") as directory:
        try:
            directory_fd = os.open(directory, _DIRECTORY_OPEN_FLAGS)
        except OSError as error:
            raise DatasetDataError("cannot open converter temporary directory") from error
        try:
            source_name = "source.riegeli"
            output_name = "converted.jsonl"
            try:
                source_fd = os.open(
                    source_name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=directory_fd,
                )
            except OSError as error:
                raise DatasetDataError("cannot create converter source file") from error
            try:
                remaining = memoryview(contents)
                while remaining:
                    written = os.write(source_fd, remaining)
                    if written <= 0:
                        raise DatasetDataError("cannot write converter source file")
                    remaining = remaining[written:]
            finally:
                os.close(source_fd)
            source = Path(directory) / source_name
            output = Path(directory) / output_name
            argv = [
                str(source) if part == "{input}" else str(output) if part == "{output}" else part
                for part in converter_argv
            ]
            try:
                completed = subprocess.run(
                    argv,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=300,
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise DatasetDataError("external Riegeli converter could not complete") from error
            if completed.returncode != 0:
                raise DatasetDataError("external Riegeli converter failed")
            converted = read_trusted_relative(
                directory_fd,
                output_name,
                logical_id="converted-riegeli-jsonl",
                max_bytes=256 * 1024 * 1024,
            )
            return _load_jsonl_rows(converted.contents, converted.logical_id)
        finally:
            os.close(directory_fd)


def read_trusted_file(
    path: Path | str,
    *,
    logical_id: str,
    max_bytes: int | None = None,
) -> TrustedFileSnapshot:
    """Open a path without following symlinks and consume that one descriptor."""

    candidate = Path(path)
    if candidate.name in {"", ".", ".."}:
        raise DatasetDataError("external file path must name one file")
    with open_trusted_directory(candidate.parent) as directory_fd:
        return read_trusted_relative(
            directory_fd,
            candidate.name,
            logical_id=logical_id,
            max_bytes=max_bytes,
        )


@contextmanager
def open_trusted_directory(path: Path | str) -> Iterator[int]:
    """Open every directory component with O_NOFOLLOW and yield its descriptor."""

    candidate = Path(path)
    parts = candidate.parts
    try:
        directory_fd: int = os.open(
            "/" if candidate.is_absolute() else ".",
            _DIRECTORY_OPEN_FLAGS,
        )
    except OSError as error:
        raise DatasetDataError("cannot open trusted external directory") from error
    try:
        start = 1 if candidate.is_absolute() else 0
        for part in parts[start:]:
            if part in {"", "."}:
                continue
            if part == ".." or "\x00" in part:
                raise DatasetDataError("trusted directory traversal is forbidden")
            try:
                next_fd = os.open(
                    part,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=directory_fd,
                )
            except OSError as error:
                raise DatasetDataError("cannot open trusted external directory") from error
            os.close(directory_fd)
            directory_fd = next_fd
        yield directory_fd
    finally:
        os.close(directory_fd)


def read_trusted_relative(
    directory_fd: int,
    relative_path: str,
    *,
    logical_id: str,
    max_bytes: int | None = None,
) -> TrustedFileSnapshot:
    """Read one safe relative file through openat and the same regular-file fd."""

    if not _LOGICAL_ID_PATTERN.fullmatch(logical_id):
        raise DatasetDataError("external file logical identifier is invalid")
    candidate = Path(relative_path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise DatasetDataError("external file path must be safe and relative")
    current_fd = os.dup(directory_fd)
    try:
        for part in candidate.parts[:-1]:
            try:
                next_fd = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            except OSError as error:
                raise DatasetDataError("external file directory is invalid") from error
            os.close(current_fd)
            current_fd = next_fd
        try:
            file_fd = os.open(candidate.parts[-1], _FILE_OPEN_FLAGS, dir_fd=current_fd)
        except OSError as error:
            raise DatasetDataError("external file must be regular and non-symlink") from error
        try:
            return _read_regular_fd(file_fd, logical_id=logical_id, max_bytes=max_bytes)
        finally:
            os.close(file_fd)
    finally:
        os.close(current_fd)


def _read_regular_fd(
    file_fd: int,
    *,
    logical_id: str,
    max_bytes: int | None,
) -> TrustedFileSnapshot:
    before = os.fstat(file_fd)
    if not stat.S_ISREG(before.st_mode):
        raise DatasetDataError("external file must be a regular file")
    if max_bytes is not None and before.st_size > max_bytes:
        raise DatasetDataError("external file exceeds its trusted byte limit")
    chunks: list[bytes] = []
    digest = hashlib.sha256()
    total = 0
    while chunk := os.read(file_fd, 1024 * 1024):
        total += len(chunk)
        if max_bytes is not None and total > max_bytes:
            raise DatasetDataError("external file exceeds its trusted byte limit")
        chunks.append(chunk)
        digest.update(chunk)
    after = os.fstat(file_fd)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_after != identity_before or total != before.st_size:
        raise DatasetDataError("external file changed while being read")
    return TrustedFileSnapshot(
        logical_id=logical_id,
        contents=b"".join(chunks),
        byte_length=total,
        sha256=digest.hexdigest(),
    )


def _bounded_text(value: str) -> str:
    sanitized = "".join(
        character if character in {"\n", "\t"} or ord(character) >= 32 else "�"
        for character in value
    )
    return sanitized[:_MAX_CONVERTER_DIAGNOSTICS].strip()
