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
import subprocess
import tempfile
from collections.abc import Iterable, Mapping, Sequence
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
    path: str = Field(min_length=1)
    byte_length: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AcquisitionValidationReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_acquisition_validation"] = "codecontests_acquisition_validation"
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    valid: Literal[True] = True
    assets: tuple[ValidatedAsset, ...] = Field(min_length=2, max_length=2)


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


class CandidateAssessment(DatasetModel):
    row_number: int = Field(gt=0)
    problem_id: str | None = Field(default=None, min_length=1)
    raw_row_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    record: ProblemRecord | None = None
    review: CandidateReview | None = None
    eligible: bool
    reasons: tuple[str, ...] = ()
    reason_detail: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.eligible:
            if self.record is None or self.review is None or self.reasons:
                raise ValueError("eligible assessment requires record/review and no reasons")
        elif not self.reasons:
            raise ValueError("rejected assessment requires at least one reason")
        if self.record is not None and self.problem_id != self.record.problem_id:
            raise ValueError("assessment problem ID does not match record")
        return self


class CandidateConversionReport(DatasetModel):
    schema_version: Literal["1.2"] = DATASET_SCHEMA_VERSION
    kind: Literal["codecontests_candidate_conversion"] = "codecontests_candidate_conversion"
    split: Literal["validation", "test"]
    data_format: DatasetFormat
    source_byte_length: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
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


def validate_acquired_assets(
    manifest: AcquisitionManifest,
    asset_paths: Mapping[str, Path | str],
) -> AcquisitionValidationReport:
    """Verify external bytes against the frozen acquisition manifest."""

    if set(asset_paths) != {"validation", "test"}:
        raise DatasetDataError("asset paths must contain exactly validation and test")
    validated: list[ValidatedAsset] = []
    by_split = {asset.split: asset for asset in manifest.assets}
    for split in ("validation", "test"):
        path = Path(asset_paths[split])
        if path.is_symlink() or not path.is_file():
            raise DatasetDataError(f"{split} asset must be a regular non-symlink file")
        expected = by_split[split]
        size = path.stat().st_size
        if size != expected.byte_length:
            raise DatasetDataError(
                f"{split} asset byte length mismatch: expected {expected.byte_length}, found {size}"
            )
        digest = _sha256_file(path)
        if digest != expected.sha256:
            raise DatasetDataError(f"{split} asset SHA-256 mismatch")
        validated.append(
            ValidatedAsset(
                split=split,
                path=str(path),
                byte_length=size,
                sha256=digest,
            )
        )
    return AcquisitionValidationReport(
        manifest_hash=manifest.content_hash,
        assets=tuple(validated),
    )


