"""CodeContests ingestion, deterministic 5×3×2 selection, and frozen manifests."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hy3_algotrace.artifacts import (
    ArtifactExistsError,
    ArtifactStore,
    ArtifactStoreError,
    canonical_json_bytes,
    sha256_json,
)
from hy3_algotrace.catalog import (
    BundleValidationError,
    PilotBundle,
    ProblemBundle,
    ProblemCatalog,
    canonical_codeforces_url,
    determine_primary_topic,
    problem_content_hash,
    validate_problem_record,
)
from hy3_algotrace.contracts import ProblemRecord, RatingBand, TestCase, Topic


class CodeContestsImportError(ValueError):
    """Raised when a CodeContests source or frozen formal selection is invalid."""


class FrozenBundleHashes(BaseModel):
    """Canonical component hashes for one complete formal bundle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    problem_id: str = Field(min_length=1)
    problem_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    oracle_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    gold_trace_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reference_cpp_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    public_tests_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    hidden_tests_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    generated_tests_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    aggregate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class FrozenSelectionManifest(BaseModel):
    """Strict immutable manifest binding all data consumed by a formal run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["formal_codecontests_selection"] = "formal_codecontests_selection"
    bundles: tuple[FrozenBundleHashes, ...] = Field(min_length=30, max_length=30)
    aggregate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("bundles")
    @classmethod
    def validate_unique_ids(
        cls, entries: tuple[FrozenBundleHashes, ...]
    ) -> tuple[FrozenBundleHashes, ...]:
        if len({entry.problem_id for entry in entries}) != len(entries):
            raise ValueError("manifest bundle problem IDs must be unique")
        return entries


def load_codecontests_json(
    path: Path | str, *, split: Literal["validation", "test"]
) -> tuple[ProblemRecord, ...]:
    """Map real CodeContests JSON/JSONL records using explicit split context."""

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
            records.append(_map_codecontests_record(item, split=split))
        except (BundleValidationError, TypeError, ValueError) as error:
            raise CodeContestsImportError(f"record {index} is invalid: {error}") from error
    return tuple(records)


def select_formal_problems(records: Iterable[ProblemRecord]) -> tuple[ProblemRecord, ...]:
    """Pick exactly two deterministic records for every topic/rating cell."""

    buckets: dict[tuple[Topic, RatingBand], list[ProblemRecord]] = defaultdict(list)
    known_ids: set[str] = set()
    for record in records:
        try:
            validate_problem_record(record)
        except BundleValidationError as error:
            raise CodeContestsImportError(
                f"formal selection rejected {record.problem_id}: {error}"
            ) from error
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


def select_formal_bundles(
    bundles: Iterable[ProblemBundle | PilotBundle],
) -> tuple[ProblemBundle, ...]:
    """Select complete formal bundles and reject every synthetic pilot envelope."""

    materialized = tuple(bundles)
    if any(not item.formal_selection_eligible for item in materialized):
        raise CodeContestsImportError("pilot bundles are not eligible for formal selection")
    formal = tuple(item for item in materialized if isinstance(item, ProblemBundle))
    if len(formal) != len(materialized):
        raise CodeContestsImportError("formal selection requires complete formal bundles")
    selected_records = select_formal_problems(bundle.record for bundle in formal)
    by_id = {bundle.record.problem_id: bundle for bundle in formal}
    return tuple(by_id[record.problem_id] for record in selected_records)


def build_selection_manifest(bundles: Iterable[ProblemBundle]) -> FrozenSelectionManifest:
    """Build a strict in-memory manifest over all formal bundle components."""

    selected = select_formal_bundles(tuple(bundles))
    entries = tuple(_bundle_hashes(bundle) for bundle in selected)
    aggregate_hash = sha256_json([entry.model_dump(mode="json") for entry in entries])
    return FrozenSelectionManifest(bundles=entries, aggregate_hash=aggregate_hash)


def validate_selection_manifest(
    manifest: Mapping[str, Any], bundles: Iterable[ProblemBundle]
) -> tuple[ProblemBundle, ...]:
    """Fail if extras or any complete-bundle component differs from the freeze."""

    try:
        frozen = FrozenSelectionManifest.model_validate(manifest)
    except ValidationError as error:
        raise CodeContestsImportError(f"selection manifest invalid: {error}") from error
    selected = select_formal_bundles(tuple(bundles))
    expected_entries = tuple(_bundle_hashes(bundle) for bundle in selected)
    expected_aggregate = sha256_json(
        [entry.model_dump(mode="json") for entry in expected_entries]
    )
    if frozen.bundles != expected_entries:
        raise CodeContestsImportError(
            "selection manifest component hash does not match frozen bundle"
        )
    if frozen.aggregate_hash != expected_aggregate:
        raise CodeContestsImportError(
            "selection manifest aggregate hash does not match frozen bundles"
        )
    return selected


def write_selection_manifest(bundles: Sequence[ProblemBundle], output_dir: Path | str) -> Path:
    """Atomically create a hash-addressed complete-bundle frozen manifest."""

    manifest = build_selection_manifest(bundles)
    created = ArtifactStore(output_dir).create("selection", manifest.model_dump(mode="json"))
    return Path(output_dir) / created.path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the stdlib CLI; create-only conflicts have a stable nonzero result."""

    parser = argparse.ArgumentParser(
        description="Validate CodeContests records and freeze complete formal bundles."
    )
    parser.add_argument("input", type=Path, help="CodeContests JSON array/object or JSONL input")
    parser.add_argument("output", type=Path, help="Directory for immutable manifest artifacts")
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        imported = load_codecontests_json(arguments.input, split=arguments.split)
        selected = select_formal_problems(imported)
        catalog = ProblemCatalog.from_directory(arguments.catalog_root)
        bundles = tuple(catalog.get_bundle(record.problem_id) for record in selected)
        if any(
            bundle.record.model_dump(mode="json") != record.model_dump(mode="json")
            for record, bundle in zip(selected, bundles, strict=True)
        ):
            raise CodeContestsImportError(
                "catalog bundle record does not match imported record"
            )
        manifest = write_selection_manifest(bundles, arguments.output)
        print(manifest)
        return 0
    except ArtifactExistsError:
        print("error: immutable selection manifest already exists", file=sys.stderr)
        return 1
    except (ArtifactStoreError, OSError, KeyError, TypeError, ValueError):
        print("error: unable to validate and freeze selection", file=sys.stderr)
        return 1


