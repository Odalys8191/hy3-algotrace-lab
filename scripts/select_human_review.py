"""Deterministic 30-problem human-review checklist for the formal corpus freeze.

Hy3 AlgoTrace Lab is a personal activity project and not an official Tencent release.

The selection rule is documented in ``docs/FORMAL_CORPUS_LIFECYCLE.md``. The
matching itself lives in :func:`hy3_algotrace.data_preflight.assign_candidates`
so the preflight draft and this checklist can never drift apart; this module
only fixes the rule parameters, binds them by content hash, and emits a
checklist whose review fields are left empty for a human to fill.

The script never writes a review decision, never converts a draft into a
``CandidateReview``, and never claims formal eligibility.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hy3_algotrace.artifacts import ArtifactStore, ArtifactStoreError, sha256_json
from hy3_algotrace.contracts import RatingBand, Topic
from hy3_algotrace.data_preflight import assess_rows, assign_candidates
from hy3_algotrace.data_preflight import canonical_raw_split_logical_id
from hy3_algotrace.dataset_models import DatasetDataError, DatasetFormat, _load_rows
from hy3_algotrace.dataset_models import read_trusted_file

CHECKLIST_FILENAME = "human-review-checklist.json"
MANIFEST_FILENAME = "selection-manifest.json"
SCHEMA_VERSION = "1.2"
EXPECTED_SELECTION_SIZE = 30

RULE_ID = "formal-selection-quota-15-cell-v1"
SELECTION_RULE: dict[str, Any] = {
    "rule_id": RULE_ID,
    "schema_version": SCHEMA_VERSION,
    "quota_cells": [
        {"topic": topic.value, "rating_band": band.value}
        for topic in Topic
        for band in RatingBand
    ],
    "problems_per_cell": 2,
    "expected_selection_size": EXPECTED_SELECTION_SIZE,
    "candidate_definition": (
        "row passes the structural assessor used with no human reviews and maps "
        "under at least one supported topic"
    ),
    "advisory_screen": (
        "prefer candidates that raised no advisory checker warning; use the "
        "unscreened candidate pool when the screened pool cannot fill every cell"
    ),
    "slot_order": "by ascending cell candidate count, then topic, then rating band, then slot",
    "candidate_order": "fewest supported topics, then lowest rating, then problem ID",
    "matching": "deterministic bipartite augmentation; one slot per problem, no duplicates",
    "output_order": "topic, then rating band, then problem ID",
    "human_review_required": [
        "checker_semantics",
        "primary_topic",
        "source_provenance",
    ],
}

REVIEW_FIELDS: tuple[str, ...] = (
    "checker_reviewed",
    "checker_kind",
    "primary_topic",
    "primary_topic_reviewed",
    "reviewer",
    "reviewed_at",
    "notes",
)


class SelectionRuleError(RuntimeError):
    """Raised when the frozen selection rule cannot be satisfied."""


def rule_hash() -> str:
    """Content hash of the frozen selection rule parameters."""

    return sha256_json(SELECTION_RULE)


def _quota_cells() -> list[tuple[str, str]]:
    return [(topic.value, band.value) for topic in Topic for band in RatingBand]


def _screened_pool(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in candidates if not row.get("checker_warnings")]


def select_problems(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the ordered checklist items and the assignment report.

    ``rows`` are preflight row summaries (see
    :func:`hy3_algotrace.data_preflight.assess_rows`). A shortfall in any quota
    cell fails closed: no partial checklist is produced.
    """

    candidates = [row for row in rows if row.get("candidate")]
    unscreened, cells = assign_candidates(candidates)
    screened, _ = assign_candidates(_screened_pool(candidates))
    used_screened_pool = len(screened) == EXPECTED_SELECTION_SIZE
    assignments = screened if used_screened_pool else unscreened
    shortfalls = [cell for cell in cells if cell["shortfall"] > 0]
    if len(assignments) != EXPECTED_SELECTION_SIZE or shortfalls:
        raise SelectionRuleError(
            "selection rule cannot fill every quota cell; "
            f"assigned={len(assignments)} shortfall_cells={len(shortfalls)}"
        )
    by_id = {str(row.get("problem_id")): row for row in rows}
    items = []

    def _order(row: Mapping[str, str]) -> tuple[str, str, str]:
        return (row["proposed_topic"], row["rating_band"], row["problem_id"])

    for number, assignment in enumerate(sorted(assignments, key=_order), start=1):
        row = by_id[assignment["problem_id"]]
        items.append(
            {
                "order": number,
                "problem_id": assignment["problem_id"],
                "quota_cell": {
                    "topic": assignment["proposed_topic"],
                    "rating_band": assignment["rating_band"],
                },
                "split": row.get("split"),
                "row_number": row.get("row_number"),
                "raw_row_hash": row.get("raw_row_hash"),
                "title": row.get("title"),
                "evidence_url": row.get("source_url"),
                "rating": row.get("rating"),
                "rating_band": row.get("rating_band"),
                "proposed_topic": assignment["proposed_topic"],
                "supported_topics": list(row.get("possible_topics", ())),
                "checker_warnings": list(row.get("checker_warnings", ())),
                "review_status": "pending_human_review",
                "checker_reviewed": False,
                "checker_kind": "unreviewed",
                "primary_topic": None,
                "primary_topic_reviewed": False,
                "reviewer": None,
                "reviewed_at": None,
                "notes": "",
            }
        )
    report = {
        "candidate_count": len(candidates),
        "screened_candidate_count": len(_screened_pool(candidates)),
        "used_advisory_screened_pool": used_screened_pool,
        "quota_cells": cells,
        "selected_count": len(items),
    }
    return items, report


