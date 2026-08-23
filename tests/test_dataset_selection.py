from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import Topic
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CheckerKind,
    ConversionTool,
    DatasetDataError,
    DatasetFormat,
    FrozenSelectionManifest,
    QuotaStatus,
    build_quota_report,
    convert_codecontests_file,
    freeze_selection,
    validate_frozen_selection,
)

_TOPIC_TAG = {
    Topic.CONSTRUCTION_SIMULATION: "constructive algorithms",
    Topic.GREEDY: "greedy",
    Topic.BINARY_SEARCH: "binary search",
    Topic.DYNAMIC_PROGRAMMING: "dp",
    Topic.GRAPH: "graphs",
}


def _row(contest_id: int, topic: Topic, rating: int) -> dict[str, object]:
    return {
        "name": f"Problem {contest_id}",
        "description": "Read an integer and print it.",
        "source": 2,
        "cf_contest_id": contest_id,
        "cf_index": "A",
        "cf_rating": rating,
        "cf_tags": [_TOPIC_TAG[topic]],
        "is_description_translated": False,
        "untranslated_description": "",
        "time_limit": {"seconds": "1", "nanos": 0},
        "memory_limit_bytes": 268435456,
        "input_file": "",
        "output_file": "",
        "public_tests": [{"input": "1\n", "output": "1\n"}],
        "private_tests": [{"input": "2\n", "output": "2\n"}],
        "generated_tests": [{"input": "3\n", "output": "3\n"}],
    }


def _review(contest_id: int) -> CandidateReview:
    return CandidateReview(
        problem_id=f"cf-{contest_id}-a",
        checker_reviewed=True,
        checker_kind=CheckerKind.STANDARD,
        reviewer="curator",
        reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
        evidence_url=f"https://codeforces.com/problemset/problem/{contest_id}/A",
    )


def _fulfilled_conversion(tmp_path: Path):  # type: ignore[no-untyped-def]
    rows: list[dict[str, object]] = []
    reviews: list[CandidateReview] = []
    contest_id = 4000
    for topic in Topic:
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                rows.append(_row(contest_id, topic, rating))
                reviews.append(_review(contest_id))
                contest_id += 1
    path = tmp_path / "records.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return convert_codecontests_file(
        path,
        split="validation",
        data_format=DatasetFormat.JSON,
        reviews=reviews,
        converter=ConversionTool(name="test-json", version="1"),
    )


def _empty_conversion(tmp_path: Path, split: str):  # type: ignore[no-untyped-def]
    path = tmp_path / f"empty-{split}.json"
    path.write_text("[]", encoding="utf-8")
    return convert_codecontests_file(
        path,
        split=split,
        data_format=DatasetFormat.JSON,
        reviews=(),
        converter=ConversionTool(name="test-json", version="1"),
    )


