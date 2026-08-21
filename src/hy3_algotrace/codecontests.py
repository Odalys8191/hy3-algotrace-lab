"""CodeContests JSON/JSONL ingestion and deterministic formal selection."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hy3_algotrace.artifacts import ArtifactStore
from hy3_algotrace.catalog import BundleValidationError, validate_problem_record
from hy3_algotrace.contracts import ProblemRecord, RatingBand, Topic


class CodeContestsImportError(ValueError):
    """Raised when a CodeContests source or formal selection is invalid."""


def load_codecontests_json(path: Path | str) -> tuple[ProblemRecord, ...]:
    """Load ProblemRecord-shaped data from a JSON array/object or JSONL file."""

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as error:
        raise CodeContestsImportError(f"cannot read CodeContests input: {source}") from error
    try:
        raw_items = _decode_items(source, text)
    except (json.JSONDecodeError, CodeContestsImportError) as error:
        raise CodeContestsImportError(f"invalid CodeContests input: {source}: {error}") from error
    records: list[ProblemRecord] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, Mapping):
            raise CodeContestsImportError(f"record {index} is not a JSON object")
        try:
            record = ProblemRecord.model_validate(item)
            validate_problem_record(record)
        except (BundleValidationError, ValueError) as error:
            raise CodeContestsImportError(f"record {index} is invalid: {error}") from error
        records.append(record)
    return tuple(records)


def select_formal_problems(records: Iterable[ProblemRecord]) -> tuple[ProblemRecord, ...]:
    """Pick exactly two deterministic records for every topic/rating cell."""

    buckets: dict[tuple[Topic, RatingBand], list[ProblemRecord]] = defaultdict(list)
    known_ids: set[str] = set()
    for record in records:
        try:
            validate_problem_record(record)
        except BundleValidationError as error:
            message = f"formal selection rejected {record.problem_id}: {error}"
            raise CodeContestsImportError(message) from error
        if record.problem_id in known_ids:
            raise CodeContestsImportError(f"duplicate problem ID: {record.problem_id}")
        known_ids.add(record.problem_id)
        buckets[(record.topic, record.rating_band)].append(record)
    selected: list[ProblemRecord] = []
    for topic in Topic:
        for band in RatingBand:
            candidates = sorted(buckets[(topic, band)], key=lambda item: item.problem_id)
            if len(candidates) < 2:
                raise CodeContestsImportError(
                    f"quota unmet for {topic.value}/{band.value}: need 2, found {len(candidates)}"
                )
            selected.extend(candidates[:2])
    return tuple(selected)


def validate_selection_manifest(
    manifest: Mapping[str, Any], records: Iterable[ProblemRecord]
) -> tuple[ProblemRecord, ...]:
    """Verify that a frozen manifest exactly names the deterministic 5×3×2 selection."""

    if manifest.get("schema_version") != "1.2":
        raise CodeContestsImportError("selection manifest has an unsupported schema version")
    if manifest.get("kind") != "formal_codecontests_selection":
        raise CodeContestsImportError("selection manifest has an unsupported kind")
    selected = select_formal_problems(records)
    expected_ids = [record.problem_id for record in selected]
    expected_hashes = {record.problem_id: record.content_hash for record in selected}
    if manifest.get("problem_ids") != expected_ids:
        raise CodeContestsImportError("selection manifest problem IDs do not match frozen quota")
    if manifest.get("record_hashes") != expected_hashes:
        raise CodeContestsImportError(
            "selection manifest record hashes do not match frozen records"
        )
    return selected


def write_selection_manifest(records: Sequence[ProblemRecord], output_dir: Path | str) -> Path:
    """Create a hash-addressed manifest for a previously validated frozen selection."""

    selected = select_formal_problems(records)
    payload: dict[str, Any] = {
        "schema_version": "1.2",
        "kind": "formal_codecontests_selection",
        "problem_ids": [record.problem_id for record in selected],
        "record_hashes": {record.problem_id: record.content_hash for record in selected},
    }
    created = ArtifactStore(output_dir).create("selection", payload)
    return Path(output_dir) / created.path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the small stdlib CLI without adding a packaging dependency."""

    parser = argparse.ArgumentParser(
        description="Validate and freeze CodeContests formal selections."
    )
    parser.add_argument("input", type=Path, help="ProblemRecord JSON array/object or JSONL input")
    parser.add_argument("output", type=Path, help="Directory for an immutable selection manifest")
    arguments = parser.parse_args(argv)
    try:
        records = load_codecontests_json(arguments.input)
        manifest = write_selection_manifest(records, arguments.output)
    except CodeContestsImportError as error:
        parser.error(str(error))
    print(manifest)
    return 0


def _decode_items(path: Path, text: str) -> list[Any]:
    if path.suffix.casefold() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    value = json.loads(text)
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        problems = value.get("problems")
        if isinstance(problems, list):
            return problems
    raise CodeContestsImportError("JSON input must be an array or an object with a problems array")


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
