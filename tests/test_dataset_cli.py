from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import hy3_algotrace.dataset_models as dataset_models
from hy3_algotrace.contracts import Topic
from hy3_algotrace.dataset_cli import main
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CheckerKind,
    ConversionTool,
    validate_acquired_assets,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _run_cli(*arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "hy3_algotrace.dataset_cli",
            *(str(argument) for argument in arguments),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


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
                "convert-preliminary",
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
                "convert-preliminary",
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
    """Every derived formal artifact can be produced by CLI before secure replay."""

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
    result = _run_cli(
        "validate-acquisition",
        acquisition_path,
        "--validation",
        raw_paths["validation"],
        "--test",
        raw_paths["test"],
        "--output",
        validation_report_path,
    )
    assert result.returncode == 0, result.stderr

    artifact_paths: list[Path] = []
    bare_reviews: list[dict[str, object]] = []
    for row in rows:
        row_id = int(row["cf_contest_id"])
        row_path = tmp_path / f"row-{row_id}.json"
        review_path = tmp_path / f"review-{row_id}.json"
        artifact_path = tmp_path / f"review-artifact-{row_id}.json"
        _write_json(row_path, row)
        review = CandidateReview(
            problem_id=f"cf-{row_id}-a",
            checker_reviewed=True,
            checker_kind=CheckerKind.STANDARD,
            reviewer="approved-human-reviewer",
            reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
            evidence_url=f"https://codeforces.com/problemset/problem/{row_id}/A",
        )
        bare_reviews.append(review.model_dump(mode="json"))
        _write_json(review_path, review.model_dump(mode="json"))
        result = _run_cli(
            "create-review-artifact",
            review_path,
            "--raw-row",
            row_path,
            "--output",
            artifact_path,
        )
        assert result.returncode == 0, result.stderr
        artifact_paths.append(artifact_path)
    review_set_paths = {
        "validation": tmp_path / "validation-reviews.json",
        "test": tmp_path / "test-reviews.json",
    }
    validation_set_argv: list[str | Path] = [
        "create-review-set",
        "--split",
        "validation",
        "--output",
        str(review_set_paths["validation"]),
    ]
    for artifact_path in artifact_paths:
        validation_set_argv.extend(("--artifact", artifact_path))
    result = _run_cli(*validation_set_argv)
    assert result.returncode == 0, result.stderr
    result = _run_cli(
        "create-review-set",
        "--split",
        "test",
        "--output",
        review_set_paths["test"],
    )
    assert result.returncode == 0, result.stderr
    review_manifest_path = tmp_path / "review-manifest.json"
    result = _run_cli(
        "pin-review-manifest",
        "--validation",
        review_set_paths["validation"],
        "--test",
        review_set_paths["test"],
        "--output",
        review_manifest_path,
    )
    assert result.returncode == 0, result.stderr

    conversion_paths = {
        split: tmp_path / f"formal-{split}-conversion.json" for split in ("validation", "test")
    }
    for split in ("validation", "test"):
        result = _run_cli(
            "convert-formal",
            raw_paths[split],
            "--split",
            split,
            "--format",
            "json",
            "--review-set",
            review_set_paths[split],
            "--review-manifest",
            review_manifest_path,
            "--converter-name",
            "secure-cli-json",
            "--converter-version",
            "1",
            "--validation-report",
            validation_report_path,
            "--output",
            conversion_paths[split],
        )
        assert result.returncode == 0, result.stderr

    quota_path = tmp_path / "formal-quota.json"
    result = _run_cli(
        "quota",
        conversion_paths["validation"],
        conversion_paths["test"],
        "--output",
        quota_path,
    )
    assert result.returncode == 0, result.stderr
    selected_ids_path = tmp_path / "selected-ids.json"
    _write_json(
        selected_ids_path,
        [f"cf-{int(row['cf_contest_id'])}-a" for row in rows],
    )
    selection_path = tmp_path / "selection.json"
    result = _run_cli(
        "freeze-selection",
        selected_ids_path,
        "--conversion",
        conversion_paths["validation"],
        "--conversion",
        conversion_paths["test"],
        "--quota",
        quota_path,
        "--acquisition",
        acquisition_path,
        "--validation-report",
        validation_report_path,
        "--output",
        selection_path,
    )
    assert result.returncode == 0, result.stderr
    result = _run_cli(
        "validate-selection-preliminary",
        selection_path,
        "--conversion",
        conversion_paths["validation"],
        "--conversion",
        conversion_paths["test"],
        "--quota",
        quota_path,
        "--acquisition",
        acquisition_path,
        "--validation-report",
        validation_report_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("preliminary-structural-only:")

    artifact_hashes = {
        json.loads(path.read_text(encoding="utf-8"))["content_hash"] for path in artifact_paths
    }
    selection_payload = json.loads(selection_path.read_text(encoding="utf-8"))
    assert {entry["review_hash"] for entry in selection_payload["entries"]} == artifact_hashes

    receipt_path = tmp_path / "selection-replay-receipt.json"
    result = _run_cli(
        "verify-selection-chain",
        selection_path,
        "--validation-raw",
        raw_paths["validation"],
        "--test-raw",
        raw_paths["test"],
        "--validation-format",
        "json",
        "--test-format",
        "json",
        "--acquisition",
        acquisition_path,
        "--validation-report",
        validation_report_path,
        "--validation-reviews",
        review_set_paths["validation"],
        "--test-reviews",
        review_set_paths["test"],
        "--review-manifest",
        review_manifest_path,
        "--output",
        receipt_path,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["kind"] == "verified_selection_replay_receipt"
    assert receipt["selection_manifest_hash"] == selection_payload["content_hash"]
    assert (
        receipt["review_manifest_hash"]
        == json.loads(review_manifest_path.read_text(encoding="utf-8"))["content_hash"]
    )
    assert receipt["formal_eligibility"] is False
    assert receipt["capability_persisted"] is False

    preliminary_reviews = {
        "validation": tmp_path / "bare-validation-reviews.json",
        "test": tmp_path / "bare-test-reviews.json",
    }
    _write_json(preliminary_reviews["validation"], bare_reviews)
    _write_json(preliminary_reviews["test"], [])
    preliminary_conversions = {
        split: tmp_path / f"preliminary-{split}-conversion.json" for split in ("validation", "test")
    }
    for split in ("validation", "test"):
        result = _run_cli(
            "convert-preliminary",
            raw_paths[split],
            "--split",
            split,
            "--format",
            "json",
            "--reviews",
            preliminary_reviews[split],
            "--converter-name",
            "secure-cli-json",
            "--converter-version",
            "1",
            "--validation-report",
            validation_report_path,
            "--output",
            preliminary_conversions[split],
        )
        assert result.returncode == 0, result.stderr
    preliminary_quota_path = tmp_path / "preliminary-quota.json"
    result = _run_cli(
        "quota",
        preliminary_conversions["validation"],
        preliminary_conversions["test"],
        "--output",
        preliminary_quota_path,
    )
    assert result.returncode == 0, result.stderr
    rejected_selection = tmp_path / "must-not-freeze-preliminary.json"
    result = _run_cli(
        "freeze-selection",
        selected_ids_path,
        "--conversion",
        preliminary_conversions["validation"],
        "--conversion",
        preliminary_conversions["test"],
        "--quota",
        preliminary_quota_path,
        "--acquisition",
        acquisition_path,
        "--validation-report",
        validation_report_path,
        "--output",
        rejected_selection,
    )
    assert result.returncode == 2
    assert result.stderr == "error: dataset command failed\n"
    assert not rejected_selection.exists()
