from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import hy3_algotrace.dataset_models as dataset_models
from hy3_algotrace.contracts import Topic
from hy3_algotrace.dataset_cli import main
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    AcquisitionValidationReport,
    CandidateReview,
    CandidateReviewSet,
    CheckerKind,
    ConversionTool,
    DatasetFormat,
    ReviewArtifactManifest,
    build_quota_report,
    convert_codecontests_file,
    freeze_selection,
    validate_acquired_assets,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _formal_row(contest_id: int, topic: Topic, rating: int) -> dict[str, object]:
    tag = {
        Topic.CONSTRUCTION_SIMULATION: "implementation",
        Topic.GREEDY: "greedy",
        Topic.BINARY_SEARCH: "binary search",
        Topic.DYNAMIC_PROGRAMMING: "dp",
        Topic.GRAPH: "graphs",
    }[topic]
    return {
        "name": f"Problem {contest_id}",
        "description": "Print the input integer.",
        "source": 2,
        "cf_contest_id": contest_id,
        "cf_index": "A",
        "cf_rating": rating,
        "cf_tags": [tag],
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


def _write_validation_report(
    tmp_path: Path,
    source: Path,
    *,
    split: str,
    converter: ConversionTool,
) -> Path:
    other_split = "test" if split == "validation" else "validation"
    other = tmp_path / f"{other_split}-raw.json"
    other.write_text("[]", encoding="utf-8")
    paths = {split: source, other_split: other}
    assets = tuple(
        AcquisitionAsset(
            split=item,
            url=f"https://example.invalid/{item}.json",
            byte_length=len(paths[item].read_bytes()),
            sha256=hashlib.sha256(paths[item].read_bytes()).hexdigest(),
            license="CC-BY-4.0 plus third-party terms",
            attribution="Google DeepMind CodeContests and Codeforces",
        )
        for item in ("validation", "test")
    )
    manifest = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=assets,
        converter=converter,
        third_party_terms_acknowledged=True,
    )
    report = validate_acquired_assets(
        manifest,
        paths,
    )
    output = tmp_path / f"{split}-validation-report.json"
    _write_json(output, report.model_dump(mode="json"))
    return output


