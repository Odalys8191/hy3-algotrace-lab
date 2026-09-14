from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from hy3_algotrace.demo_media import build_demo_gif


def test_demo_gif_is_create_only_under_two_minutes_and_uses_safe_summary(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    result.write_text(
        json.dumps(
            {
                "sample_id": "natural-1",
                "primary_review_agreement": True,
                "arbitration_used": False,
                "trace": {
                    "problem_id": "cf-100-a",
                    "algorithm": "Read x and output x + 1.",
                    "code": "int main() { return 0; }\n",
                    "steps": [{"step_id": "s1", "stage": "algorithm_design", "status": "correct"}],
                },
                "judge": {
                    "compile_status": "ac",
                    "verdict": "ac",
                    "tests": [
                        {
                            "test_id": "hidden-secret-name",
                            "status": "ac",
                            "counterexample_input": "must-not-render",
                        }
                    ],
                },
                "audit": {
                    "final_correct": True,
                    "process_valid": True,
                    "process_score": 100.0,
                    "first_material_error_step_id": None,
                    "final_error_taxonomy": None,
                    "needs_human_review": False,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "demo.gif"

    stats = build_demo_gif(result_path=result, output_path=output, title="Add One")

    assert stats.frame_count == 6
    assert stats.duration_seconds < 120
    assert output.is_file()
    assert b"must-not-render" not in output.read_bytes()
    with Image.open(output) as image:
        assert image.n_frames == 6
        durations = []
        for frame in range(image.n_frames):
            image.seek(frame)
            durations.append(image.info["duration"])
    assert sum(durations) == stats.duration_seconds * 1000
