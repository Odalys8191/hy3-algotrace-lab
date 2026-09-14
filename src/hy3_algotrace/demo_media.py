"""Build a short, redacted GIF walkthrough from one completed public result."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import textwrap
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


class DemoMediaError(RuntimeError):
    """Raised when a demo source is incomplete or the output is unsafe."""


@dataclass(frozen=True, slots=True)
class DemoGifStats:
    frame_count: int
    duration_seconds: int
    width: int
    height: int


_WIDTH = 1280
_HEIGHT = 720
_FRAME_DURATION_MS = 6000
_BACKGROUND = "#08111f"
_PANEL = "#111d2f"
_PANEL_LIGHT = "#17263c"
_TEXT = "#f3f7ff"
_MUTED = "#9eb0ca"
_CYAN = "#4ed8d2"
_GREEN = "#6ee7a8"
_AMBER = "#f6c86b"


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_header(draw: ImageDraw.ImageDraw, *, step: int, label: str) -> None:
    draw.text((58, 43), "HY3 ALGOTRACE LAB", fill=_CYAN, font=_font(25, bold=True))
    draw.text((58, 83), label, fill=_TEXT, font=_font(42, bold=True))
    draw.text((1033, 50), "REAL MVP", fill=_GREEN, font=_font(20, bold=True))
    draw.text((1005, 82), "NON-FORMAL", fill=_AMBER, font=_font(18, bold=True))
    for index in range(6):
        color = _CYAN if index <= step else "#2b3b52"
        draw.rounded_rectangle((58 + index * 94, 142, 132 + index * 94, 151), 5, fill=color)


def _draw_card(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    lines: Sequence[str],
    *,
    accent: str = _CYAN,
) -> None:
    draw.rounded_rectangle(box, radius=22, fill=_PANEL, outline="#2b3b52", width=2)
    x1, y1, _, _ = box
    draw.rounded_rectangle((x1, y1, x1 + 8, box[3]), radius=4, fill=accent)
    draw.text((x1 + 30, y1 + 24), title, fill=accent, font=_font(24, bold=True))
    y = y1 + 70
    for line in lines:
        for wrapped in textwrap.wrap(str(line), width=66) or [""]:
            draw.text((x1 + 30, y), wrapped, fill=_TEXT, font=_font(23))
            y += 34
        y += 5


def _new_frame(step: int, label: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (_WIDTH, _HEIGHT), _BACKGROUND)
    draw = ImageDraw.Draw(image)
    _draw_header(draw, step=step, label=label)
    draw.text(
        (58, 678),
        "Public summary only - no credentials, prompts, hidden tests, or oracle content",
        fill=_MUTED,
        font=_font(17),
    )
    return image, draw


def _load_result(path: Path) -> tuple[dict[str, Any], str]:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DemoMediaError("cannot read demo result") from error
    if not isinstance(value, dict):
        raise DemoMediaError("demo result must be a JSON object")
    for field in ("sample_id", "trace", "judge", "audit"):
        if field not in value:
            raise DemoMediaError("demo result is incomplete")
    if not all(isinstance(value[field], dict) for field in ("trace", "judge", "audit")):
        raise DemoMediaError("demo result has invalid sections")
    return value, hashlib.sha256(data).hexdigest()


def build_demo_gif(*, result_path: Path, output_path: Path, title: str) -> DemoGifStats:
    """Render six safe summary frames without rendering per-test IDs or test content."""

    if output_path.exists():
        raise DemoMediaError("demo output already exists")
    result, result_hash = _load_result(result_path)
    trace: Mapping[str, Any] = result["trace"]
    judge: Mapping[str, Any] = result["judge"]
    audit: Mapping[str, Any] = result["audit"]
    steps = trace.get("steps")
    tests = judge.get("tests")
    if not isinstance(steps, list) or not isinstance(tests, list):
        raise DemoMediaError("demo result has no trace or Judge rows")
    test_statuses = Counter(
        row.get("status")
        for row in tests
        if isinstance(row, dict) and isinstance(row.get("status"), str)
    )
    step_statuses = Counter(
        row.get("status")
        for row in steps
        if isinstance(row, dict) and isinstance(row.get("status"), str)
    )
    algorithm = str(trace.get("algorithm", ""))
    code = str(trace.get("code", ""))
    problem_id = str(trace.get("problem_id", "unknown"))
    sample_id = str(result.get("sample_id", "unknown"))

    frames: list[Image.Image] = []
    image, draw = _new_frame(0, "One complete solve-and-audit run")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "Run context",
        (
            f"Problem  {problem_id.upper()}  /  {title}",
            "Mode     Hy3 generation -> C++17 Judge -> dual process review",
            f"Sample   {sample_id}",
            "Evidence Real TokenHub/GA hy3 MVP artifact; formal=false",
        ),
    )
    frames.append(image)

    image, draw = _new_frame(1, "1. Problem selected")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "Public task boundary",
        (
            title,
            f"Problem ID: {problem_id}",
            "Only the public statement is model-visible.",
            "Hidden tests and oracle facts stay behind the API boundary.",
        ),
        accent=_AMBER,
    )
    frames.append(image)

    image, draw = _new_frame(2, "2. Hy3 generates a structured solution")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "SolutionTrace",
        (
            f"Algorithm: {algorithm}",
            f"Reasoning steps: {len(steps)}  |  C++17 lines: {len(code.splitlines())}",
            "Every step has an ID, stage, dependencies, claim, rationale, and status.",
        ),
    )
    frames.append(image)

    image, draw = _new_frame(3, "3. Sandboxed C++17 Judge")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "Execution evidence",
        (
            f"Compile: {str(judge.get('compile_status', 'unknown')).upper()}",
            f"Verdict: {str(judge.get('verdict', 'unknown')).upper()}",
            f"Tests: {len(tests)} total  |  AC: {test_statuses.get('ac', 0)}",
            "Per-test inputs and expected outputs are intentionally not shown.",
        ),
        accent=_GREEN,
    )
    frames.append(image)

    image, draw = _new_frame(4, "4. Independent process review")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "Trace audit",
        (
            "Reviewers: logic-reviewer + adversarial-reviewer",
            f"Primary agreement: {result.get('primary_review_agreement')}",
            f"Arbitration used: {result.get('arbitration_used')}",
            "Step labels: "
            + ", ".join(f"{key}={value}" for key, value in sorted(step_statuses.items())),
        ),
        accent="#b69cff",
    )
    frames.append(image)

    image, draw = _new_frame(5, "5. Fused public result")
    _draw_card(
        draw,
        (58, 190, 1222, 620),
        "Decision",
        (
            f"Final answer correct: {audit.get('final_correct')}",
            f"Process valid: {audit.get('process_valid')}  |  Score: {audit.get('process_score')}",
            "First material error: " + str(audit.get("first_material_error_step_id") or "none"),
            f"Needs human review: {audit.get('needs_human_review')}",
            f"Immutable source SHA-256: {result_hash[:16]}...",
        ),
        accent=_GREEN,
    )
    frames.append(image)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        frames[0].save(
            temporary,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=_FRAME_DURATION_MS,
            loop=0,
            optimize=False,
        )
        try:
            os.link(temporary, output_path)
        except FileExistsError as error:
            raise DemoMediaError("demo output already exists") from error
    finally:
        if temporary.exists():
            temporary.unlink()
    return DemoGifStats(
        frame_count=len(frames),
        duration_seconds=len(frames) * _FRAME_DURATION_MS // 1000,
        width=_WIDTH,
        height=_HEIGHT,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a redacted AlgoTrace demo GIF.")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", required=True)
    arguments = parser.parse_args(argv)
    stats = build_demo_gif(
        result_path=arguments.result,
        output_path=arguments.output,
        title=arguments.title,
    )
    print(json.dumps(asdict(stats), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
