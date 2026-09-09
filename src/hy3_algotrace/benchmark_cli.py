"""Standard-library command-line boundary for frozen benchmark execution."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from .artifacts import ArtifactStore, ArtifactStoreError
from .benchmark import (
    ArtifactAttemptLedger,
    BenchmarkRunner,
    RemoteAttemptBudget,
)
from .benchmark_models import (
    BenchmarkConfig,
    BenchmarkExecutionKind,
    HumanConfirmedLabel,
    MetricObservation,
    ObservationReplayInput,
)
from .hy3_client import Hy3AttemptContext

type BenchmarkExecute = Callable[[str, Callable[[Hy3AttemptContext], None]], MetricObservation]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hy3-algotrace-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-config")
    validate.add_argument("--config", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--artifact-root", type=Path, required=True)
    run.add_argument("--catalog-root", type=Path)
    run.add_argument("--live-inputs", type=Path)
    live_validate = commands.add_parser("validate-live-inputs")
    live_validate.add_argument("--config", type=Path, required=True)
    live_validate.add_argument("--catalog-root", type=Path, required=True)
    live_validate.add_argument("--live-inputs", type=Path, required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--config", type=Path, required=True)
    replay.add_argument("--observations", type=Path, required=True)
    replay.add_argument("--artifact-root", type=Path, required=True)
    return parser


def _load_config(path: Path) -> BenchmarkConfig:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return BenchmarkConfig.model_validate(payload)


def _load_replay(path: Path) -> ObservationReplayInput:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return ObservationReplayInput.model_validate(payload)


def _emit(payload: dict[str, Any], output: TextIO) -> None:
    output.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    output.write("\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    execute: BenchmarkExecute | None = None,
    human_labels: tuple[HumanConfirmedLabel, ...] = (),
    output: TextIO | None = None,
) -> int:
    """Validate or execute a frozen config; execution is injected by corpus wiring."""

    parser = _parser()
    args = parser.parse_args(argv)
    destination = output if output is not None else sys.stdout
    automatic_live = args.command == "run" and execute is None
    try:
        config = _load_config(args.config)
    except (OSError, ValueError):
        if args.command == "validate-live-inputs":
            _emit({"inputs_valid": False, "formal": False, "docker_checked": False}, destination)
            return 2
        if automatic_live:
            _emit({"status": "preflight_failed", "formal_eligible": False}, destination)
            return 2
        raise
    if args.command == "validate-config":
        _emit(
            {
                "benchmark_id": config.benchmark_id,
                "formal": config.formal,
                "remote_attempt_budget": config.remote_attempt_budget,
                "static_attempt_lower_bound": config.static_attempt_lower_bound,
                "valid": True,
            },
            destination,
        )
        return 0
    from . import live_benchmark

    if args.command == "validate-live-inputs":
        from .catalog import ProblemCatalog

        try:
            live_benchmark.validate_live_inputs(
                config,
                ProblemCatalog.from_directory(args.catalog_root),
                live_benchmark.load_live_inputs(args.live_inputs),
            )
        except Exception:
            _emit({"inputs_valid": False, "formal": False, "docker_checked": False}, destination)
            return 2
        _emit({"inputs_valid": True, "formal": False, "docker_checked": False}, destination)
        return 0
    replay_input: ObservationReplayInput | None = None
    execution_kind = BenchmarkExecutionKind.LIVE
    if args.command == "replay":
        if config.formal:
            parser.error("artifact replay cannot claim a formal benchmark")
        replay_input = _load_replay(args.observations)
        execution_kind = BenchmarkExecutionKind.ARTIFACT_REPLAY
        by_sample = {row.sample_id: row for row in replay_input.observations}

        def replay_execute(
            sample_id: str, _observer: Callable[[Hy3AttemptContext], None]
        ) -> MetricObservation:
            try:
                return by_sample[sample_id]
            except KeyError as error:
                raise ValueError("replay is missing a frozen observation") from error

        execute = replay_execute
    elif execute is None and (args.catalog_root is None or args.live_inputs is None):
        parser.error("live run requires --catalog-root and --live-inputs")
    try:
        artifacts = ArtifactStore(args.artifact_root)
    except (OSError, ArtifactStoreError):
        if not automatic_live:
            raise
        _emit({"status": "preflight_failed", "formal_eligible": False}, destination)
        return 2
    if automatic_live:
        try:
            execute = live_benchmark.build_live_executor(
                config=config,
                catalog_root=args.catalog_root,
                inputs_path=args.live_inputs,
                artifacts=artifacts,
            )
        except Exception:
            _emit({"status": "preflight_failed", "formal_eligible": False}, destination)
            return 2
    assert execute is not None
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id=config.benchmark_id)
    budget = RemoteAttemptBudget(
        limit=config.remote_attempt_budget,
        event_sink=ledger.record,
        benchmark_id=config.benchmark_id,
    )
    try:
        report = BenchmarkRunner(
            config=config,
            artifacts=artifacts,
            budget=budget,
            ledger=ledger,
            execution_kind=execution_kind,
            replay_input=replay_input,
            human_labels=human_labels,
        ).run(execute)
    except live_benchmark.LiveExecutionError:
        if not automatic_live:
            raise
        try:
            ledger.finalize()
            artifacts.write_json(
                Path("benchmarks") / config.benchmark_id / "failure.json",
                {
                    "schema_version": "1.2",
                    "status": "execution_failed",
                    "formal_eligibility": False,
                },
            )
        except (OSError, ArtifactStoreError):
            _emit({"status": "artifact_failed", "formal_eligible": False}, destination)
            return 2
        _emit({"status": "execution_failed", "formal_eligible": False}, destination)
        return 2
    except (OSError, ArtifactStoreError):
        if not automatic_live:
            raise
        _emit({"status": "artifact_failed", "formal_eligible": False}, destination)
        return 2
    _emit(
        {
            "benchmark_id": report.benchmark_id,
            "complete": report.complete,
            "execution_kind": report.execution_kind,
            "formal_eligible": report.formal_eligible,
            "remote_attempts_used": report.remote_attempts_used,
            "status": report.status,
        },
        destination,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main in tests
    raise SystemExit(main())
