"""Tests for the deterministic 30-problem human-review checklist generator."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from hy3_algotrace.artifacts import ArtifactStore, canonical_json_bytes, sha256_json
from hy3_algotrace.contracts import RatingBand, Topic

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "select_human_review.py"
_spec = importlib.util.spec_from_file_location("select_human_review", _SCRIPT)
assert _spec is not None and _spec.loader is not None
selection = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(selection)

_CELLS = [(topic.value, band.value) for topic in Topic for band in RatingBand]


def _row(
    number: int,
    topic: str,
    band: str,
    *,
    rating: int = 1300,
    extra_topics: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    contest = 2000 + number
    return {
        "split": "validation" if number % 2 else "test",
        "row_number": number,
        "problem_id": f"cf-{contest}-{number}",
        "raw_row_hash": sha256_json({"row": number, "topic": topic, "band": band}),
        "title": f"Problem {number}",
        "source_url": f"https://codeforces.com/problemset/problem/{contest}/{number}",
        "rating": rating,
        "rating_band": band,
        "possible_topics": [topic, *extra_topics],
        "checker_warnings": list(warnings),
        "candidate": True,
    }


def _pool(per_cell: int = 2, **kwargs: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    number = 0
    for topic, band in _CELLS:
        for _ in range(per_cell):
            number += 1
            rows.append(_row(number, topic, band, **kwargs))
    return rows


def _preflight_file(tmp_path: Path, rows: list[dict[str, Any]], kind: str = "codecontests_data_preflight") -> Path:
    path = tmp_path / "data-preflight.json"
    path.write_text(json.dumps({"kind": kind, "rows": rows}), encoding="utf-8")
    return path


def test_rule_hash_binds_the_frozen_rule_parameters() -> None:
    assert selection.RULE_ID == "formal-selection-quota-15-cell-v1"
    assert selection.rule_hash() == sha256_json(selection.SELECTION_RULE)
    changed = dict(selection.SELECTION_RULE, problems_per_cell=3)
    assert sha256_json(changed) != selection.rule_hash()


def test_selection_fills_every_quota_cell_with_two_distinct_problems() -> None:
    items, report = selection.select_problems(_pool(per_cell=3))
    assert [item["order"] for item in items] == list(range(1, 31))
    assert len({item["problem_id"] for item in items}) == 30
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        key = (item["quota_cell"]["topic"], item["quota_cell"]["rating_band"])
        counts[key] = counts.get(key, 0) + 1
    assert counts == {cell: 2 for cell in _CELLS}
    assert report["selected_count"] == 30
    assert report["candidate_count"] == 45


def test_selection_prefers_checker_warning_free_candidates() -> None:
    clean = _pool(per_cell=3)
    noisy = [
        _row(1000 + index, topic, band, warnings=("possible_multiple_answers",))
        for index, (topic, band) in enumerate(_CELLS)
    ]
    items, report = selection.select_problems(clean + noisy)
    assert report["used_advisory_screened_pool"] is True
    assert all(item["checker_warnings"] == [] for item in items)


def test_selection_falls_back_when_the_screened_pool_cannot_fill_a_cell() -> None:
    rows = _pool(per_cell=2, warnings=("possible_tolerance",))
    rows.append(_row(900, _CELLS[0][0], _CELLS[0][1], rating=1200))
    rows.append(_row(901, _CELLS[0][0], _CELLS[0][1], rating=1201))
    items, report = selection.select_problems(rows)
    assert report["used_advisory_screened_pool"] is False
    first_cell = [
        item
        for item in items
        if (item["quota_cell"]["topic"], item["quota_cell"]["rating_band"]) == _CELLS[0]
    ]
    assert len(first_cell) == 2
    assert all(item["checker_warnings"] == [] for item in first_cell)


def test_shortfall_fails_closed_without_a_partial_checklist() -> None:
    rows = [row for index, row in enumerate(_pool(per_cell=2)) if index != 3]
    with pytest.raises(selection.SelectionRuleError, match="cannot fill every quota cell"):
        selection.select_problems(rows)


def test_review_fields_start_empty_and_are_listed() -> None:
    items, _ = selection.select_problems(_pool(per_cell=2))
    for item in items:
        assert item["review_status"] == "pending_human_review"
        assert item["checker_reviewed"] is False
        assert item["checker_kind"] == "unreviewed"
        assert item["primary_topic"] is None
        assert item["primary_topic_reviewed"] is False
        assert item["reviewer"] is None
        assert item["reviewed_at"] is None
        assert item["notes"] == ""
    assert set(selection.REVIEW_FIELDS) <= set(items[0])


def test_checklist_hashes_bind_items_and_never_claim_formality() -> None:
    rows = _pool(per_cell=2)
    source = {"kind": "test"}
    checklist, manifest = selection.build_checklist(
        rows, recorded_at="2026-09-10T00:00:00+00:00", source=source
    )
    assert checklist["formal_eligibility"] is False
    assert manifest["formal_eligibility"] is False
    assert manifest["items_hash"] == sha256_json(checklist["items"])
    assert checklist["rule_hash"] == selection.rule_hash()
    replaced = [
        dict(row, problem_id="cf-9999-z")
        if row["problem_id"] == checklist["items"][0]["problem_id"]
        else row
        for row in rows
    ]
    other, other_manifest = selection.build_checklist(
        replaced, recorded_at="2026-09-10T00:00:00+00:00", source=source
    )
    assert other_manifest["items_hash"] != manifest["items_hash"]
    assert other["items"] != checklist["items"]


def test_selection_is_deterministic_under_row_reordering() -> None:
    rows = _pool(per_cell=3)
    forward, _ = selection.select_problems(rows)
    backward, _ = selection.select_problems(list(reversed(rows)))
    assert forward == backward


def test_items_reference_the_exact_raw_row_identity() -> None:
    rows = _pool(per_cell=2)
    by_id = {row["problem_id"]: row for row in rows}
    items, _ = selection.select_problems(rows)
    for item in items:
        source = by_id[item["problem_id"]]
        assert item["raw_row_hash"] == source["raw_row_hash"]
        assert item["row_number"] == source["row_number"]
        assert item["split"] == source["split"]
        assert item["proposed_topic"] in source["possible_topics"]


def test_cli_writes_create_only_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "human-review-20260910-v1"
    preflight = _preflight_file(tmp_path, _pool(per_cell=2))
    assert selection.main(["--preflight", str(preflight), "--output-root", str(root)]) == 0
    checklist = json.loads((root / selection.CHECKLIST_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((root / selection.MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert len(checklist["items"]) == 30
    assert manifest["checklist_hash"] == sha256_json(checklist)
    assert manifest["rule_hash"] == selection.rule_hash()
    assert selection.main(["--preflight", str(preflight), "--output-root", str(root)]) == 2


def test_publish_accepts_a_blocked_temp_cleanup_only_when_content_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ArtifactStore(tmp_path)
    payload = {"kind": "test"}

    def blocked(self: ArtifactStore, relative_path: Any, payload: Any, **_: Any) -> Any:
        (self.root / relative_path).write_bytes(canonical_json_bytes(payload))
        raise PermissionError("sandbox blocks directory-relative unlink")

    monkeypatch.setattr(ArtifactStore, "write_json", blocked)
    assert selection._publish(store, "checklist.json", payload) == sha256_json(payload)

    def blocked_wrong(self: ArtifactStore, relative_path: Any, payload: Any, **_: Any) -> Any:
        (self.root / relative_path).write_bytes(canonical_json_bytes({"kind": "other"}))
        raise PermissionError("sandbox blocks directory-relative unlink")

    monkeypatch.setattr(ArtifactStore, "write_json", blocked_wrong)
    with pytest.raises(PermissionError):
        selection._publish(store, "manifest.json", payload)


def test_cli_rejects_a_non_preflight_input(tmp_path: Path) -> None:
    payload = _preflight_file(tmp_path, _pool(per_cell=2), kind="something_else")
    assert selection.main(["--preflight", str(payload), "--output-root", str(tmp_path / "out")]) == 2


def test_cli_refuses_a_populated_output_root(tmp_path: Path) -> None:
    root = tmp_path / "occupied"
    root.mkdir()
    (root / "stale.json").write_text("{}", encoding="utf-8")
    preflight = _preflight_file(tmp_path, _pool(per_cell=2))
    assert selection.main(["--preflight", str(preflight), "--output-root", str(root)]) == 2
    assert (root / "stale.json").read_text(encoding="utf-8") == "{}"
    assert not (root / selection.CHECKLIST_FILENAME).exists()