def _map_codecontests_record(
    raw: Mapping[str, Any], *, split: Literal["validation", "test"]
) -> ProblemRecord:
    if "content_hash" in raw and "problem_id" in raw:
        record = ProblemRecord.model_validate(raw)
        if canonical_json_bytes(raw) != canonical_json_bytes(
            record.model_dump(mode="json")
        ):
            raise ValueError(
                "disk ProblemRecord must use strict JSON types and explicit canonical fields"
            )
        if record.source_split != split:
            raise BundleValidationError(
                "record source_split does not match explicit import context"
            )
        validate_problem_record(record)
        return record
    contest_id = _positive_int(raw.get("cf_contest_id"), "cf_contest_id")
    index = raw.get("cf_index")
    if not isinstance(index, str) or not index.strip():
        raise ValueError("cf_index is required")
    index = index.strip()
    source_url = canonical_codeforces_url(contest_id, index)
    supplied_url = raw.get("source_url")
    if supplied_url is not None and supplied_url != source_url:
        raise ValueError("Codeforces URL does not match cf_contest_id/cf_index")
    name = raw.get("name")
    description = raw.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description is required")
    if raw.get("is_description_translated", False) is not False:
        raise ValueError("translated CodeContests descriptions are not eligible")
    source = raw.get("source")
    if source != "CODEFORCES" and not (
        isinstance(source, int) and not isinstance(source, bool) and source == 2
    ):
        raise ValueError("source must be the official CODEFORCES enum value")
    if raw.get("input_file", "") != "" or raw.get("output_file", "") != "":
        raise ValueError("Codeforces records must use standard stdin/stdout")
    tags = raw.get("cf_tags", raw.get("tags"))
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ValueError("cf_tags is required")
    topic = determine_primary_topic(tags)
    time_limit_ms = _protobuf_duration_ms(raw.get("time_limit"))
    memory_bytes = _positive_int(raw.get("memory_limit_bytes"), "memory_limit_bytes")
    # Official Parquet records include decimal-byte limits such as 256_000_000.
    # The existing Judge contract uses integral MiB. Floor rather than round up:
    # execution must never be granted more memory than the acquired byte limit.
    memory_mib = memory_bytes // (1024 * 1024)
    if memory_mib == 0:
        raise ValueError("memory_limit_bytes must permit at least one MiB")
    public_tests = _map_tests(raw.get("public_tests", []), "public")
    hidden_tests = _map_tests(raw.get("private_tests"), "hidden")
    generated_tests = _map_tests(raw.get("generated_tests", []), "generated")
    provisional = ProblemRecord(
        problem_id=f"cf-{contest_id}-{index.casefold()}",
        title=name.strip(),
        statement_en=description.strip(),
        source_url=source_url,
        attribution=(
            f"Codeforces problem {contest_id}{index}; metadata imported from "
            f"CodeContests {split} split."
        ),
        cf_contest_id=contest_id,
        cf_index=index,
        cf_tags=tuple(tags),
        source_split=split,
        topic=topic,
        rating=_positive_int(raw.get("cf_rating"), "cf_rating"),
        time_limit_ms=time_limit_ms,
        memory_limit_mb=memory_mib,
        public_tests=public_tests,
        hidden_tests=hidden_tests,
        generated_tests=generated_tests,
        content_hash="0" * 64,
    )
    record = provisional.model_copy(update={"content_hash": problem_content_hash(provisional)})
    validate_problem_record(record)
    return record