def _acquisition(conversions):  # type: ignore[no-untyped-def]
    by_split = {conversion.split: conversion for conversion in conversions}
    return AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=(
            AcquisitionAsset(
                split="validation",
                url="https://example.invalid/code_contests_valid.json",
                byte_length=by_split["validation"].source_byte_length,
                sha256=by_split["validation"].source_sha256,
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
            AcquisitionAsset(
                split="test",
                url="https://example.invalid/code_contests_test.json",
                byte_length=by_split["test"].source_byte_length,
                sha256=by_split["test"].source_sha256,
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
        ),
        converter=ConversionTool(name="test-json", version="1"),
        third_party_terms_acknowledged=True,
    )


def test_freeze_selection_requires_fulfilled_quota_and_locks_all_candidate_hashes(
    tmp_path: Path,
) -> None:
    """Changing a reviewed row after freeze must invalidate the exact 30 manifest."""

    conversion = _fulfilled_conversion(tmp_path)
    conversions = (conversion, _empty_conversion(tmp_path, "test"))
    acquisition = _acquisition(conversions)
    quota = build_quota_report(conversions)
    selected_ids = tuple(item.problem_id for item in conversion.eligible)

    manifest = freeze_selection(
        selected_ids,
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
    )

    assert quota.status is QuotaStatus.FULFILLED
    assert len(manifest.entries) == 30
    assert manifest.content_hash == manifest.expected_content_hash()
    assert (
        validate_frozen_selection(
            manifest.model_dump(mode="json"),
            conversions=conversions,
            quota=quota,
            acquisition=acquisition,
        )
        == manifest
    )

    payload = manifest.model_dump(mode="json")
    payload["entries"][0]["review_hash"] = "b" * 64
    payload["content_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )
    with pytest.raises(DatasetDataError, match="candidate hashes"):
        validate_frozen_selection(
            payload,
            conversions=conversions,
            quota=quota,
            acquisition=acquisition,
        )


def test_freeze_selection_refuses_underfilled_or_duplicate_choice(tmp_path: Path) -> None:
    """Selection cannot compensate for missing cells or duplicate one candidate."""

    conversion = _fulfilled_conversion(tmp_path)
    conversions = (conversion, _empty_conversion(tmp_path, "test"))
    acquisition = _acquisition(conversions)
    quota = build_quota_report(conversions)
    ids = [item.problem_id for item in conversion.eligible]
    ids[-1] = ids[0]
    with pytest.raises(DatasetDataError, match="30 unique"):
        freeze_selection(
            ids,
            conversions=conversions,
            quota=quota,
            acquisition=acquisition,
        )

    sparse_path = tmp_path / "sparse.json"
    sparse_path.write_text(json.dumps([_row(9999, Topic.GREEDY, 1300)]), encoding="utf-8")
    sparse = convert_codecontests_file(
        sparse_path,
        split="test",
        data_format=DatasetFormat.JSON,
        reviews=(_review(9999),),
        converter=ConversionTool(name="test-json", version="1"),
    )
    sparse_conversions = (_empty_conversion(tmp_path, "validation"), sparse)
    with pytest.raises(DatasetDataError, match="unfulfilled_quota"):
        freeze_selection(
            ("cf-9999-a",),
            conversions=sparse_conversions,
            quota=build_quota_report(sparse_conversions),
            acquisition=_acquisition(sparse_conversions),
        )


def test_freeze_selection_rejects_conversion_not_pinned_by_acquisition(tmp_path: Path) -> None:
    """Claiming a manifest hash cannot substitute for matching both raw split digests."""

    conversion = _fulfilled_conversion(tmp_path)
    conversions = (conversion, _empty_conversion(tmp_path, "test"))
    acquisition = _acquisition(conversions)
    payload = acquisition.model_dump(mode="json")
    payload["assets"][0]["sha256"] = "f" * 64
    mismatched = AcquisitionManifest.model_validate_json(json.dumps(payload))
    with pytest.raises(DatasetDataError, match="source SHA-256"):
        freeze_selection(
            tuple(item.problem_id for item in conversion.eligible),
            conversions=conversions,
            quota=build_quota_report(conversions),
            acquisition=mismatched,
        )


def test_frozen_selection_model_itself_rejects_wrong_band_and_cell_counts(tmp_path: Path) -> None:
    """Downstream readers cannot bypass quota rules by parsing a self-hashed manifest directly."""

    conversion = _fulfilled_conversion(tmp_path)
    conversions = (conversion, _empty_conversion(tmp_path, "test"))
    manifest = freeze_selection(
        tuple(item.problem_id for item in conversion.eligible),
        conversions=conversions,
        quota=build_quota_report(conversions),
        acquisition=_acquisition(conversions),
    )
    wrong_band = manifest.model_dump(mode="json")
    wrong_band["entries"][0]["rating_band"] = "1600-1900"
    wrong_band["content_hash"] = sha256_json(
        {key: value for key, value in wrong_band.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="rating band"):
        FrozenSelectionManifest.model_validate_json(json.dumps(wrong_band))

    wrong_cells = manifest.model_dump(mode="json")
    wrong_cells["entries"][0]["topic"] = "greedy"
    wrong_cells["content_hash"] = sha256_json(
        {key: value for key, value in wrong_cells.items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="two entries in every"):
        FrozenSelectionManifest.model_validate_json(json.dumps(wrong_cells))
