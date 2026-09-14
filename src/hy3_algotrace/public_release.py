"""Create a path-free, oracle-free public export of the authored evaluation corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import ValidationError

from .artifacts import canonical_json_bytes, sha256_json
from .contracts import SolutionTrace

EXPECTED_PUBLIC_COUNTS: Mapping[str, int] = {
    "gold": 30,
    "controlled_wrong": 60,
    "paradox": 15,
}


class PublicReleaseError(RuntimeError):
    """Raised when a public export is incomplete, unsafe, or would overwrite data."""


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PublicReleaseError(f"cannot read JSON input: {path.name}") from error
    if not isinstance(value, dict):
        raise PublicReleaseError(f"JSON input must be an object: {path.name}")
    return value


def _public_source_path(authored_root: Path, reference: Mapping[str, Any], kind: str) -> Path:
    raw_path = reference.get("path")
    if not isinstance(raw_path, str):
        raise PublicReleaseError("sample reference path is missing")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:2] != ("corpus", kind)
        or relative.suffix not in {".cpp", ".json"}
    ):
        raise PublicReleaseError("sample reference is not a public corpus path")
    source = authored_root.joinpath(*relative.parts)
    try:
        resolved = source.resolve(strict=True)
        authored_resolved = authored_root.resolve(strict=True)
    except OSError as error:
        raise PublicReleaseError("sample artifact is missing") from error
    if (
        source.is_symlink()
        or not resolved.is_relative_to(authored_resolved)
        or not resolved.is_file()
    ):
        raise PublicReleaseError("sample artifact escapes the authored corpus")
    data = resolved.read_bytes()
    if reference.get("byte_length") != len(data):
        raise PublicReleaseError("sample artifact byte length does not match its manifest")
    if reference.get("sha256") != hashlib.sha256(data).hexdigest():
        raise PublicReleaseError("sample artifact hash does not match its manifest")
    return resolved


def _problem_url(problem_id: str) -> str:
    parts = problem_id.split("-")
    if len(parts) != 3 or parts[0] != "cf" or not parts[1].isdigit() or not parts[2]:
        raise PublicReleaseError("invalid Codeforces problem ID")
    return f"https://codeforces.com/problemset/problem/{parts[1]}/{parts[2].upper()}"


def export_public_evaluation(
    *,
    authored_root: Path,
    quota_path: Path,
    output_root: Path,
    expected_counts: Mapping[str, int] = EXPECTED_PUBLIC_COUNTS,
) -> dict[str, Any]:
    """Export only project-authored traces/code and a safe, self-hashed index."""

    if output_root.exists():
        raise PublicReleaseError("public export destination already exists")
    authored_root = authored_root.resolve(strict=True)
    corpus = _load_object(authored_root / "corpus-pending.json")
    quota = _load_object(quota_path)
    samples = corpus.get("samples")
    cells = quota.get("cells")
    if not isinstance(samples, list) or not isinstance(cells, list):
        raise PublicReleaseError("corpus or quota rows are missing")

    count_by_kind = Counter(sample.get("kind") for sample in samples if isinstance(sample, dict))
    if dict(sorted(count_by_kind.items())) != dict(sorted(expected_counts.items())):
        raise PublicReleaseError("public corpus counts do not match the expected profile")

    assignment: dict[str, tuple[str, str]] = {}
    for cell in cells:
        if not isinstance(cell, dict) or cell.get("fulfilled") is not True:
            raise PublicReleaseError("quota cell is not fulfilled")
        topic = cell.get("topic")
        rating_band = cell.get("rating_band")
        problem_ids = cell.get("eligible_problem_ids")
        if (
            not isinstance(topic, str)
            or not isinstance(rating_band, str)
            or not isinstance(problem_ids, list)
        ):
            raise PublicReleaseError("quota cell metadata is invalid")
        for problem_id in problem_ids:
            if not isinstance(problem_id, str) or problem_id in assignment:
                raise PublicReleaseError("problem-to-quota assignment is invalid")
            assignment[problem_id] = (topic, rating_band)

    validated: list[tuple[Path, PurePosixPath]] = []
    public_samples: list[dict[str, Any]] = []
    samples_by_problem: defaultdict[str, list[str]] = defaultdict(list)
    taxonomy: Counter[str] = Counter()
    for sample in samples:
        if not isinstance(sample, dict):
            raise PublicReleaseError("corpus sample is invalid")
        sample_id = sample.get("sample_id")
        problem_id = sample.get("problem_id")
        kind = sample.get("kind")
        if (
            not isinstance(sample_id, str)
            or not isinstance(problem_id, str)
            or not isinstance(kind, str)
        ):
            raise PublicReleaseError("corpus sample identity is invalid")
        if problem_id not in assignment:
            raise PublicReleaseError("sample problem is absent from the quota assignment")
        trace_ref = sample.get("trace")
        source_ref = sample.get("cpp_source")
        if not isinstance(trace_ref, dict) or not isinstance(source_ref, dict):
            raise PublicReleaseError("sample artifact references are invalid")
        for reference in (trace_ref, source_ref):
            source = _public_source_path(authored_root, reference, kind)
            validated.append((source, PurePosixPath(str(reference["path"]))))
        primary_error = sample.get("primary_error")
        if primary_error is not None:
            if not isinstance(primary_error, str):
                raise PublicReleaseError("sample error taxonomy is invalid")
            taxonomy[primary_error] += 1
        samples_by_problem[problem_id].append(sample_id)
        public_samples.append(
            {
                "cpp_source": {key: source_ref[key] for key in ("byte_length", "path", "sha256")},
                "final_expected_correct": sample.get("final_expected_correct"),
                "first_error_step_id": sample.get("first_error_step_id"),
                "kind": kind,
                "primary_error": primary_error,
                "problem_id": problem_id,
                "sample_id": sample_id,
                "trace": {key: trace_ref[key] for key in ("byte_length", "path", "sha256")},
            }
        )

    if set(samples_by_problem) != set(assignment):
        raise PublicReleaseError("quota problems and corpus problems differ")
    public_problems = [
        {
            "problem_id": problem_id,
            "rating_band": assignment[problem_id][1],
            "sample_ids": sorted(samples_by_problem[problem_id]),
            "source_url": _problem_url(problem_id),
            "topic": assignment[problem_id][0],
        }
        for problem_id in sorted(assignment)
    ]
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "kind": "hy3_algotrace_public_evaluation",
        "source_bundle_manifest_hash": corpus.get("bundle_manifest_hash"),
        "source_corpus_hash": corpus.get("content_hash"),
        "source_selection_manifest_hash": corpus.get("selection_manifest_hash"),
        "counts": dict(sorted(count_by_kind.items())),
        "taxonomy_distribution": dict(sorted(taxonomy.items())),
        "problems": public_problems,
        "samples": sorted(public_samples, key=lambda item: str(item["sample_id"])),
    }
    manifest = payload | {"content_hash": sha256_json(payload)}

    temporary = output_root.with_name(f".{output_root.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.mkdir(parents=True, exist_ok=False)
        seen: set[PurePosixPath] = set()
        for source, relative in validated:
            if relative in seen:
                continue
            seen.add(relative)
            destination = temporary.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        os.rename(temporary, output_root)
    except OSError as error:
        raise PublicReleaseError("could not publish the public evaluation export") from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return manifest


def validate_public_evaluation(root: Path) -> dict[str, object]:
    """Verify the public manifest, every artifact hash, and every trace/source pair."""

    try:
        resolved_root = root.resolve(strict=True)
    except OSError as error:
        raise PublicReleaseError("public evaluation root is missing") from error
    manifest = _load_object(resolved_root / "manifest.json")
    expected_hash = manifest.get("content_hash")
    payload = {key: value for key, value in manifest.items() if key != "content_hash"}
    if not isinstance(expected_hash, str) or sha256_json(payload) != expected_hash:
        raise PublicReleaseError("public manifest hash is invalid")
    samples = manifest.get("samples")
    problems = manifest.get("problems")
    counts = manifest.get("counts")
    if (
        not isinstance(samples, list)
        or not isinstance(problems, list)
        or not isinstance(counts, dict)
    ):
        raise PublicReleaseError("public manifest structure is invalid")
    observed_counts: Counter[str] = Counter()
    referenced: set[PurePosixPath] = set()
    for sample in samples:
        if not isinstance(sample, dict) or not isinstance(sample.get("kind"), str):
            raise PublicReleaseError("public sample row is invalid")
        observed_counts[sample["kind"]] += 1
        artifacts: dict[str, bytes] = {}
        for name in ("trace", "cpp_source"):
            reference = sample.get(name)
            if not isinstance(reference, dict):
                raise PublicReleaseError("public sample artifact reference is invalid")
            relative_value = reference.get("path")
            if not isinstance(relative_value, str):
                raise PublicReleaseError("public sample artifact path is invalid")
            relative = PurePosixPath(relative_value)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative.parts[:2] != ("corpus", sample["kind"])
            ):
                raise PublicReleaseError("public sample artifact path is unsafe")
            path = resolved_root.joinpath(*relative.parts)
            try:
                resolved = path.resolve(strict=True)
                data = resolved.read_bytes()
            except OSError as error:
                raise PublicReleaseError("public sample artifact is missing") from error
            if path.is_symlink() or not resolved.is_relative_to(resolved_root):
                raise PublicReleaseError("public sample artifact escapes the export")
            if reference.get("byte_length") != len(data):
                raise PublicReleaseError("public sample artifact byte length is invalid")
            if reference.get("sha256") != hashlib.sha256(data).hexdigest():
                raise PublicReleaseError("public sample artifact hash is invalid")
            referenced.add(relative)
            artifacts[name] = data
        try:
            trace = SolutionTrace.model_validate_json(artifacts["trace"])
            source = artifacts["cpp_source"].decode("utf-8")
        except (ValidationError, UnicodeError) as error:
            raise PublicReleaseError("public sample schema is invalid") from error
        if trace.trace_id != sample.get("sample_id") or trace.problem_id != sample.get(
            "problem_id"
        ):
            raise PublicReleaseError("public sample identity is invalid")
        if trace.code != source:
            raise PublicReleaseError("public trace and C++ source differ")
    if dict(sorted(observed_counts.items())) != dict(sorted(counts.items())):
        raise PublicReleaseError("public sample counts are invalid")
    actual_files = {
        PurePosixPath(path.relative_to(resolved_root).as_posix())
        for path in resolved_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_files != referenced:
        raise PublicReleaseError("public export contains unreferenced files")
    return {
        "artifact_count": len(referenced),
        "content_hash": expected_hash,
        "problem_count": len(problems),
        "sample_count": len(samples),
        "valid": True,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export or validate the public evaluation corpus.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export")
    export.add_argument("--authored-root", type=Path, required=True)
    export.add_argument("--quota", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "validate":
        print(json.dumps(validate_public_evaluation(arguments.root), sort_keys=True))
        return 0
    manifest = export_public_evaluation(
        authored_root=arguments.authored_root,
        quota_path=arguments.quota,
        output_root=arguments.output,
    )
    print(json.dumps({"content_hash": manifest["content_hash"]}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
