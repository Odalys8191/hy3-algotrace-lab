"""Prepare acquisition and review drafts without manufacturing formal eligibility."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from .artifacts import ArtifactStore, ArtifactStoreError, sha256_json
from .contracts import RatingBand, Topic
from .dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    ConversionTool,
    DatasetDataError,
    DatasetFormat,
    _assess_row,
    _load_rows,
    _map_with_reviewed_topic,
    _mapping_reason,
    _matched_topics,
    _raw_problem_id,
    canonical_raw_split_logical_id,
    read_trusted_file,
    validate_acquired_assets,
)

type Split = Literal["validation", "test"]
SPLITS: tuple[Split, ...] = ("validation", "test")
MEMORY_POLICY = "floor-positive-bytes-to-MiB;reject-below-one-MiB"
_REVIEW_REASONS = frozenset({"checker_review_missing", "ambiguous_primary_topic"})
_MAX_RAW_BYTES = 256 * 1024**2


def _checker_warnings(statement: object) -> list[str]:
    """Advisory text screen only; absence of a match is NOT standard-checker proof."""
    if not isinstance(statement, str):
        return []
    patterns = {
        "possible_multiple_answers": (
            r"\b(?:print|output)\s+any\b|\b(?:multiple|several)\s+(?:valid\s+)?"
            r"(?:answers|solutions)\b|\bany\s+(?:of\s+them|order)\b"
            r"|\b(?:could|can|may)\s+also\s+(?:print|output)\b"
        ),
        "possible_interactive": r"\b(?:interactive|interaction)\b",
        "possible_tolerance": r"\b(?:absolute|relative)\s+error\b",
    }
    return sorted(name for name, pattern in patterns.items() if re.search(pattern, statement, re.I))


def assess_rows(rows_by_split: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
    """Compute an optimistic quota bound; every proposed choice needs human review.

    The formal assessor is used with NO reviews. Ambiguous tags are evaluated under
    each supported topic for structural feasibility only. This never constructs a
    CandidateReview or persists a provisional ProblemRecord.
    """
    if set(rows_by_split) != set(SPLITS):
        raise DatasetDataError("preflight requires validation and test")
    identities = Counter(
        _raw_problem_id(row)
        for split in SPLITS
        for row in rows_by_split[split]
        if isinstance(row, Mapping)
    )
    summaries: list[dict[str, Any]] = []
    for split in SPLITS:
        for number, raw in enumerate(rows_by_split[split], start=1):
            if not isinstance(raw, Mapping):
                summaries.append(
                    {
                        "split": split,
                        "row_number": number,
                        "problem_id": None,
                        "raw_row_hash": sha256_json(raw),
                        "candidate": False,
                        "blocking_reasons": ["row_not_object"],
                        "possible_topics": [],
                        "review_status": "excluded_automatically",
                    }
                )
                continue
            assessment = _assess_row(
                raw, row_number=number, split=split, reviews={}, seen_ids=set()
            )
            reasons = set(assessment.reasons) - _REVIEW_REASONS
            if assessment.problem_id is None:
                reasons.add("invalid_problem_id")
            elif identities[assessment.problem_id] > 1:
                reasons.add("duplicate_problem_id")
            raw_tags = raw.get("cf_tags", raw.get("tags"))
            tags = (
                tuple(x for x in raw_tags if isinstance(x, str))
                if isinstance(raw_tags, list)
                else ()
            )
            topics = _matched_topics(tags)
            possible: list[str] = []
            rating_band: str | None = None
            memory_mib: int | None = None
            # _assess_row cannot fully map multi-topic rows without a human topic.
            # Try every supported topic to uncover hidden/resource/rating failures.
            for topic in topics:
                try:
                    record = _map_with_reviewed_topic(
                        raw, split=split, selected_topic=topic, original_tags=tags
                    )
                except (TypeError, ValueError) as error:
                    reasons.add(_mapping_reason(error))
                else:
                    possible.append(topic.value)
                    rating_band = record.rating_band.value
                    memory_mib = record.memory_limit_mb
            if not possible and not reasons:
                reasons.add("invalid_record")
            candidate = not reasons and bool(possible)
            pid = assessment.problem_id
            url = None
            if pid is not None:
                _, contest, index = pid.split("-", 2)
                url = f"https://codeforces.com/problemset/problem/{contest}/{index.upper()}"
            summaries.append(
                {
                    "split": split,
                    "row_number": number,
                    "problem_id": pid,
                    "raw_row_hash": assessment.raw_row_hash,
                    "title": str(raw.get("name", ""))[:256],
                    "source_url": url,
                    "rating": raw.get("cf_rating"),
                    "rating_band": rating_band,
                    "tags": list(tags),
                    "possible_topics": possible,
                    "source_memory_bytes": raw.get("memory_limit_bytes"),
                    "judge_memory_mib": memory_mib,
                    "checker_warnings": _checker_warnings(raw.get("description")),
                    "candidate": candidate,
                    "blocking_reasons": sorted(reasons),
                    "review_status": "pending_human_review"
                    if candidate
                    else "excluded_automatically",
                    "pending_checks": ["checker_semantics", "primary_topic", "source_provenance"]
                    if candidate
                    else [],
                }
            )
    candidates = [row for row in summaries if row["candidate"]]
    assignments, cells = assign_candidates(candidates)
    screened = [row for row in candidates if not row["checker_warnings"]]
    screened_assignments, screened_cells = assign_candidates(screened)
    if len(screened_assignments) == 30:
        assignments = screened_assignments
    return {
        "schema_version": "1.2",
        "kind": "codecontests_data_preflight",
        "preflight_version": "data-preflight-v1",
        "formal_eligibility": False,
        "memory_policy": MEMORY_POLICY,
        "split_counts": {split: len(rows_by_split[split]) for split in SPLITS},
        "candidate_count": len(candidates),
        "excluded_count": len(summaries) - len(candidates),
        "blocking_reason_counts": dict(
            sorted(
                Counter(reason for row in summaries for reason in row["blocking_reasons"]).items()
            )
        ),
        "rows": summaries,
        "quota_cells": cells,
        "maximum_assignable": len(assignments),
        "checker_warning_count": len(candidates) - len(screened),
        "checker_screened_maximum_assignable": len(screened_assignments),
        "checker_screened_quota_cells": screened_cells,
        "checker_screen_notice": "Pattern screening is advisory, not human review; "
        "absence of a warning does not prove standard checking.",
        "quota_feasible_before_human_review": len(assignments) == 30,
        "proposed_assignment": assignments,
        "formal_reviewed_count": 0,
        "notice": "Optimistic structural feasibility only. Checker and primary-topic human "
        "reviews may exclude candidates. Proposed assignment is not a frozen selection.",
    }


def assign_candidates(
    candidates: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Fill the 15 quota cells with two distinct problems each, deterministically.

    Public because the formal checklist generator binds the same rule by content
    hash; the tie-break order (fewest supported topics, then lowest rating, then
    problem ID) and the slot order are part of the frozen selection rule and must
    not drift between the preflight draft and the formal checklist.
    """
    # Bipartite maximum matching: two slots per cell, one slot per unique problem.
    cells = [(topic.value, band.value) for topic in Topic for band in RatingBand]
    choices = {
        cell: sorted(
            (
                row
                for row in candidates
                if row["rating_band"] == cell[1] and cell[0] in row["possible_topics"]
            ),
            key=lambda row: (len(row["possible_topics"]), row["rating"], row["problem_id"]),
        )
        for cell in cells
    }
    slots = [(topic, band, slot) for topic, band in cells for slot in range(2)]
    owner: dict[str, tuple[str, str, int]] = {}

    def match(slot: tuple[str, str, int], seen: set[str]) -> bool:
        for row in choices[slot[:2]]:
            pid = str(row["problem_id"])
            if pid in seen:
                continue
            seen.add(pid)
            if pid not in owner or match(owner[pid], seen):
                owner[pid] = slot
                return True
        return False

    for slot in sorted(slots, key=lambda slot: (len(choices[slot[:2]]), slot)):
        match(slot, set())
    assignments = [
        {"problem_id": pid, "proposed_topic": slot[0], "rating_band": slot[1]}
        for pid, slot in sorted(owner.items(), key=lambda pair: (pair[1], pair[0]))
    ]
    quota_cells = []
    for topic, band in cells:
        assigned = sum(slot[:2] == (topic, band) for slot in owner.values())
        quota_cells.append(
            {
                "topic": topic,
                "rating_band": band,
                "required": 2,
                "candidate_count": len(choices[(topic, band)]),
                "assigned_count": assigned,
                "shortfall": 2 - assigned,
            }
        )
    return assignments, quota_cells