def test_cli_validates_external_acquisition_and_writes_create_only_report(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    """A second invocation cannot overwrite the acquisition validation artifact."""

    valid = b"valid bytes"
    test = b"test bytes"
    valid_path = tmp_path / "valid.riegeli"
    test_path = tmp_path / "test.riegeli"
    valid_path.write_bytes(valid)
    test_path.write_bytes(test)
    manifest = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=(
            AcquisitionAsset(
                split="validation",
                url="https://storage.googleapis.com/dm-code_contests/code_contests_valid.riegeli",
                byte_length=len(valid),
                sha256=hashlib.sha256(valid).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
            AcquisitionAsset(
                split="test",
                url="https://storage.googleapis.com/dm-code_contests/code_contests_test.riegeli",
                byte_length=len(test),
                sha256=hashlib.sha256(test).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
        ),
        converter=ConversionTool(name="official-riegeli-export", version="1"),
        third_party_terms_acknowledged=True,
    )
    manifest_path = tmp_path / "acquisition.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    output = tmp_path / "validation-report.json"
    argv = [
        "validate-acquisition",
        str(manifest_path),
        "--validation",
        str(valid_path),
        "--test",
        str(test_path),
        "--output",
        str(output),
    ]

    assert main(argv) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["valid"] is True
    assert main(argv) == 2
    assert "create-only" in capsys.readouterr().err


def test_cli_reads_manifest_from_one_trusted_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLI input path swap after open cannot replace the parsed manifest bytes."""

    validation_bytes = b"validation"
    test_bytes = b"test"
    validation_path = tmp_path / "validation.riegeli"
    test_path = tmp_path / "test.riegeli"
    validation_path.write_bytes(validation_bytes)
    test_path.write_bytes(test_bytes)
    manifest = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=(
            AcquisitionAsset(
                split="validation",
                url="https://example.invalid/validation.riegeli",
                byte_length=len(validation_bytes),
                sha256=hashlib.sha256(validation_bytes).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
            AcquisitionAsset(
                split="test",
                url="https://example.invalid/test.riegeli",
                byte_length=len(test_bytes),
                sha256=hashlib.sha256(test_bytes).hexdigest(),
                license="CC-BY-4.0 plus third-party terms",
                attribution="Google DeepMind CodeContests and Codeforces",
            ),
        ),
        converter=ConversionTool(name="riegeli", version="1"),
        third_party_terms_acknowledged=True,
    )
    manifest_path = tmp_path / "acquisition.json"
    _write_json(manifest_path, manifest.model_dump(mode="json"))
    saved = tmp_path / "acquisition-before-swap.json"
    attacker = tmp_path / "attacker.json"
    attacker.write_text("{}", encoding="utf-8")
    real_open = dataset_models.os.open
    swapped = False

    def swap_after_open(path: object, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        file_fd = real_open(path, *args, **kwargs)
        if path == manifest_path.name and kwargs.get("dir_fd") is not None and not swapped:
            manifest_path.rename(saved)
            manifest_path.symlink_to(attacker)
            swapped = True
        return file_fd

    monkeypatch.setattr(dataset_models.os, "open", swap_after_open)

    exit_code = main(
        [
            "validate-acquisition",
            str(manifest_path),
            "--validation",
            str(validation_path),
            "--test",
            str(test_path),
            "--output",
            str(tmp_path / "report.json"),
        ]
    )

    assert swapped is True
    assert exit_code == 0


def test_cli_conversion_and_quota_preserve_unfulfilled_status(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    """A one-row import emits an honest quota artifact and a distinct pending exit."""

    problem = {
        "name": "Identity",
        "description": "Print the input.",
        "source": 2,
        "cf_contest_id": 7000,
        "cf_index": "A",
        "cf_rating": 1400,
        "cf_tags": ["greedy"],
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
    source = tmp_path / "rows.json"
    _write_json(source, [problem])
    review = CandidateReview(
        problem_id="cf-7000-a",
        checker_reviewed=True,
        checker_kind=CheckerKind.STANDARD,
        reviewer="curator",
        reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
        evidence_url="https://codeforces.com/problemset/problem/7000/A",
    )
    reviews = tmp_path / "reviews.json"
    _write_json(reviews, [review.model_dump(mode="json")])
    conversion = tmp_path / "conversion.json"
    converter = ConversionTool(name="json-reader", version="1")
    validation_report = _write_validation_report(
        tmp_path,
        source,
        split="validation",
        converter=converter,
    )

    assert (
        main(
            [
                "convert",
                str(source),
                "--split",
                "validation",
                "--format",
                "json",
                "--reviews",
                str(reviews),
                "--converter-name",
                "json-reader",
                "--converter-version",
                "1",
                "--validation-report",
                str(validation_report),
                "--output",
                str(conversion),
            ]
        )
        == 0
    )
    quota = tmp_path / "quota.json"
    assert main(["quota", str(conversion), "--output", str(quota)]) == 3
    quota_payload = json.loads(quota.read_text(encoding="utf-8"))
    assert quota_payload["status"] == "unfulfilled_quota"
    assert len(quota_payload["cells"]) == 15
    assert "unfulfilled_quota" in capsys.readouterr().out


def test_cli_errors_are_sanitized_and_do_not_echo_hidden_row_content(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    """Malformed input errors must not print statements, tests, or tracebacks."""

    source = tmp_path / "secret.json"
    source.write_text('{"private_tests":"DO_NOT_PRINT"', encoding="utf-8")
    reviews = tmp_path / "reviews.json"
    _write_json(reviews, [])
    validation_report = _write_validation_report(
        tmp_path,
        source,
        split="test",
        converter=ConversionTool(name="json-reader", version="1"),
    )

    assert (
        main(
            [
                "convert",
                str(source),
                "--split",
                "test",
                "--format",
                "json",
                "--reviews",
                str(reviews),
                "--converter-name",
                "json-reader",
                "--converter-version",
                "1",
                "--validation-report",
                str(validation_report),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert "DO_NOT_PRINT" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.err == "error: dataset command failed\n"


def test_cli_secure_review_pin_and_selection_replay_workflow(tmp_path: Path) -> None:
    """The CLI can reach trusted raw/review replay without persisting its capability."""

    rows: list[dict[str, object]] = []
    contest_id = 8000
    for topic in Topic:
        for rating in (1300, 1700, 2100):
            for _ in range(2):
                rows.append(_formal_row(contest_id, topic, rating))
                contest_id += 1
    raw_paths = {
        "validation": tmp_path / "validation.json",
        "test": tmp_path / "test.json",
    }
    _write_json(raw_paths["validation"], rows)
    _write_json(raw_paths["test"], [])
    converter = ConversionTool(name="secure-cli-json", version="1")
    acquisition = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=tuple(
            AcquisitionAsset(
                split=split,
                url=f"https://example.invalid/{split}.json",
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
    acquisition_path = tmp_path / "acquisition.json"
    _write_json(acquisition_path, acquisition.model_dump(mode="json"))
    validation_report_path = tmp_path / "acquisition-validation.json"
    assert (
        main(
            [
                "validate-acquisition",
                str(acquisition_path),
                "--validation",
                str(raw_paths["validation"]),
                "--test",
                str(raw_paths["test"]),
                "--output",
                str(validation_report_path),
            ]
        )
        == 0
    )

    artifact_paths: list[Path] = []
    for row in rows:
        row_id = int(row["cf_contest_id"])
        row_path = tmp_path / f"row-{row_id}.json"
        review_path = tmp_path / f"review-{row_id}.json"
        artifact_path = tmp_path / f"review-artifact-{row_id}.json"
        _write_json(row_path, row)
        _write_json(
            review_path,
            CandidateReview(
                problem_id=f"cf-{row_id}-a",
                checker_reviewed=True,
                checker_kind=CheckerKind.STANDARD,
                reviewer="approved-human-reviewer",
                reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
                evidence_url=f"https://codeforces.com/problemset/problem/{row_id}/A",
            ).model_dump(mode="json"),
        )
        assert (
            main(
                [
                    "create-review-artifact",
                    str(review_path),
                    "--raw-row",
                    str(row_path),
                    "--output",
                    str(artifact_path),
                ]
            )
            == 0
        )
        artifact_paths.append(artifact_path)
    review_set_paths = {
        "validation": tmp_path / "validation-reviews.json",
        "test": tmp_path / "test-reviews.json",
    }
    validation_set_argv = [
        "create-review-set",
        "--split",
        "validation",
        "--output",
        str(review_set_paths["validation"]),
    ]
    for artifact_path in artifact_paths:
        validation_set_argv.extend(("--artifact", str(artifact_path)))
    assert main(validation_set_argv) == 0
    assert (
        main(
            [
                "create-review-set",
                "--split",
                "test",
                "--output",
                str(review_set_paths["test"]),
            ]
        )
        == 0
    )
    review_manifest_path = tmp_path / "review-manifest.json"
    assert (
        main(
            [
                "pin-review-manifest",
                "--validation",
                str(review_set_paths["validation"]),
                "--test",
                str(review_set_paths["test"]),
                "--output",
                str(review_manifest_path),
            ]
        )
        == 0
    )

    acquisition_validation = AcquisitionValidationReport.model_validate_json(
        validation_report_path.read_text(encoding="utf-8")
    )
    review_sets = {
        split: CandidateReviewSet.model_validate_json(
            review_set_paths[split].read_text(encoding="utf-8")
        )
        for split in ("validation", "test")
    }
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
    selection_path = tmp_path / "selection.json"
    _write_json(selection_path, selection.model_dump(mode="json"))
    receipt_path = tmp_path / "selection-replay-receipt.json"
    assert (
        main(
            [
                "verify-selection-chain",
                str(selection_path),
                "--validation-raw",
                str(raw_paths["validation"]),
                "--test-raw",
                str(raw_paths["test"]),
                "--validation-format",
                "json",
                "--test-format",
                "json",
                "--acquisition",
                str(acquisition_path),
                "--validation-report",
                str(validation_report_path),
                "--validation-reviews",
                str(review_set_paths["validation"]),
                "--test-reviews",
                str(review_set_paths["test"]),
                "--review-manifest",
                str(review_manifest_path),
                "--output",
                str(receipt_path),
            ]
        )
        == 0
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["kind"] == "verified_selection_replay_receipt"
    assert receipt["selection_manifest_hash"] == selection.content_hash
    assert (
        receipt["review_manifest_hash"]
        == ReviewArtifactManifest.model_validate_json(
            review_manifest_path.read_text(encoding="utf-8")
        ).content_hash
    )
    assert receipt["formal_eligibility"] is False
    assert receipt["capability_persisted"] is False
