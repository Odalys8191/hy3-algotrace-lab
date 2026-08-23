from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hy3_algotrace.artifacts import canonical_json_bytes, sha256_json
from hy3_algotrace.catalog import problem_content_hash
from hy3_algotrace.contracts import Topic
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CandidateReviewArtifact,
    CandidateReviewSet,
    CheckerKind,
    ConversionTool,
    DatasetDataError,
    DatasetFormat,
    FrozenSelectionManifest,
    QuotaStatus,
    ReviewArtifactAsset,
    ReviewArtifactManifest,
    VerifiedSelectionChain,
    build_quota_report,
    convert_codecontests_file,
    freeze_selection,
    validate_acquired_assets,
    validate_frozen_selection,
    verify_frozen_selection_chain,
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


def _fixture_chain(
    tmp_path: Path,
    *,
    prefix: str = "full",
    validation_rows: list[dict[str, object]] | None = None,
    validation_reviews: list[CandidateReview] | None = None,
    test_rows: list[dict[str, object]] | None = None,
    test_reviews: list[CandidateReview] | None = None,
):  # type: ignore[no-untyped-def]
    converter = ConversionTool(name="test-json", version="1")
    paths = {
        "validation": tmp_path / f"{prefix}-validation.json",
        "test": tmp_path / f"{prefix}-test.json",
    }
    paths["validation"].write_text(json.dumps(validation_rows or []), encoding="utf-8")
    paths["test"].write_text(json.dumps(test_rows or []), encoding="utf-8")
    assets = []
    for split in ("validation", "test"):
        contents = paths[split].read_bytes()
        assets.append(
            AcquisitionAsset(
                split=split,
                url=f"https://example.invalid/code_contests_{split}.json",
                byte_length=len(contents),
                sha256=hashlib.sha256(contents).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            )
        )
    acquisition = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=tuple(assets),
        converter=converter,
        third_party_terms_acknowledged=True,
    )
    validation = validate_acquired_assets(
        acquisition,
        paths,
    )
    conversions = tuple(
        convert_codecontests_file(
            paths[split],
            split=split,
            data_format=DatasetFormat.JSON,
            reviews=(validation_reviews or []) if split == "validation" else (test_reviews or []),
            converter=converter,
            acquisition_validation=validation,
        )
        for split in ("validation", "test")
    )
    return conversions, acquisition, validation


def _fulfilled_chain(tmp_path: Path):  # type: ignore[no-untyped-def]
    rows: list[dict[str, object]] = []
    reviews: list[CandidateReview] = []
    contest_id = 4000
    for topic in Topic:
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                rows.append(_row(contest_id, topic, rating))
                reviews.append(_review(contest_id))
                contest_id += 1
    return _fixture_chain(
        tmp_path,
        validation_rows=rows,
        validation_reviews=reviews,
    )


