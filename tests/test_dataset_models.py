from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

import hy3_algotrace.dataset_models as dataset_models
from hy3_algotrace.contracts import RatingBand, Topic
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CheckerKind,
    ConversionTool,
    DatasetDataError,
    DatasetFormat,
    QuotaStatus,
    build_quota_report,
    convert_codecontests_file,
    validate_acquired_assets,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _asset(split: str, content: bytes) -> AcquisitionAsset:
    return AcquisitionAsset(
        split=split,
        url=f"https://storage.googleapis.com/dm-code_contests/code_contests_{split}.riegeli",
        byte_length=len(content),
        sha256=_sha256(content),
        license="CC-BY-4.0 with separately governed third-party materials",
        attribution="Google DeepMind CodeContests and Codeforces",
    )


def _manifest(valid: bytes, test: bytes) -> AcquisitionManifest:
    return AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=(_asset("validation", valid), _asset("test", test)),
        converter=ConversionTool(name="verified-test-converter", version="1.0.0"),
        third_party_terms_acknowledged=True,
    )


def _raw_problem(
    contest_id: int,
    *,
    tags: list[str] | None = None,
    rating: int = 1400,
    generated_tests: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "name": f"Problem {contest_id}",
        "description": "Read an integer and print it.",
        "source": 2,
        "cf_contest_id": contest_id,
        "cf_index": "A",
        "cf_rating": rating,
        "cf_tags": tags or ["greedy"],
        "is_description_translated": False,
        "untranslated_description": "",
        "time_limit": {"seconds": "1", "nanos": 0},
        "memory_limit_bytes": 268435456,
        "input_file": "",
        "output_file": "",
        "public_tests": [{"input": "1\n", "output": "1\n"}],
        "private_tests": [{"input": "2\n", "output": "2\n"}],
        "generated_tests": generated_tests
        if generated_tests is not None
        else [{"input": "3\n", "output": "3\n"}],
    }


def _review(
    contest_id: int,
    *,
    primary_topic: Topic | None = None,
) -> CandidateReview:
    return CandidateReview(
        problem_id=f"cf-{contest_id}-a",
        checker_reviewed=True,
        checker_kind=CheckerKind.STANDARD,
        reviewer="dataset-curator",
        reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
        evidence_url=f"https://codeforces.com/problemset/problem/{contest_id}/A",
        primary_topic=primary_topic,
        primary_topic_reviewed=primary_topic is not None,
    )


def test_acquisition_manifest_and_external_bytes_fail_closed(tmp_path: Path) -> None:
    """A changed byte or incomplete split set must invalidate acquisition provenance."""

    valid = b"official validation bytes"
    test = b"official test bytes"
    manifest = _manifest(valid, test)
    valid_path = tmp_path / "valid.riegeli"
    test_path = tmp_path / "test.riegeli"
    valid_path.write_bytes(valid)
    test_path.write_bytes(test)

    report = validate_acquired_assets(
        manifest,
        {"validation": valid_path, "test": test_path},
    )

    assert report.valid is True
    assert [(item.split, item.byte_length) for item in report.assets] == [
        ("validation", 25),
        ("test", 19),
    ]
    test_path.write_bytes(test + b"tampered")
    with pytest.raises(DatasetDataError, match="test.*byte length"):
        validate_acquired_assets(
            manifest,
            {"validation": valid_path, "test": test_path},
        )
    with pytest.raises(DatasetDataError, match="exactly validation and test"):
        validate_acquired_assets(manifest, {"validation": valid_path})


def test_acquisition_models_reject_coercion_duplicate_splits_and_unpinned_urls() -> None:
    """Loose integers, duplicate splits, and non-HTTPS URLs must never look pinned."""

    valid = b"valid"
    test = b"test"
    with pytest.raises(ValidationError):
        AcquisitionAsset(
            split="validation",
            url="http://example.test/valid",
            byte_length="5",
            sha256=_sha256(valid),
            license="CC-BY-4.0",
            attribution="CodeContests",
        )
    with pytest.raises(ValidationError, match="one validation and one test"):
        AcquisitionManifest(
            dataset="google-deepmind/code_contests",
            assets=(_asset("validation", valid), _asset("validation", test)),
            converter=ConversionTool(name="converter", version="1"),
            third_party_terms_acknowledged=True,
        )


