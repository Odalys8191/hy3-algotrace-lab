from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from hy3_algotrace.dataset_cli import main
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CheckerKind,
    ConversionTool,
)


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


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