def build_checklist(
    rows: Sequence[Mapping[str, Any]],
    *,
    recorded_at: str,
    source: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the checklist and its binding manifest; review fields stay empty."""

    items, report = select_problems(rows)
    checklist: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "formal_human_review_checklist",
        "formal_eligibility": False,
        "rule_id": RULE_ID,
        "rule_hash": rule_hash(),
        "recorded_at": recorded_at,
        "source": dict(source),
        "items": items,
        "review_fields_to_complete": list(REVIEW_FIELDS),
        "instructions": (
            "Advisory draft only. A human must confirm standard checker semantics, the "
            "primary topic, and the source URL for every row, then supply their own "
            "reviewer identity and timezone-aware timestamp. Empty review fields must "
            "never be filled by a tool, and this file is not a CandidateReview input."
        ),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "formal_human_review_selection",
        "formal_eligibility": False,
        "rule_id": RULE_ID,
        "rule_hash": rule_hash(),
        "recorded_at": recorded_at,
        "source": dict(source),
        "selection_report": report,
        "items_hash": sha256_json(items),
        "checklist_hash": sha256_json(checklist),
    }
    return checklist, manifest


def _read_raw(dir_path: Path) -> tuple[list[Any], dict[str, Any]]:
    loaded: dict[str, list[Any]] = {}
    source: dict[str, Any] = {"kind": "raw_parquet", "files": {}}
    for split in ("validation", "test"):
        path = dir_path / f"{split}.parquet"
        snapshot = read_trusted_file(
            path, logical_id=canonical_raw_split_logical_id(split), max_bytes=256 * 1024**2
        )
        rows = _load_rows(
            snapshot.contents,
            source_label=snapshot.logical_id,
            data_format=DatasetFormat.PARQUET,
            converter_argv=None,
        )
        loaded[split] = rows
        source["files"][split] = {
            "path": str(path),
            "byte_length": snapshot.byte_length,
            "sha256": snapshot.sha256,
            "row_count": len(rows),
        }
    report = assess_rows(loaded)
    source["split_counts"] = report["split_counts"]
    source["candidate_count"] = report["candidate_count"]
    source["preflight_assignment_size"] = len(report["proposed_assignment"])
    return report["rows"], source


def _read_preflight(path: Path) -> tuple[list[Any], dict[str, Any]]:
    snapshot = read_trusted_file(path, logical_id="data-preflight", max_bytes=64 * 1024**2)
    report = json.loads(snapshot.contents)
    if report.get("kind") != "codecontests_data_preflight":
        raise DatasetDataError("input is not a data-preflight report")
    source = {
        "kind": "data_preflight_report",
        "path": str(path),
        "sha256": snapshot.sha256,
        "split_counts": report.get("split_counts"),
        "candidate_count": report.get("candidate_count"),
    }
    rows = report.get("rows")
    if not isinstance(rows, list):
        raise DatasetDataError("data-preflight report has no rows")
    return rows, source


def _reject_populated_root(root: Path) -> None:
    if root.exists() and any(root.iterdir()):
        raise ArtifactStoreError(f"output root is not empty: {root}")


def _publish(store: ArtifactStore, filename: str, payload: Mapping[str, Any]) -> str:
    """Publish one create-only artifact and return its canonical content hash.

    The store publishes with ``link`` and then removes its temporary file through
    a directory-relative ``unlink``. Some sandboxes block that cleanup after the
    link already succeeded, so a ``PermissionError`` here is resolved by reading
    the published artifact back and comparing its canonical hash. A mismatch or a
    missing artifact still fails closed.
    """

    try:
        return store.write_json(filename, payload).content_hash
    except PermissionError:
        published = store.read_json(filename)
        content_hash = sha256_json(published)
        if content_hash != sha256_json(payload):
            raise
        return content_hash


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hy3 AlgoTrace Lab: personal activity project, not an official "
        "Tencent release. Emit a 30-problem human-review checklist with empty review "
        "fields."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--raw-dir", type=Path, help="directory holding validation/test parquet")
    source.add_argument("--preflight", type=Path, help="existing data-preflight report JSON")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows, origin = (
            _read_raw(args.raw_dir) if args.raw_dir is not None else _read_preflight(args.preflight)
        )
        _reject_populated_root(args.output_root)
        checklist, manifest = build_checklist(
            rows,
            recorded_at=datetime.now(timezone.utc).isoformat(),
            source=origin,
        )
        store = ArtifactStore(args.output_root)
        checklist_hash = _publish(store, CHECKLIST_FILENAME, checklist)
        manifest_hash = _publish(store, MANIFEST_FILENAME, manifest)
    except (SelectionRuleError, DatasetDataError, ArtifactStoreError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "checklist": str(args.output_root / CHECKLIST_FILENAME),
                "checklist_hash": checklist_hash,
                "manifest": str(args.output_root / MANIFEST_FILENAME),
                "manifest_hash": manifest_hash,
                "items_hash": manifest["items_hash"],
                "rule_hash": manifest["rule_hash"],
                "selected_count": manifest["selection_report"]["selected_count"],
                "formal_eligibility": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