def _trusted_replay_chain(tmp_path: Path):  # type: ignore[no-untyped-def]
    rows: dict[str, list[dict[str, object]]] = {"validation": [], "test": []}
    reviews: dict[str, list[CandidateReview]] = {"validation": [], "test": []}
    contest_id = 4500
    for topic in Topic:
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                rows["validation"].append(_row(contest_id, topic, rating))
                reviews["validation"].append(_review(contest_id))
                contest_id += 1
    raw_paths = {split: tmp_path / f"replay-{split}.json" for split in ("validation", "test")}
    for split in ("validation", "test"):
        raw_paths[split].write_text(json.dumps(rows[split]), encoding="utf-8")
    converter = ConversionTool(name="trusted-replay-json", version="1")
    acquisition = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=tuple(
            AcquisitionAsset(
                split=split,
                url=f"https://example.invalid/replay-{split}.json",
                byte_length=len(raw_paths[split].read_bytes()),
                sha256=hashlib.sha256(raw_paths[split].read_bytes()).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            )
            for split in ("validation", "test")
        ),
        converter=converter,
        third_party_terms_acknowledged=True,
    )
    acquisition_validation = validate_acquired_assets(
        acquisition,
        raw_paths,
    )
    review_sets: dict[str, CandidateReviewSet] = {}
    review_paths = {split: tmp_path / f"reviews-{split}.json" for split in ("validation", "test")}
    for split in ("validation", "test"):
        artifacts = tuple(
            CandidateReviewArtifact.create(
                raw_row_hash=sha256_json(row),
                review=review,
            )
            for row, review in zip(rows[split], reviews[split], strict=True)
        )
        review_sets[split] = CandidateReviewSet.create(split=split, artifacts=artifacts)
        review_paths[split].write_bytes(
            canonical_json_bytes(review_sets[split].model_dump(mode="json"))
        )
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
    conversions = tuple(
        convert_codecontests_file(
            raw_paths[split],
            split=split,
            data_format=DatasetFormat.JSON,
            reviews=review_sets[split].artifacts,
            converter=converter,
            acquisition_validation=acquisition_validation,
        )
        for split in ("validation", "test")
    )
    quota = build_quota_report(conversions)
    selection = freeze_selection(
        tuple(
            assessment.problem_id
            for conversion in conversions
            for assessment in conversion.eligible
        ),
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    return {
        "raw_paths": raw_paths,
        "review_paths": review_paths,
        "review_manifest": review_manifest,
        "review_sets": review_sets,
        "acquisition": acquisition,
        "acquisition_validation": acquisition_validation,
        "conversions": conversions,
        "quota": quota,
        "selection": selection,
    }


def test_freeze_selection_requires_fulfilled_quota_and_locks_all_candidate_hashes(
    tmp_path: Path,
) -> None:
    """Changing a reviewed row after freeze must invalidate the exact 30 manifest."""

    conversions, acquisition, validation = _fulfilled_chain(tmp_path)
    conversion = conversions[0]
    quota = build_quota_report(conversions)
    selected_ids = tuple(item.problem_id for item in conversion.eligible)

    manifest = freeze_selection(
        selected_ids,
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=validation,
    )

    assert quota.status is QuotaStatus.FULFILLED
    assert len(manifest.entries) == 30
    assert manifest.acquisition_validation_hash == validation.content_hash
    assert manifest.content_hash == manifest.expected_content_hash()
    assert (
        validate_frozen_selection(
            manifest.model_dump(mode="json"),
            conversions=conversions,
            quota=quota,
            acquisition=acquisition,
            acquisition_validation=validation,
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
            acquisition_validation=validation,
        )


def test_freeze_selection_refuses_underfilled_or_duplicate_choice(tmp_path: Path) -> None:
    """Selection cannot compensate for missing cells or duplicate one candidate."""

    conversions, acquisition, validation = _fulfilled_chain(tmp_path)
    conversion = conversions[0]
    quota = build_quota_report(conversions)
    ids = [item.problem_id for item in conversion.eligible]
    ids[-1] = ids[0]
    with pytest.raises(DatasetDataError, match="30 unique"):
        freeze_selection(
            ids,
            conversions=conversions,
            quota=quota,
            acquisition=acquisition,
            acquisition_validation=validation,
        )

    sparse_conversions, sparse_acquisition, sparse_validation = _fixture_chain(
        tmp_path,
        prefix="sparse",
        test_rows=[_row(9999, Topic.GREEDY, 1300)],
        test_reviews=[_review(9999)],
    )
    with pytest.raises(DatasetDataError, match="unfulfilled_quota"):
        freeze_selection(
            ("cf-9999-a",),
            conversions=sparse_conversions,
            quota=build_quota_report(sparse_conversions),
            acquisition=sparse_acquisition,
            acquisition_validation=sparse_validation,
        )


@pytest.mark.parametrize("hash_field", ("raw_row_hash", "review_hash"))
def test_selection_entry_rejects_all_zero_evidence_hashes(
    tmp_path: Path,
    hash_field: str,
) -> None:
    """Sentinel hashes cannot cross a frozen-selection model boundary."""

    conversions, acquisition, validation = _fulfilled_chain(tmp_path)
    quota = build_quota_report(conversions)
    manifest = freeze_selection(
        tuple(item.problem_id for item in conversions[0].eligible),
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=validation,
    )
    payload = manifest.entries[0].model_dump()
    payload[hash_field] = "0" * 64

    with pytest.raises(ValidationError, match="all-zero"):
        type(manifest.entries[0]).model_validate(payload)


def test_verified_selection_replays_raw_rows_and_pinned_human_reviews(
    tmp_path: Path,
) -> None:
    """Self-rehashing every derived row/reviewer/record cannot mint a capability."""

    chain = _trusted_replay_chain(tmp_path)
    forged_conversions = []
    for conversion in chain["conversions"]:
        forged_assessments = []
        for assessment in conversion.assessments:
            if not assessment.eligible:
                forged_assessments.append(assessment)
                continue
            assert assessment.record is not None
            assert assessment.review is not None
            forged_raw_hash = hashlib.sha256(
                f"forged-row:{assessment.problem_id}".encode()
            ).hexdigest()
            forged_provisional = assessment.record.model_copy(
                update={"title": "Forged attacker title", "content_hash": "0" * 64}
            )
            forged_record = forged_provisional.model_copy(
                update={"content_hash": problem_content_hash(forged_provisional)}
            )
            forged_review = assessment.review.model_copy(update={"reviewer": "attacker"})
            forged_artifact = CandidateReviewArtifact.create(
                raw_row_hash=forged_raw_hash,
                review=forged_review,
            )
            forged_assessments.append(
                assessment.model_copy(
                    update={
                        "raw_row_hash": forged_raw_hash,
                        "record": forged_record,
                        "review": forged_review,
                        "review_artifact_hash": forged_artifact.content_hash,
                    }
                )
            )
        forged_conversions.append(
            conversion.model_copy(update={"assessments": tuple(forged_assessments)})
        )
    forged_quota = build_quota_report(tuple(forged_conversions))
    forged_selection = freeze_selection(
        tuple(entry.problem_id for entry in chain["selection"].entries),
        conversions=tuple(forged_conversions),
        quota=forged_quota,
        acquisition=chain["acquisition"],
        acquisition_validation=chain["acquisition_validation"],
    )

    with pytest.raises(DatasetDataError, match="candidate hashes"):
        verify_frozen_selection_chain(
            forged_selection.model_dump(mode="json"),
            raw_asset_paths=chain["raw_paths"],
            data_formats={
                "validation": DatasetFormat.JSON,
                "test": DatasetFormat.JSON,
            },
            review_artifact_paths=chain["review_paths"],
            review_manifest=chain["review_manifest"],
            acquisition=chain["acquisition"],
            acquisition_validation=chain["acquisition_validation"],
        )


@pytest.mark.parametrize("altered_input", ("raw", "review"))
def test_verified_selection_rejects_altered_raw_or_review_file(
    tmp_path: Path,
    altered_input: str,
) -> None:
    """Capability issuance reobserves both pinned byte roots on every replay."""

    chain = _trusted_replay_chain(tmp_path)
    verified_chain = verify_frozen_selection_chain(
        chain["selection"].model_dump(mode="json"),
        raw_asset_paths=chain["raw_paths"],
        data_formats={
            "validation": DatasetFormat.JSON,
            "test": DatasetFormat.JSON,
        },
        review_artifact_paths=chain["review_paths"],
        review_manifest=chain["review_manifest"],
        acquisition=chain["acquisition"],
        acquisition_validation=chain["acquisition_validation"],
    )
    assert verified_chain.selection == chain["selection"]
    with pytest.raises(TypeError):
        VerifiedSelectionChain(selection=chain["selection"])
    with pytest.raises((TypeError, ValueError)):
        replace(verified_chain, selection=chain["selection"])
    if altered_input == "raw":
        target = chain["raw_paths"]["validation"]
        altered_rows = json.loads(target.read_text(encoding="utf-8"))
        altered_rows[0]["name"] = "Altered raw title"
        target.write_text(json.dumps(altered_rows), encoding="utf-8")
    else:
        target = chain["review_paths"]["validation"]
        review_set = chain["review_sets"]["validation"]
        original = review_set.artifacts[0]
        altered_review = original.review.model_copy(update={"reviewer": "attacker"})
        altered_artifact = CandidateReviewArtifact.create(
            raw_row_hash=original.raw_row_hash,
            review=altered_review,
        )
        altered_set = CandidateReviewSet.create(
            split="validation",
            artifacts=(altered_artifact, *review_set.artifacts[1:]),
        )
        target.write_bytes(canonical_json_bytes(altered_set.model_dump(mode="json")))

    with pytest.raises(DatasetDataError, match="byte length|raw source|review artifact"):
        verify_frozen_selection_chain(
            chain["selection"].model_dump(mode="json"),
            raw_asset_paths=chain["raw_paths"],
            data_formats={
                "validation": DatasetFormat.JSON,
                "test": DatasetFormat.JSON,
            },
            review_artifact_paths=chain["review_paths"],
            review_manifest=chain["review_manifest"],
            acquisition=chain["acquisition"],
            acquisition_validation=chain["acquisition_validation"],
        )


def test_freeze_selection_rejects_conversion_not_pinned_by_acquisition(tmp_path: Path) -> None:
    """Claiming a manifest hash cannot substitute for matching both raw split digests."""

    conversions, acquisition, validation = _fulfilled_chain(tmp_path)
    conversion = conversions[0]
    payload = acquisition.model_dump(mode="json")
    payload["assets"][0]["sha256"] = "f" * 64
    mismatched = AcquisitionManifest.model_validate_json(json.dumps(payload))
    with pytest.raises(DatasetDataError, match="validation report"):
        freeze_selection(
            tuple(item.problem_id for item in conversion.eligible),
            conversions=conversions,
            quota=build_quota_report(conversions),
            acquisition=mismatched,
            acquisition_validation=validation,
        )

    forged_conversion = conversion.model_copy(update={"acquisition_validation_hash": "f" * 64})
    with pytest.raises(DatasetDataError, match="validation linkage"):
        freeze_selection(
            tuple(item.problem_id for item in conversion.eligible),
            conversions=(forged_conversion, conversions[1]),
            quota=build_quota_report((forged_conversion, conversions[1])),
            acquisition=acquisition,
            acquisition_validation=validation,
        )


def test_frozen_selection_model_itself_rejects_wrong_band_and_cell_counts(tmp_path: Path) -> None:
    """Downstream readers cannot bypass quota rules by parsing a self-hashed manifest directly."""

    conversions, acquisition, validation = _fulfilled_chain(tmp_path)
    conversion = conversions[0]
    manifest = freeze_selection(
        tuple(item.problem_id for item in conversion.eligible),
        conversions=conversions,
        quota=build_quota_report(conversions),
        acquisition=acquisition,
        acquisition_validation=validation,
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
