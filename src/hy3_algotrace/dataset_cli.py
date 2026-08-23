"""Command-line entry points for external Task 7 dataset and corpus linting."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from hy3_algotrace.artifacts import canonical_json_bytes
from hy3_algotrace.corpus import (
    CorpusDataError,
    ProjectBundleManifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from hy3_algotrace.dataset_models import (
    AcquisitionManifest,
    CandidateConversionReport,
    CandidateReview,
    ConversionTool,
    DatasetDataError,
    DatasetFormat,
    EligibilityQuotaReport,
    FrozenSelectionManifest,
    QuotaStatus,
    build_quota_report,
    convert_codecontests_file,
    freeze_selection,
    validate_acquired_assets,
    validate_frozen_selection,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run a fail-closed command without echoing raw problem or hidden-test data."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    try:
        return int(arguments.handler(arguments))
    except FileExistsError:
        print("error: output artifacts are create-only", file=sys.stderr)
        return 2
    except (
        CorpusDataError,
        DatasetDataError,
        JSONDecodeError,
        OSError,
        TypeError,
        UnicodeError,
        ValidationError,
        ValueError,
    ):
        print("error: dataset command failed", file=sys.stderr)
        return 2


JSONDecodeError = json.JSONDecodeError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hy3_algotrace.dataset_cli",
        description="Validate external CodeContests provenance and authored corpus artifacts.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    acquisition = commands.add_parser("validate-acquisition")
    acquisition.add_argument("manifest", type=Path)
    acquisition.add_argument("--validation", type=Path, required=True)
    acquisition.add_argument("--test", type=Path, required=True)
    acquisition.add_argument("--output", type=Path, required=True)
    acquisition.set_defaults(handler=_validate_acquisition)

    convert = commands.add_parser("convert")
    convert.add_argument("input", type=Path)
    convert.add_argument("--split", choices=("validation", "test"), required=True)
    convert.add_argument(
        "--format",
        choices=tuple(item.value for item in DatasetFormat),
        required=True,
    )
    convert.add_argument("--reviews", type=Path, required=True)
    convert.add_argument("--converter-name", required=True)
    convert.add_argument("--converter-version", required=True)
    convert.add_argument("--converter-arg", action="append", default=[])
    convert.add_argument("--output", type=Path, required=True)
    convert.set_defaults(handler=_convert)

    quota = commands.add_parser("quota")
    quota.add_argument("conversions", type=Path, nargs="+")
    quota.add_argument("--output", type=Path, required=True)
    quota.set_defaults(handler=_quota)

    freeze = commands.add_parser("freeze-selection")
    freeze.add_argument("selected_ids", type=Path)
    freeze.add_argument("--conversion", type=Path, action="append", required=True)
    freeze.add_argument("--quota", type=Path, required=True)
    freeze.add_argument("--acquisition", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.set_defaults(handler=_freeze_selection)

    selection = commands.add_parser("validate-selection")
    selection.add_argument("manifest", type=Path)
    selection.add_argument("--conversion", type=Path, action="append", required=True)
    selection.add_argument("--quota", type=Path, required=True)
    selection.add_argument("--acquisition", type=Path, required=True)
    selection.set_defaults(handler=_validate_selection)

    bundles = commands.add_parser("lint-bundles")
    bundles.add_argument("manifest", type=Path)
    bundles.add_argument("--root", type=Path, required=True)
    bundles.add_argument("--selection", type=Path, required=True)
    bundles.set_defaults(handler=_lint_bundles)

    corpus = commands.add_parser("lint-corpus")
    corpus.add_argument("manifest", type=Path)
    corpus.add_argument("--root", type=Path, required=True)
    corpus.add_argument("--selection", type=Path, required=True)
    corpus.add_argument("--bundles", type=Path, required=True)
    corpus.add_argument("--output", type=Path, required=True)
    corpus.set_defaults(handler=_lint_corpus)
    return parser


def _validate_acquisition(arguments: argparse.Namespace) -> int:
    manifest = _read_model(AcquisitionManifest, arguments.manifest)
    report = validate_acquired_assets(
        manifest,
        {"validation": arguments.validation, "test": arguments.test},
    )
    _write_model(arguments.output, report)
    print(arguments.output)
    return 0


def _convert(arguments: argparse.Namespace) -> int:
    raw_reviews = _read_json(arguments.reviews)
    if not isinstance(raw_reviews, list):
        raise DatasetDataError("checker reviews must be a JSON array")
    reviews = tuple(
        CandidateReview.model_validate_json(_compact_json(review)) for review in raw_reviews
    )
    report = convert_codecontests_file(
        arguments.input,
        split=arguments.split,
        data_format=DatasetFormat(arguments.format),
        reviews=reviews,
        converter=ConversionTool(
            name=arguments.converter_name,
            version=arguments.converter_version,
        ),
        converter_argv=tuple(arguments.converter_arg) or None,
    )
    _write_model(arguments.output, report)
    print(arguments.output)
    return 0


def _quota(arguments: argparse.Namespace) -> int:
    conversions = tuple(
        _read_model(CandidateConversionReport, path) for path in arguments.conversions
    )
    report = build_quota_report(conversions)
    _write_model(arguments.output, report)
    print(report.status.value)
    return 0 if report.status is QuotaStatus.FULFILLED else 3


def _freeze_selection(arguments: argparse.Namespace) -> int:
    selected_ids = _read_json(arguments.selected_ids)
    if not isinstance(selected_ids, list) or any(
        not isinstance(problem_id, str) for problem_id in selected_ids
    ):
        raise DatasetDataError("selected IDs must be a JSON string array")
    conversions = tuple(
        _read_model(CandidateConversionReport, path) for path in arguments.conversion
    )
    quota = _read_model(EligibilityQuotaReport, arguments.quota)
    acquisition = _read_model(AcquisitionManifest, arguments.acquisition)
    manifest = freeze_selection(
        selected_ids,
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
    )
    _write_model(arguments.output, manifest)
    print(arguments.output)
    return 0


def _validate_selection(arguments: argparse.Namespace) -> int:
    payload = _read_object(arguments.manifest)
    conversions = tuple(
        _read_model(CandidateConversionReport, path) for path in arguments.conversion
    )
    quota = _read_model(EligibilityQuotaReport, arguments.quota)
    acquisition = _read_model(AcquisitionManifest, arguments.acquisition)
    manifest = validate_frozen_selection(
        payload,
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
    )
    print(manifest.content_hash)
    return 0


def _lint_bundles(arguments: argparse.Namespace) -> int:
    selection = _read_model(FrozenSelectionManifest, arguments.selection)
    manifest = lint_project_bundles(
        _read_object(arguments.manifest),
        root=arguments.root,
        selection=selection,
    )
    print(manifest.content_hash)
    return 0


def _lint_corpus(arguments: argparse.Namespace) -> int:
    selection = _read_model(FrozenSelectionManifest, arguments.selection)
    bundles = _read_model(ProjectBundleManifest, arguments.bundles)
    audit = lint_corpus_manifest(
        _read_object(arguments.manifest),
        root=arguments.root,
        selection=selection,
        bundle_manifest=bundles,
    )
    _write_model(arguments.output, audit)
    print(audit.status.value)
    return 0 if audit.status.value == "complete" else 3


def _read_model[ModelT: BaseModel](model: type[ModelT], path: Path) -> ModelT:
    try:
        text = _read_text(path)
        return model.model_validate_json(text)
    except ValidationError as error:
        raise DatasetDataError(f"invalid {model.__name__}") from error


def _read_object(path: Path) -> Mapping[str, Any]:
    value = _read_json(path)
    if not isinstance(value, Mapping):
        raise DatasetDataError("manifest must be a JSON object")
    return value


def _read_json(path: Path) -> Any:
    return json.loads(_read_text(path))


def _read_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise DatasetDataError("input must be a regular non-symlink file")
    return path.read_text(encoding="utf-8")


def _write_model(path: Path, model: BaseModel) -> None:
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise DatasetDataError("output parent must be an existing non-symlink directory")
    with path.open("xb") as handle:
        handle.write(canonical_json_bytes(model.model_dump(mode="json")))
        handle.write(b"\n")


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":  # pragma: no cover - exercised via main
    raise SystemExit(main())
