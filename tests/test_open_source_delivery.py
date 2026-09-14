from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from hy3_algotrace.public_release import validate_public_evaluation

ROOT = Path(__file__).parents[1]


def test_checked_in_public_evaluation_and_results_use_the_same_literal_counts() -> None:
    validation = validate_public_evaluation(ROOT / "evaluation/materials")
    manifest = json.loads((ROOT / "evaluation/materials/manifest.json").read_text())
    results = json.loads((ROOT / "evaluation/results/current-results.json").read_text())
    validity = json.loads((ROOT / "evaluation/validation/status.json").read_text())

    assert validation == {
        "artifact_count": 210,
        "content_hash": "ba71264866bc57651e253e89c7d97b1c27b5bd0a993b066fce987832de6d1bcc",
        "problem_count": 30,
        "sample_count": 105,
        "valid": True,
    }
    controlled = results["controlled_corpus_validation"]
    assert controlled["counts"] == manifest["counts"]
    assert controlled["taxonomy_distribution"] == manifest["taxonomy_distribution"]
    assert controlled["samples"] == len(manifest["samples"])
    assert controlled["passed_by_expected_semantics"] == 105
    assert controlled["observed_tests"] == 22839
    assert results["formal"] is False
    assert validity["human_audit_records"] == 0
    for metric in (
        "exact_localization_accuracy",
        "within_one_step_localization_accuracy",
        "flagged_false_positive_rate",
    ):
        assert validity[metric]["denominator"] == 0
        assert validity[metric]["not_evaluable"] is True
        assert validity[metric]["value"] is None


def test_checked_in_demo_is_under_two_minutes() -> None:
    with Image.open(ROOT / "docs/assets/demo.gif") as demo:
        durations = []
        for frame in range(demo.n_frames):
            demo.seek(frame)
            durations.append(demo.info["duration"])
    assert len(durations) == 6
    assert sum(durations) == 36_000
    assert sum(durations) < 120_000