def test_json_and_jsonl_conversion_report_row_reasons_and_reviewed_override(
    tmp_path: Path,
) -> None:
    """Missing generated tests and ambiguous unreviewed tags must not enter quotas."""

    rows = [
        _raw_problem(1000),
        _raw_problem(1001, generated_tests=[]),
        _raw_problem(1002, tags=["greedy", "dp"]),
        _raw_problem(1003, tags=["greedy", "dp"]),
    ]
    json_path = tmp_path / "rows.json"
    json_path.write_text(json.dumps(rows), encoding="utf-8")
    jsonl_path = tmp_path / "rows.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    reviews = (
        _review(1000),
        _review(1001),
        _review(1002),
        _review(1003, primary_topic=Topic.DYNAMIC_PROGRAMMING),
    )

    from_json = convert_codecontests_file(
        json_path,
        split="validation",
        data_format=DatasetFormat.JSON,
        reviews=reviews,
        converter=ConversionTool(name="json-reader", version="1"),
    )
    from_jsonl = convert_codecontests_file(
        jsonl_path,
        split="validation",
        data_format=DatasetFormat.JSONL,
        reviews=reviews,
        converter=ConversionTool(name="jsonl-reader", version="1"),
    )

    assert [item.problem_id for item in from_json.eligible] == ["cf-1000-a", "cf-1003-a"]
    assert from_json.eligible[1].record.topic is Topic.DYNAMIC_PROGRAMMING
    assert from_json.eligible[1].record.cf_tags == ("greedy", "dp")
    assert [(item.problem_id, item.reasons) for item in from_json.rejected] == [
        ("cf-1001-a", ("generated_tests_missing",)),
        ("cf-1002-a", ("ambiguous_primary_topic",)),
    ]
    assert [item.model_dump(mode="json") for item in from_jsonl.assessments] == [
        item.model_dump(mode="json") for item in from_json.assessments
    ]


def test_unreviewed_or_nonstandard_checker_never_becomes_eligible(tmp_path: Path) -> None:
    """A structurally valid row still needs a positive human checker decision."""

    path = tmp_path / "row.json"
    path.write_text(json.dumps([_raw_problem(2000)]), encoding="utf-8")
    report = convert_codecontests_file(
        path,
        split="test",
        data_format=DatasetFormat.JSON,
        reviews=(),
        converter=ConversionTool(name="json-reader", version="1"),
    )
    assert report.eligible == ()
    assert report.rejected[0].reasons == ("checker_review_missing",)

    special = CandidateReview(
        problem_id="cf-2000-a",
        checker_reviewed=True,
        checker_kind=CheckerKind.SPECIAL_JUDGE,
        reviewer="dataset-curator",
        reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
        evidence_url="https://codeforces.com/problemset/problem/2000/A",
    )
    report = convert_codecontests_file(
        path,
        split="test",
        data_format=DatasetFormat.JSON,
        reviews=(special,),
        converter=ConversionTool(name="json-reader", version="1"),
    )
    assert report.rejected[0].reasons == ("checker_not_standard",)


def test_original_english_requires_consistent_translation_metadata(tmp_path: Path) -> None:
    """A row cannot claim untranslated English while retaining translated source text."""

    row = _raw_problem(2001)
    row["untranslated_description"] = "Texto original no ingles."
    path = tmp_path / "translated-row.json"
    path.write_text(json.dumps([row]), encoding="utf-8")

    report = convert_codecontests_file(
        path,
        split="test",
        data_format=DatasetFormat.JSON,
        reviews=(_review(2001),),
        converter=ConversionTool(name="json-reader", version="1"),
    )

    assert report.eligible == ()
    assert report.rejected[0].reasons == ("translation_metadata_inconsistent",)


def test_optional_parquet_and_riegeli_dependencies_fail_actionably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unavailable optional readers must name the dependency or converter action."""

    parquet = tmp_path / "rows.parquet"
    parquet.write_bytes(b"not parquet")
    monkeypatch.setattr(dataset_models.importlib.util, "find_spec", lambda _name: None)
    with pytest.raises(DatasetDataError, match="pyarrow.*JSONL"):
        convert_codecontests_file(
            parquet,
            split="validation",
            data_format=DatasetFormat.PARQUET,
            reviews=(),
            converter=ConversionTool(name="pyarrow", version="unavailable"),
        )
    riegeli = tmp_path / "rows.riegeli"
    riegeli.write_bytes(b"riegeli")
    with pytest.raises(DatasetDataError, match="external converter.*executable"):
        convert_codecontests_file(
            riegeli,
            split="validation",
            data_format=DatasetFormat.RIEGELI,
            reviews=(),
            converter=ConversionTool(name="riegeli-jsonl", version="1"),
            converter_argv=("/definitely/missing/riegeli-converter", "{input}", "{output}"),
        )


def test_quota_report_has_all_fifteen_cells_and_never_pads(tmp_path: Path) -> None:
    """A sparse eligible pool must yield an explicit 15-cell unfulfilled report."""

    path = tmp_path / "rows.json"
    path.write_text(json.dumps([_raw_problem(3000)]), encoding="utf-8")
    conversion = convert_codecontests_file(
        path,
        split="validation",
        data_format=DatasetFormat.JSON,
        reviews=(_review(3000),),
        converter=ConversionTool(name="json-reader", version="1"),
    )

    quota = build_quota_report(conversion)

    assert quota.status is QuotaStatus.UNFULFILLED
    assert len(quota.cells) == 15
    greedy_foundation = next(
        cell
        for cell in quota.cells
        if cell.topic is Topic.GREEDY and cell.rating_band is RatingBand.FOUNDATION
    )
    assert greedy_foundation.eligible_problem_ids == ("cf-3000-a",)
    assert greedy_foundation.required == 2
    assert greedy_foundation.fulfilled is False
    assert sum(cell.eligible_count for cell in quota.cells) == 1