def prepare(
    *,
    paths: Mapping[str, Path],
    urls: Mapping[str, str],
    data_format: DatasetFormat,
    output_root: Path,
) -> dict[str, str]:
    """Hash actual source bytes and create immutable drafts; URLs are declared only."""
    snapshots = {
        split: read_trusted_file(
            paths[split],
            logical_id=canonical_raw_split_logical_id(split),
            max_bytes=_MAX_RAW_BYTES,
        )
        for split in SPLITS
    }
    version = "preflight-v1-memory-floor"
    if data_format is DatasetFormat.PARQUET:
        version += "-pyarrow-" + importlib.metadata.version("pyarrow")
    manifest = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=tuple(
            AcquisitionAsset(
                split=split,
                url=urls[split],
                byte_length=snapshots[split].byte_length,
                sha256=snapshots[split].sha256,
                license="CC-BY-4.0; third-party materials may have separate terms",
                attribution="Google DeepMind CodeContests; Codeforces problem materials",
            )
            for split in SPLITS
        ),
        converter=ConversionTool(name=f"hy3-codecontests-{data_format.value}", version=version),
        third_party_terms_acknowledged=True,
    )
    validation = validate_acquired_assets(manifest, paths)
    report = assess_rows(
        {
            split: _load_rows(
                snapshots[split].contents,
                source_label=snapshots[split].logical_id,
                data_format=data_format,
                converter_argv=None,
            )
            for split in SPLITS
        }
    )
    report.update(
        {
            "acquisition_manifest_hash": manifest.content_hash,
            "acquisition_validation_hash": validation.content_hash,
            "publisher_verified": False,
            "source_verification": "User-supplied local bytes; URLs are declared provenance. "
            "No independent publisher hash or upstream revision verification performed.",
            "converter": manifest.converter.model_dump(mode="json"),
        }
    )
    proposed = {row["problem_id"]: row["proposed_topic"] for row in report["proposed_assignment"]}
    drafts = {
        "schema_version": "1.2",
        "kind": "codecontests_human_review_draft",
        "formal_eligibility": False,
        "preflight_hash": sha256_json(report),
        "instructions": "These are unsigned drafts, not CandidateReview artifacts. "
        "A human must inspect checker semantics and approve the primary topic, then supply "
        "their own reviewer identity and timezone-aware timestamp before formal conversion.",
        "items": [
            {
                "problem_id": row["problem_id"],
                "split": row["split"],
                "row_number": row["row_number"],
                "raw_row_hash": row["raw_row_hash"],
                "evidence_url": row["source_url"],
                "possible_topics": row["possible_topics"],
                "checker_warnings": row["checker_warnings"],
                "proposed_topic": proposed.get(row["problem_id"]),
                "proposed_for_selection": row["problem_id"] in proposed,
                "checker_reviewed": False,
                "checker_kind": "unreviewed",
                "primary_topic": None,
                "primary_topic_reviewed": False,
                "reviewer": None,
                "reviewed_at": None,
                "notes": "",
            }
            for row in report["rows"]
            if row["candidate"]
        ],
    }
    store = ArtifactStore(output_root)
    artifacts = {
        "acquisition": manifest.model_dump(mode="json"),
        "acquisition-validation": validation.model_dump(mode="json"),
        "data-preflight": report,
        "human-review-draft": drafts,
    }
    result = {kind: str(store.create(kind, payload).path) for kind, payload in artifacts.items()}
    index = {
        "schema_version": "1.2",
        "kind": "data_preflight_index",
        "formal_eligibility": False,
        "artifacts": result,
    }
    result["index"] = str(store.create("index", index).path)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hy3 AlgoTrace Lab: personal activity project, not an official Tencent "
        "release. Create non-formal CodeContests review drafts."
    )
    parser.add_argument("--validation", required=True, type=Path)
    parser.add_argument("--test", required=True, type=Path)
    parser.add_argument("--validation-url", required=True)
    parser.add_argument("--test-url", required=True)
    parser.add_argument("--format", required=True, choices=("json", "jsonl", "parquet"))
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--acknowledge-third-party-terms", action="store_true", required=True)
    args = parser.parse_args(argv)
    try:
        result = prepare(
            paths={"validation": args.validation, "test": args.test},
            urls={"validation": args.validation_url, "test": args.test_url},
            data_format=DatasetFormat(args.format),
            output_root=args.output_root,
        )
    except (
        DatasetDataError,
        ArtifactStoreError,
        OSError,
        ValueError,
        TypeError,
        ValidationError,
        importlib.metadata.PackageNotFoundError,
    ):
        print(
            "error: preflight failed; verify inputs and use a new output directory", file=sys.stderr
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