def convert_codecontests_file(
    path: Path | str,
    *,
    split: Literal["validation", "test"],
    data_format: DatasetFormat,
    reviews: Iterable[CandidateReview],
    converter: ConversionTool,
    converter_argv: Sequence[str] | None = None,
) -> CandidateConversionReport:
    """Convert one verified source file and retain a reason for every rejected row."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise DatasetDataError(f"dataset input must be a regular non-symlink file: {source}")
    review_by_id: dict[str, CandidateReview] = {}
    for review in reviews:
        if review.problem_id in review_by_id:
            raise DatasetDataError(f"duplicate checker review: {review.problem_id}")
        review_by_id[review.problem_id] = review
    rows = _load_rows(source, data_format=data_format, converter_argv=converter_argv)
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
        assessments.append(assessment)
        if assessment.problem_id is not None:
            seen_ids.add(assessment.problem_id)
    return CandidateConversionReport(
        split=split,
        data_format=data_format,
        source_byte_length=source.stat().st_size,
        source_sha256=_sha256_file(source),
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
) -> FrozenSelectionManifest:
    """Freeze an explicit curator choice after, and only after, quota proof."""

    materialized = tuple(conversions)
    _validate_conversion_acquisition(materialized, acquisition)
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
        "quota_report_hash": quota.content_hash,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    return FrozenSelectionManifest(
        acquisition_manifest_hash=acquisition.content_hash,
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
    expected = freeze_selection(
        (entry.problem_id for entry in manifest.entries),
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
    )
    if manifest.entries != expected.entries:
        raise DatasetDataError("selection candidate hashes do not match reviewed rows")
    if manifest.quota_report_hash != expected.quota_report_hash:
        raise DatasetDataError("selection quota report hash does not match")
    if manifest.content_hash != expected.content_hash:
        raise DatasetDataError("selection content hash does not match current inputs")
    return manifest


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
) -> None:
    if tuple(conversion.split for conversion in conversions) != ("validation", "test"):
        raise DatasetDataError(
            "formal freeze requires exactly one validation and one test conversion in order"
        )
    if any(conversion.converter != acquisition.converter for conversion in conversions):
        raise DatasetDataError("conversion tool/version does not match acquisition manifest")
    asset_by_split = {asset.split: asset for asset in acquisition.assets}
    for conversion in conversions:
        asset = asset_by_split[conversion.split]
        if conversion.source_byte_length != asset.byte_length:
            raise DatasetDataError(
                f"{conversion.split} conversion source byte length is not acquisition-pinned"
            )
        if conversion.source_sha256 != asset.sha256:
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
        review_hash=assessment.review.content_hash,
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
    source: Path,
    *,
    data_format: DatasetFormat,
    converter_argv: Sequence[str] | None,
) -> list[Any]:
    if data_format is DatasetFormat.JSON:
        return _load_json_rows(source)
    if data_format is DatasetFormat.JSONL:
        return _load_jsonl_rows(source)
    if data_format is DatasetFormat.PARQUET:
        return _load_parquet_rows(source)
    if data_format is DatasetFormat.RIEGELI:
        return _convert_riegeli_rows(source, converter_argv)
    raise DatasetDataError(f"unsupported dataset format: {data_format}")


def _load_json_rows(source: Path) -> list[Any]:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetDataError(f"invalid JSON dataset input: {source}") from error
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping) and isinstance(payload.get("problems"), list):
        return list(payload["problems"])
    raise DatasetDataError("JSON input must be an array or an object with a problems array")


def _load_jsonl_rows(source: Path) -> list[Any]:
    rows: list[Any] = []
    try:
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise DatasetDataError(
                        f"invalid JSONL dataset input at line {line_number}"
                    ) from error
    except (OSError, UnicodeError) as error:
        raise DatasetDataError(f"cannot read JSONL dataset input: {source}") from error
    return rows


def _load_parquet_rows(source: Path) -> list[Any]:
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
        import pyarrow.parquet as parquet  # type: ignore[import-untyped]

        return list(parquet.read_table(source).to_pylist())
    except Exception as error:
        raise DatasetDataError(f"unable to decode verified Parquet input: {source}") from error


def _convert_riegeli_rows(source: Path, converter_argv: Sequence[str] | None) -> list[Any]:
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
        output = Path(directory) / "converted.jsonl"
        argv = [
            str(source) if part == "{input}" else str(output) if part == "{output}" else part
            for part in converter_argv
        ]
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise DatasetDataError("external Riegeli converter could not complete") from error
        if completed.returncode != 0:
            diagnostics = _bounded_text(completed.stderr)
            raise DatasetDataError(
                f"external Riegeli converter failed with exit {completed.returncode}: {diagnostics}"
            )
        if not output.is_file() or output.is_symlink():
            raise DatasetDataError("external Riegeli converter did not create JSONL output")
        return _load_jsonl_rows(output)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise DatasetDataError(f"cannot hash external dataset file: {path}") from error
    return digest.hexdigest()


def _bounded_text(value: str) -> str:
    sanitized = "".join(
        character if character in {"\n", "\t"} or ord(character) >= 32 else "�"
        for character in value
    )
    return sanitized[:_MAX_CONVERTER_DIAGNOSTICS].strip()
