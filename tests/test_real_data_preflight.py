from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_dataset_cli import _formal_row

from hy3_algotrace import data_preflight
from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.codecontests import _map_codecontests_record
from hy3_algotrace.contracts import Topic


@pytest.mark.parametrize(
    ("byte_limit", "expected_mib"),
    [(256_000_000, 244), (512_000_000, 488), (268_435_456, 256)],
)
def test_decimal_byte_limits_never_allocate_more_than_source(
    byte_limit: int, expected_mib: int
) -> None:
    row = _formal_row(1001, Topic.GREEDY, 1300)
    row["memory_limit_bytes"] = byte_limit
    record = _map_codecontests_record(row, split="validation")
    assert record.memory_limit_mb == expected_mib
    assert 0 <= byte_limit - record.memory_limit_mb * 1024**2 < 1024**2
    assert row["memory_limit_bytes"] == byte_limit


@pytest.mark.parametrize("byte_limit", [True, 0, -1, 0.5, "256000000", 1024**2 - 1])
def test_invalid_or_sub_mib_limits_fail_closed(byte_limit: object) -> None:
    row = _formal_row(1001, Topic.GREEDY, 1300)
    row["memory_limit_bytes"] = byte_limit
    with pytest.raises(ValueError, match="memory"):
        _map_codecontests_record(row, split="validation")


def test_preflight_keeps_ambiguous_rows_pending_but_checks_their_other_fields() -> None:
    good = _formal_row(1001, Topic.GREEDY, 1300)
    good["cf_tags"] = ["greedy", "binary search"]
    good["memory_limit_bytes"] = 256_000_000
    bad = dict(good, cf_contest_id=1002, cf_rating=800)
    report = data_preflight.assess_rows({"validation": [good, bad], "test": []})
    assert report["candidate_count"] == 1
    assert report["formal_eligibility"] is False
    first, second = report["rows"]
    assert first["raw_row_hash"] == sha256_json(good)
    assert first["possible_topics"] == ["greedy", "binary_search"]
    assert first["review_status"] == "pending_human_review"
    assert first["source_memory_bytes"] == 256_000_000
    assert first["judge_memory_mib"] == 244
    assert "rating_outside_frozen_bands" in second["blocking_reasons"]


def test_assignment_does_not_double_count_overlapping_topic_candidates() -> None:
    rows = [_formal_row(i, Topic.GREEDY, 1300) for i in range(1001, 1004)]
    rows[0]["cf_tags"] = ["greedy", "binary search"]
    rows[1]["cf_tags"] = ["greedy", "binary search"]
    report = data_preflight.assess_rows({"validation": rows, "test": []})
    cells = {(c["topic"], c["rating_band"]): c for c in report["quota_cells"]}
    assert cells[("greedy", "1200-1500")]["candidate_count"] == 3
    assert cells[("binary_search", "1200-1500")]["candidate_count"] == 2
    assert report["maximum_assignable"] == 3
    assert len({x["problem_id"] for x in report["proposed_assignment"]}) == 3
    assert report["quota_feasible_before_human_review"] is False
    assert sum(c["assigned_count"] for c in report["quota_cells"]) == 3
    assert report == data_preflight.assess_rows({"validation": rows, "test": []})


def test_duplicate_ids_across_splits_are_excluded_in_both_places() -> None:
    row = _formal_row(1001, Topic.GREEDY, 1300)
    report = data_preflight.assess_rows({"validation": [row], "test": [row]})
    assert report["candidate_count"] == 0
    assert all("duplicate_problem_id" in x["blocking_reasons"] for x in report["rows"])


@pytest.mark.parametrize(
    "statement",
    [
        "Output\nIf there are multiple answers, print any of them.",
        "Output the array. Note: you could also print 3 -3, for example.",
    ],
)
def test_statement_screen_flags_multiple_answers_without_claiming_checker_review(
    statement: str,
) -> None:
    row = _formal_row(1001, Topic.GREEDY, 1300)
    row["description"] = statement
    report = data_preflight.assess_rows({"validation": [row], "test": []})
    assert report["candidate_count"] == 1
    assert report["rows"][0]["checker_warnings"] == ["possible_multiple_answers"]
    assert report["rows"][0]["review_status"] == "pending_human_review"
    assert report["checker_screened_maximum_assignable"] == 0


def test_complete_assignment_prefers_unflagged_candidates_in_every_cell() -> None:
    rows = []
    for topic in Topic:
        for rating in (1300, 1700, 2200):
            for _ in range(2):
                rows.append(_formal_row(1001 + len(rows), topic, rating))
    flagged = _formal_row(999, Topic.GREEDY, 1200)
    flagged["description"] = "Output any valid solution."
    report = data_preflight.assess_rows({"validation": [flagged, *rows], "test": []})
    assert report["maximum_assignable"] == 30
    assert report["checker_screened_maximum_assignable"] == 30
    assert len({x["problem_id"] for x in report["proposed_assignment"]}) == 30
    assert "cf-999-a" not in {x["problem_id"] for x in report["proposed_assignment"]}


def test_preflight_export_is_create_only_and_contains_no_private_content(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    row = _formal_row(1001, Topic.GREEDY, 1300)
    row["private_tests"] = [{"input": "HIDDEN_INPUT_SENTINEL", "output": "SECRET_OUTPUT"}]
    row["solutions"] = {"solution": ["THIRD_PARTY_CODE_SENTINEL"]}
    row["description"] = "STATEMENT_SENTINEL"
    (raw / "validation.json").write_text(json.dumps([row]))
    (raw / "test.json").write_text("[]")
    output = tmp_path / "output"
    args = [
        "--validation",
        str(raw / "validation.json"),
        "--test",
        str(raw / "test.json"),
        "--validation-url",
        "https://example.org/validation.json",
        "--test-url",
        "https://example.org/test.json",
        "--format",
        "json",
        "--output-root",
        str(output),
        "--acknowledge-third-party-terms",
    ]
    assert data_preflight.main(args) == 0
    files = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*.json")}
    contents = b"".join(files.values())
    for forbidden in (
        b"HIDDEN_INPUT_SENTINEL",
        b"SECRET_OUTPUT",
        b"THIRD_PARTY_CODE_SENTINEL",
        b"STATEMENT_SENTINEL",
    ):
        assert forbidden not in contents
    assert b'"publisher_verified":false' in contents
    assert b'"reviewer":null' in contents
    assert data_preflight.main(args) == 2
    assert files == {str(p.relative_to(output)): p.read_bytes() for p in output.rglob("*.json")}


def test_preflight_refuses_raw_symlinks(tmp_path: Path) -> None:
    actual = tmp_path / "actual.json"
    actual.write_text("[]")
    alias = tmp_path / "alias.json"
    alias.symlink_to(actual)
    args = [
        "--validation",
        str(alias),
        "--test",
        str(actual),
        "--validation-url",
        "https://example.org/validation.json",
        "--test-url",
        "https://example.org/test.json",
        "--format",
        "json",
        "--output-root",
        str(tmp_path / "out"),
        "--acknowledge-third-party-terms",
    ]
    assert data_preflight.main(args) == 2
    assert not (tmp_path / "out").exists()
