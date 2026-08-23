from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import hy3_algotrace.dataset_models as dataset_models
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
        logical_ids={"validation": "validation-raw", "test": "test-raw"},
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
        "--validation-id",
        "official-validation",
        "--test-id",
        "official-test",
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
            "--validation-id",
            "validation-raw",
            "--test-id",
            "test-raw",
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