def _map_tests(value: Any, prefix: str) -> tuple[TestCase, ...]:
    if value is None:
        if prefix == "hidden":
            raise ValueError("private_tests must be non-empty")
        return ()
    if isinstance(value, Mapping):
        inputs = value.get("input")
        outputs = value.get("output")
        if isinstance(inputs, list) and isinstance(outputs, list) and len(inputs) == len(outputs):
            value = [{"input": item, "output": outputs[index]} for index, item in enumerate(inputs)]
    if not isinstance(value, list):
        raise ValueError(f"{prefix} tests must be a list")
    result: list[TestCase] = []
    for number, test in enumerate(value, start=1):
        if not isinstance(test, Mapping):
            raise ValueError(f"{prefix} test {number} must be an object")
        input_data = test.get("input", test.get("input_data"))
        expected_output = test.get("output", test.get("expected_output"))
        if not isinstance(input_data, str) or not isinstance(expected_output, str):
            raise ValueError(f"{prefix} test {number} requires string input/output")
        result.append(TestCase(
            test_id=f"{prefix}-{number}",
            input_data=input_data,
            expected_output=expected_output,
        ))
    return tuple(result)


def _bundle_hashes(bundle: ProblemBundle) -> FrozenBundleHashes:
    record = bundle.record
    components: dict[str, str] = {
        "problem_id": record.problem_id,
        "problem_hash": sha256_json(record.model_dump(mode="json")),
        "oracle_hash": sha256_json(bundle.oracle.model_dump(mode="json")),
        "gold_trace_hash": sha256_json(bundle.gold_trace.model_dump(mode="json")),
        "reference_cpp_hash": sha256_json(bundle.reference_cpp),
        "public_tests_hash": sha256_json(
            [test.model_dump(mode="json") for test in record.public_tests]
        ),
        "hidden_tests_hash": sha256_json(
            [test.model_dump(mode="json") for test in record.hidden_tests]
        ),
        "generated_tests_hash": sha256_json(
            [test.model_dump(mode="json") for test in record.generated_tests]
        ),
    }
    aggregate_input = dict(components)
    components["aggregate_hash"] = sha256_json(aggregate_input)
    return FrozenBundleHashes.model_validate(components)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _protobuf_duration_ms(value: Any) -> int:
    if not isinstance(value, Mapping) or set(value) != {"seconds", "nanos"}:
        raise ValueError("time_limit must contain exactly seconds and nanos")
    raw_seconds = value["seconds"]
    if isinstance(raw_seconds, str):
        if not raw_seconds.isascii() or not raw_seconds.isdigit():
            raise ValueError("time_limit seconds must be a non-negative integer")
        seconds = int(raw_seconds)
    elif isinstance(raw_seconds, int) and not isinstance(raw_seconds, bool):
        seconds = raw_seconds
    else:
        raise ValueError("time_limit seconds must be a non-negative integer")
    nanos = value["nanos"]
    if isinstance(nanos, bool) or not isinstance(nanos, int):
        raise ValueError("time_limit nanos must be an integer")
    if not 0 <= seconds <= 315_576_000_000:
        raise ValueError("time_limit seconds are outside the protobuf Duration range")
    if not 0 <= nanos <= 999_999_999:
        raise ValueError("time_limit nanos are outside the protobuf Duration range")
    total_nanos = seconds * 1_000_000_000 + nanos
    if total_nanos <= 0:
        raise ValueError("time_limit must be strictly positive")
    milliseconds, remainder = divmod(total_nanos, 1_000_000)
    if remainder:
        milliseconds += 1
    return milliseconds


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
