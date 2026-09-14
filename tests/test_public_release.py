from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hy3_algotrace.public_release import (
    PublicReleaseError,
    export_public_evaluation,
    validate_public_evaluation,
)


def _write_sample(root: Path, relative: str, contents: str) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    data = contents.encode("utf-8")
    path.write_bytes(data)
    return {
        "path": relative,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "media_type": "application/json" if relative.endswith(".json") else "text/x-c++src",
        "provenance": "project_authored",
    }


def _fixture_inputs(tmp_path: Path) -> tuple[Path, Path]:
    authored = tmp_path / "authored"
    trace = _write_sample(
        authored,
        "corpus/gold/cf-100-a-gold.json",
        json.dumps(
            {
                "schema_version": "1.2",
                "trace_id": "cf-100-a-gold",
                "problem_id": "cf-100-a",
                "language": "cpp17",
                "problem_understanding": "Read one value.",
                "algorithm": "Return the value.",
                "correctness_argument": "The returned value is the requested value.",
                "time_complexity": "O(1)",
                "space_complexity": "O(1)",
                "edge_cases": ["zero"],
                "steps": [
                    {
                        "schema_version": "1.2",
                        "step_id": "s1",
                        "step_number": 1,
                        "stage": "algorithm_design",
                        "claim": "Return the value.",
                        "rationale": "No transformation is needed.",
                        "depends_on": [],
                        "status": "correct",
                    }
                ],
                "code": "int main() { return 0; }\n",
            }
        ),
    )
    source = _write_sample(
        authored,
        "corpus/gold/cf-100-a-gold.cpp",
        "int main() { return 0; }\n",
    )
    corpus = {
        "schema_version": "1.2",
        "kind": "algotrace_formal_corpus",
        "selection_manifest_hash": "a" * 64,
        "bundle_manifest_hash": "b" * 64,
        "status": "pending_credentials",
        "samples": [
            {
                "sample_id": "cf-100-a-gold",
                "problem_id": "cf-100-a",
                "kind": "gold",
                "trace": trace,
                "cpp_source": source,
                "final_expected_correct": True,
                "primary_error": None,
                "first_error_step_id": None,
            }
        ],
        "content_hash": "c" * 64,
    }
    (authored / "corpus-pending.json").write_text(json.dumps(corpus), encoding="utf-8")
    quota = tmp_path / "quota.json"
    quota.write_text(
        json.dumps(
            {
                "schema_version": "1.2",
                "kind": "codecontests_eligibility_quota",
                "status": "fulfilled",
                "cells": [
                    {
                        "topic": "greedy",
                        "rating_band": "1200-1500",
                        "required": 1,
                        "eligible_count": 1,
                        "eligible_problem_ids": ["cf-100-a"],
                        "fulfilled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return authored, quota


def test_public_export_copies_only_manifested_samples_and_builds_path_free_index(
    tmp_path: Path,
) -> None:
    authored, quota = _fixture_inputs(tmp_path)
    private = authored / "private/problem-records/cf-100-a.json"
    private.parent.mkdir(parents=True)
    private.write_text('{"statement":"secret"}', encoding="utf-8")
    oracle = authored / "problems/cf-100-a/oracle.json"
    oracle.parent.mkdir(parents=True)
    oracle.write_text('{"oracle":"secret"}', encoding="utf-8")

    destination = tmp_path / "public"
    manifest = export_public_evaluation(
        authored_root=authored,
        quota_path=quota,
        output_root=destination,
        expected_counts={"gold": 1},
    )

    assert (destination / "corpus/gold/cf-100-a-gold.cpp").is_file()
    assert (destination / "corpus/gold/cf-100-a-gold.json").is_file()
    assert not (destination / "private").exists()
    assert not (destination / "problems").exists()
    persisted = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    assert persisted == manifest
    assert persisted["counts"] == {"gold": 1}
    assert persisted["problems"] == [
        {
            "problem_id": "cf-100-a",
            "rating_band": "1200-1500",
            "sample_ids": ["cf-100-a-gold"],
            "source_url": "https://codeforces.com/problemset/problem/100/A",
            "topic": "greedy",
        }
    ]
    assert str(tmp_path) not in (destination / "manifest.json").read_text(encoding="utf-8")
    assert validate_public_evaluation(destination) == {
        "artifact_count": 2,
        "content_hash": persisted["content_hash"],
        "problem_count": 1,
        "sample_count": 1,
        "valid": True,
    }


def test_public_export_is_create_only_and_rejects_non_corpus_paths(tmp_path: Path) -> None:
    authored, quota = _fixture_inputs(tmp_path)
    destination = tmp_path / "public"
    export_public_evaluation(
        authored_root=authored,
        quota_path=quota,
        output_root=destination,
        expected_counts={"gold": 1},
    )
    with pytest.raises(PublicReleaseError, match="already exists"):
        export_public_evaluation(
            authored_root=authored,
            quota_path=quota,
            output_root=destination,
            expected_counts={"gold": 1},
        )

    corpus_path = authored / "corpus-pending.json"
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["samples"][0]["trace"]["path"] = "problems/cf-100-a/oracle.json"
    corpus_path.write_text(json.dumps(corpus), encoding="utf-8")
    with pytest.raises(PublicReleaseError, match="public corpus path"):
        export_public_evaluation(
            authored_root=authored,
            quota_path=quota,
            output_root=tmp_path / "public-2",
            expected_counts={"gold": 1},
        )


def test_public_validator_detects_trace_or_source_tampering(tmp_path: Path) -> None:
    authored, quota = _fixture_inputs(tmp_path)
    destination = tmp_path / "public"
    export_public_evaluation(
        authored_root=authored,
        quota_path=quota,
        output_root=destination,
        expected_counts={"gold": 1},
    )
    (destination / "corpus/gold/cf-100-a-gold.cpp").write_text(
        "int main() { return 1; }\n", encoding="utf-8"
    )

    with pytest.raises(PublicReleaseError, match="hash"):
        validate_public_evaluation(destination)
