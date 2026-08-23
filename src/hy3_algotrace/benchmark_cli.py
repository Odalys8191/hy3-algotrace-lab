"""Standard-library command-line boundary for frozen benchmark execution."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TextIO

from .artifacts import ArtifactStore
from .benchmark import (
    ArtifactAttemptLedger,
    BenchmarkRunner,
    FormalEvidenceVerifier,
    RemoteAttemptBudget,
)
from .benchmark_models import (
    BenchmarkConfig,
    BenchmarkExecutionKind,
    MetricObservation,
    ObservationReplayInput,
)
from .hy3_client import Hy3AttemptContext

type BenchmarkExecute = Callable[
    [str, Callable[[Hy3AttemptContext], None]], MetricObservation
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hy3-algotrace-benchmark")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-config")
    validate.add_argument("--config", type=Path, required=True)
    run = commands.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--artifact-root", type=Path, required=True)
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
    formal_evidence_verifier: FormalEvidenceVerifier | None = None,
    output: TextIO | None = None,
) -> int:
    """Validate or execute a frozen config; execution is injected by corpus wiring."""

    parser = _parser()
    args = parser.parse_args(argv)
    config = _load_config(args.config)
    destination = output if output is not None else sys.stdout
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
    elif execute is None:
        parser.error(
            "live run requires the trusted Task-7/Hy3 execution adapter and credentials"
        )
    assert execute is not None
    artifacts = ArtifactStore(args.artifact_root)
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id=config.benchmark_id)
    budget = RemoteAttemptBudget(
        limit=config.remote_attempt_budget,
        event_sink=ledger.record,
        benchmark_id=config.benchmark_id,
    )
    report = BenchmarkRunner(
        config=config,
        artifacts=artifacts,
        budget=budget,
        ledger=ledger,
        execution_kind=execution_kind,
        replay_input=replay_input,
        formal_evidence_verifier=formal_evidence_verifier,
    ).run(execute)
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
