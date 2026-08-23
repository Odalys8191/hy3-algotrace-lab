"""Immutable benchmark orchestration, remote-attempt budget, and ledger."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .artifacts import ArtifactRef, ArtifactStore
from .benchmark_models import (
    ArtifactHashEntry,
    BenchmarkConfig,
    BenchmarkExecutionKind,
    BenchmarkRunReport,
    BenchmarkStatus,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    ObservationReplayInput,
    SampleKind,
    VerifiedDataEvidence,
)
from .bootstrap import bootstrap_metric, find_stable_breakpoint
from .charts import metric_chart_spec
from .contracts import RatingBand
from .hy3_client import Hy3AttemptContext
from .metrics import compute_metrics


class BudgetExceededError(RuntimeError):
    """No further remote attempt may be transmitted."""


type FormalEvidenceVerifier = Callable[
    [BenchmarkConfig, VerifiedDataEvidence, tuple[MetricObservation, ...]], bool
]


class RemoteAttemptBudget:
    """Atomically reserve and optionally persist every outbound attempt."""

    def __init__(
        self,
        *,
        limit: int,
        consumed_attempts: int = 0,
        event_sink: Callable[[LedgerEvent], None] | None = None,
        benchmark_id: str = "standalone",
    ) -> None:
        if limit < 1 or consumed_attempts < 0 or consumed_attempts > limit:
            raise ValueError("invalid remote attempt budget state")
        self._limit = limit
        self._used = consumed_attempts
        self._event_sink = event_sink
        self._benchmark_id = benchmark_id
        self._lock = threading.Lock()
        self._events: list[LedgerEvent] = []

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def reserve(self, context: Hy3AttemptContext, *, sample_id: str) -> int:
        with self._lock:
            if self._used >= self._limit:
                raise BudgetExceededError("remote attempt budget exhausted")
            sequence = self._used + 1
            event = LedgerEvent(
                benchmark_id=self._benchmark_id,
                sequence=sequence,
                sample_id=sample_id,
                operation=context.operation,
                phase=context.phase,
                retry_number=context.retry_number,
            )
            if self._event_sink is not None:
                self._event_sink(event)
            self._events.append(event)
            self._used = sequence
            return sequence

    def for_sample(self, sample_id: str) -> Callable[[Hy3AttemptContext], None]:
        def observe(context: Hy3AttemptContext) -> None:
            self.reserve(context, sample_id=sample_id)

        return observe


class ArtifactAttemptLedger:
    """Create-only ledger events and a final immutable index."""

    def __init__(self, artifacts: ArtifactStore, *, benchmark_id: str) -> None:
        self._artifacts = artifacts
        self._benchmark_id = benchmark_id
        self._refs: list[ArtifactRef] = []
        self._lock = threading.Lock()

    def record(self, event: LedgerEvent) -> None:
        if event.benchmark_id != self._benchmark_id:
            raise ValueError("ledger event benchmark identity does not match")
        path = (
            Path("benchmarks")
            / self._benchmark_id
            / "ledger"
            / f"{event.sequence:06d}.json"
        )
        ref = self._artifacts.write_json(path, event.model_dump(mode="json"))
        with self._lock:
            self._refs.append(ref)

    def finalize(self) -> ArtifactRef:
        with self._lock:
            refs = tuple(sorted(self._refs, key=lambda item: str(item.path)))
        index = LedgerIndex(
            benchmark_id=self._benchmark_id,
            event_paths=tuple(str(ref.path) for ref in refs),
            event_hashes=tuple(ref.content_hash for ref in refs),
        )
        return self._artifacts.write_json(
            Path("benchmarks") / self._benchmark_id / "ledger-index.json",
            index.model_dump(mode="json"),
        )


class BenchmarkRunner:
    """Execute ordered samples and publish immutable complete or partial outputs."""

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        artifacts: ArtifactStore,
        budget: RemoteAttemptBudget,
        ledger: ArtifactAttemptLedger,
        formal_evidence_verifier: FormalEvidenceVerifier | None = None,
        execution_kind: BenchmarkExecutionKind = BenchmarkExecutionKind.LIVE,
        replay_input: ObservationReplayInput | None = None,
    ) -> None:
        self._config = config
        self._artifacts = artifacts
        self._budget = budget
        self._ledger = ledger
        self._formal_evidence_verifier = formal_evidence_verifier
        self._execution_kind = execution_kind
        self._replay_input = replay_input
        self._specs = {item.sample_id: item for item in config.sample_specs}
        if (execution_kind is BenchmarkExecutionKind.ARTIFACT_REPLAY) is (
            replay_input is None
        ):
            raise ValueError("artifact replay execution requires replay input only")
        if execution_kind is BenchmarkExecutionKind.ARTIFACT_REPLAY:
            if config.formal:
                raise ValueError("artifact replay can never execute a formal benchmark")
            assert replay_input is not None
            replay_ids = tuple(row.sample_id for row in replay_input.observations)
            if replay_ids != config.ordered_sample_ids:
                raise ValueError("replay observations must match frozen sample order")
            if budget.used != 0:
                raise ValueError("artifact replay cannot inherit remote attempts")

    def run(
        self,
        execute: Callable[
            [str, Callable[[Hy3AttemptContext], None]], MetricObservation
        ],
    ) -> BenchmarkRunReport:
        root = Path("benchmarks") / self._config.benchmark_id
        refs: list[ArtifactHashEntry] = []
        config_ref = self._artifacts.write_json(
            root / "config.json", self._config.model_dump(mode="json")
        )
        refs.append(self._entry("config", config_ref))
        if self._replay_input is not None:
            replay_ref = self._artifacts.write_json(
                root / "replay-input.json",
                self._replay_input.model_dump(mode="json"),
            )
            refs.append(self._entry("replay_input", replay_ref))
        observations: list[MetricObservation] = []
        exhausted = False
        for sample_id in self._config.ordered_sample_ids:
            try:
                observation = execute(sample_id, self._budget.for_sample(sample_id))
            except BudgetExceededError:
                exhausted = True
                break
            self._validate_observation(sample_id, observation)
            observation_ref = self._artifacts.write_json(
                root / "observations" / f"{sample_id}.json",
                observation.model_dump(mode="json"),
            )
            refs.append(self._entry(f"observation:{sample_id}", observation_ref))
            observations.append(observation)
        ledger_ref = self._ledger.finalize()
        refs.append(self._entry("ledger_index", ledger_ref))
        complete = not exhausted and len(observations) == len(
            self._config.ordered_sample_ids
        )
        if complete:
            metrics = compute_metrics(observations, formal=self._config.formal)
            metrics_ref = self._artifacts.write_json(
                root / "metrics.json", metrics.model_dump(mode="json")
            )
            refs.append(self._entry("metrics", metrics_ref))
            intervals = tuple(
                bootstrap_metric(
                    observations,
                    metric_name=metric.name,
                    seed=self._config.seed,
                    replicates=self._config.bootstrap_replicates,
                ).model_dump(mode="json")
                for metric in metrics.overall
            )
            ci_ref = self._artifacts.write_json(
                root / "confidence-intervals.json",
                {"schema_version": "1.2", "intervals": intervals},
            )
            refs.append(self._entry("confidence_intervals", ci_ref))
            breakpoint = find_stable_breakpoint(
                {
                    band: tuple(
                        row.predicted_final_correct is row.gold_final_correct
                        for row in observations
                        if row.sample_kind is SampleKind.NATURAL
                        and row.gold_final_correct is not None
                        and row.rating_band is band
                    )
                    for band in RatingBand
                },
                seed=self._config.seed,
                replicates=self._config.bootstrap_replicates,
            )
            breakpoint_ref = self._artifacts.write_json(
                root / "breakpoint.json", breakpoint.model_dump(mode="json")
            )
            refs.append(self._entry("breakpoint", breakpoint_ref))
            chart = metric_chart_spec(
                metrics,
                metric_names=tuple(metric.name for metric in metrics.overall),
            )
            chart_ref = self._artifacts.write_json(
                root / "charts" / "overall-metrics.json",
                chart.model_dump(mode="json"),
            )
            refs.append(self._entry("chart:overall_metrics", chart_ref))
        formal_evidence_verified = self._verify_formal_evidence(tuple(observations))
        report = BenchmarkRunReport(
            benchmark_id=self._config.benchmark_id,
            execution_kind=self._execution_kind,
            status=(BenchmarkStatus.COMPLETE if complete else BenchmarkStatus.PARTIAL),
            complete=complete,
            formal_eligible=(
                complete and self._config.formal and formal_evidence_verified
            ),
            formal_evidence_verified=formal_evidence_verified,
            completed_sample_ids=tuple(row.sample_id for row in observations),
            remote_attempts_used=self._budget.used,
            artifacts=tuple(refs),
        )
        self._artifacts.write_json(root / "report.json", report.model_dump(mode="json"))
        return report

    def _validate_observation(
        self, sample_id: str, observation: MetricObservation
    ) -> None:
        spec = self._specs[sample_id]
        actual = (
            observation.sample_id,
            observation.problem_id,
            observation.sample_kind,
            observation.topic,
            observation.rating_band,
        )
        expected = (
            spec.sample_id,
            spec.problem_id,
            spec.sample_kind,
            spec.topic,
            spec.rating_band,
        )
        if actual != expected:
            raise ValueError("benchmark observation violates its frozen sample specification")

    def _verify_formal_evidence(
        self, observations: tuple[MetricObservation, ...]
    ) -> bool:
        if (
            not self._config.formal
            or self._execution_kind is not BenchmarkExecutionKind.LIVE
            or self._formal_evidence_verifier is None
            or self._config.verified_data_evidence is None
            or len(observations) != len(self._config.ordered_sample_ids)
        ):
            return False
        try:
            return self._formal_evidence_verifier(
                self._config,
                self._config.verified_data_evidence,
                observations,
            ) is True
        except Exception:
            return False

    @staticmethod
    def _entry(name: str, ref: ArtifactRef) -> ArtifactHashEntry:
        return ArtifactHashEntry(
            name=name,
            path=str(ref.path),
            content_hash=ref.content_hash,
        )
