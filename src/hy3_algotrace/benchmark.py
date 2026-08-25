"""Immutable benchmark orchestration, remote-attempt budget, and ledger."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from .artifacts import ArtifactRef, ArtifactStore, sha256_json
from .benchmark_models import (
    ArtifactHashEntry,
    BenchmarkConfig,
    BenchmarkExecutionKind,
    BenchmarkRunReport,
    BenchmarkStatus,
    FormalIntegrationCandidate,
    HumanConfirmedLabel,
    HumanConfirmedLabelSet,
    LedgerEvent,
    LedgerIndex,
    MetricObservation,
    ObservationReplayInput,
    SampleKind,
)
from .bootstrap import (
    bootstrap_metric,
    find_stable_breakpoint,
    natural_final_outcomes,
)
from .charts import (
    metric_chart_spec,
    stratified_metric_chart_spec,
    taxonomy_distribution_chart_spec,
)
from .hy3_client import Hy3AttemptContext
from .metrics import compute_metrics


class BudgetExceededError(RuntimeError):
    """No further remote attempt may be transmitted."""


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
        self._events: list[LedgerEvent] = []
        self._lock = threading.Lock()

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def record(self, event: LedgerEvent) -> None:
        if event.benchmark_id != self._benchmark_id:
            raise ValueError("ledger event benchmark identity does not match")
        path = Path("benchmarks") / self._benchmark_id / "ledger" / f"{event.sequence:06d}.json"
        ref = self._artifacts.write_json(path, event.model_dump(mode="json"))
        with self._lock:
            self._refs.append(ref)
            self._events.append(event)

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


_FORMAL_MAX_RETRIES_PER_PHASE = 3


def formal_attempt_profile_is_valid(
    config: BenchmarkConfig,
    observations: tuple[MetricObservation, ...],
    events: tuple[LedgerEvent, ...],
) -> bool:
    """Validate the frozen per-sample operation, retry, and repair state machine."""

    if len(observations) != len(config.ordered_sample_ids):
        return False
    if tuple(event.sequence for event in events) != tuple(range(1, len(events) + 1)):
        return False
    arbitrated = {row.sample_id for row in observations if row.arbitration_used}
    audit = set(config.audit_sample_ids)
    natural = set(config.generation_sample_ids)
    cursor = 0
    for sample_id in config.ordered_sample_ids:
        operations: list[str] = []
        if sample_id in natural:
            operations.append(config.generator_prompt_version)
        if sample_id in audit:
            operations.extend(
                (
                    config.logic_review_prompt_version,
                    config.adversarial_review_prompt_version,
                )
            )
        if sample_id in arbitrated:
            operations.append(config.arbiter_prompt_version)
        for operation in operations:
            start = cursor
            request_retry = 1
            repair_retry = 1
            repair_started = False
            while cursor < len(events):
                event = events[cursor]
                if (event.sample_id, event.operation) != (sample_id, operation):
                    break
                if event.benchmark_id != config.benchmark_id:
                    return False
                if event.phase == "request":
                    if (
                        repair_started
                        or event.retry_number != request_retry
                        or event.retry_number > _FORMAL_MAX_RETRIES_PER_PHASE
                    ):
                        return False
                    request_retry += 1
                elif event.phase == "schema_repair":
                    if (
                        request_retry == 1
                        or event.retry_number != repair_retry
                        or event.retry_number > _FORMAL_MAX_RETRIES_PER_PHASE
                    ):
                        return False
                    repair_started = True
                    repair_retry += 1
                else:
                    return False
                cursor += 1
            if cursor == start:
                return False
    return cursor == len(events)


class BenchmarkRunner:
    """Execute ordered samples and publish immutable complete or partial outputs."""

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        artifacts: ArtifactStore,
        budget: RemoteAttemptBudget,
        ledger: ArtifactAttemptLedger,
        human_labels: tuple[HumanConfirmedLabel, ...] = (),
        execution_kind: BenchmarkExecutionKind = BenchmarkExecutionKind.LIVE,
        replay_input: ObservationReplayInput | None = None,
    ) -> None:
        self._config = BenchmarkConfig.model_validate(config.model_dump(mode="json"))
        self._artifacts = artifacts
        self._budget = budget
        self._ledger = ledger
        self._human_labels = human_labels
        self._execution_kind = execution_kind
        self._replay_input = replay_input
        self._specs = {item.sample_id: item for item in self._config.sample_specs}
        self._human_label_set = (
            HumanConfirmedLabelSet(
                benchmark_id=self._config.benchmark_id,
                labels=human_labels,
            )
            if human_labels
            else None
        )
        if self._human_label_set is not None and not {
            label.sample_id for label in self._human_label_set.labels
        } <= set(config.ordered_sample_ids):
            raise ValueError("human-confirmed label references an unknown frozen sample")
        if (execution_kind is BenchmarkExecutionKind.ARTIFACT_REPLAY) is (replay_input is None):
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
        execute: Callable[[str, Callable[[Hy3AttemptContext], None]], MetricObservation],
    ) -> BenchmarkRunReport:
        root = Path("benchmarks") / self._config.benchmark_id
        refs: list[ArtifactHashEntry] = []
        config_ref = self._artifacts.write_json(
            root / "config.json", self._config.model_dump(mode="json")
        )
        refs.append(self._entry("config", config_ref))
        if self._human_label_set is not None:
            labels_ref = self._artifacts.write_json(
                root / "human-labels.json",
                self._human_label_set.model_dump(mode="json"),
            )
            refs.append(self._entry("human_labels", labels_ref))
        if self._replay_input is not None:
            replay_ref = self._artifacts.write_json(
                root / "replay-input.json",
                self._replay_input.model_dump(mode="json"),
            )
            refs.append(self._entry("replay_input", replay_ref))
        observations: list[MetricObservation] = []
        observation_refs: list[ArtifactRef] = []
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
            observation_refs.append(observation_ref)
            observations.append(observation)
        ledger_ref = self._ledger.finalize()
        refs.append(self._entry("ledger_index", ledger_ref))
        complete = not exhausted and len(observations) == len(self._config.ordered_sample_ids)
        if complete:
            metrics = compute_metrics(
                observations,
                human_labels=self._human_labels,
                formal=self._config.formal,
            )
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
                    human_labels=self._human_labels,
                ).model_dump(mode="json")
                for metric in metrics.overall
            )
            ci_ref = self._artifacts.write_json(
                root / "confidence-intervals.json",
                {"schema_version": "1.2", "intervals": intervals},
            )
            refs.append(self._entry("confidence_intervals", ci_ref))
            breakpoint = find_stable_breakpoint(
                natural_final_outcomes(observations),
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
            metric_names = tuple(metric.name for metric in metrics.overall)
            topic_chart = stratified_metric_chart_spec(
                metrics, dimension="topic", metric_names=metric_names
            )
            topic_ref = self._artifacts.write_json(
                root / "charts" / "topic-metrics.json",
                topic_chart.model_dump(mode="json"),
            )
            refs.append(self._entry("chart:topic_metrics", topic_ref))
            rating_chart = stratified_metric_chart_spec(
                metrics, dimension="rating_band", metric_names=metric_names
            )
            rating_ref = self._artifacts.write_json(
                root / "charts" / "rating-band-metrics.json",
                rating_chart.model_dump(mode="json"),
            )
            refs.append(self._entry("chart:rating_band_metrics", rating_ref))
            taxonomy_chart = taxonomy_distribution_chart_spec(observations)
            taxonomy_ref = self._artifacts.write_json(
                root / "charts" / "taxonomy-distribution.json",
                taxonomy_chart.model_dump(mode="json"),
            )
            refs.append(self._entry("chart:taxonomy_distribution", taxonomy_ref))
        stable_observations = tuple(observations)
        formal_attempt_profile_valid = self._formal_attempt_profile_valid(stable_observations)
        formal_candidate_complete = (
            complete
            and self._config.formal
            and formal_attempt_profile_valid
            and self._formal_human_labels_match(stable_observations)
        )
        if formal_candidate_complete:
            candidate = FormalIntegrationCandidate(
                benchmark_id=self._config.benchmark_id,
                config_hash=config_ref.content_hash,
                observation_hashes=tuple(ref.content_hash for ref in observation_refs),
                human_label_hashes=tuple(
                    sha256_json(label.model_dump(mode="json")) for label in self._human_labels
                ),
                ledger_index_hash=ledger_ref.content_hash,
                remote_attempts_used=self._budget.used,
            )
            candidate_ref = self._artifacts.write_json(
                root / "formal-candidate.json",
                candidate.model_dump(mode="json"),
            )
            refs.append(self._entry("formal_integration_candidate", candidate_ref))
        report = BenchmarkRunReport(
            benchmark_id=self._config.benchmark_id,
            execution_kind=self._execution_kind,
            status=(BenchmarkStatus.COMPLETE if complete else BenchmarkStatus.PARTIAL),
            complete=complete,
            formal_candidate_complete=formal_candidate_complete,
            formal_eligible=False,
            formal_evidence_verified=False,
            formal_attempt_profile_valid=formal_attempt_profile_valid,
            completed_sample_ids=tuple(row.sample_id for row in observations),
            remote_attempts_used=self._budget.used,
            artifacts=tuple(refs),
        )
        self._artifacts.write_json(root / "report.json", report.model_dump(mode="json"))
        return report

    def _validate_observation(self, sample_id: str, observation: MetricObservation) -> None:
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
        if self._config.formal:
            if not self._formal_gold_semantics_valid(observation):
                raise ValueError("formal observation gold semantics do not match its sample kind")
            agreement = observation.primary_review_agreement
            if agreement is None or observation.arbitration_used is not (agreement is False):
                raise ValueError(
                    "formal primary review relationship requires agreement or arbitration"
                )

    @staticmethod
    def _formal_gold_semantics_valid(observation: MetricObservation) -> bool:
        labels = (observation.gold_final_correct, observation.gold_process_valid)
        expected_labels = {
            SampleKind.GOLD: (True, True),
            SampleKind.CONTROLLED_WRONG: (False, False),
            SampleKind.PARADOX: (True, False),
        }
        if observation.sample_kind is SampleKind.NATURAL:
            if None in labels:
                return False
        elif labels != expected_labels[observation.sample_kind]:
            return False
        has_error = (
            observation.gold_first_error_step is not None and observation.gold_taxonomy is not None
        )
        has_no_error = (
            observation.gold_first_error_step is None and observation.gold_taxonomy is None
        )
        return has_no_error if observation.gold_process_valid else has_error

    def _formal_attempt_profile_valid(self, observations: tuple[MetricObservation, ...]) -> bool:
        if (
            not self._config.formal
            or self._execution_kind is not BenchmarkExecutionKind.LIVE
            or len(observations) != len(self._config.ordered_sample_ids)
        ):
            return False
        events = self._budget.events
        if len(events) != self._budget.used or self._ledger.events != events:
            return False
        return formal_attempt_profile_is_valid(self._config, observations, events)

    def _formal_human_labels_match(self, observations: tuple[MetricObservation, ...]) -> bool:
        if len(self._human_labels) != len(observations):
            return False
        for observation, label in zip(observations, self._human_labels, strict=True):
            if (
                label.sample_id,
                label.final_correct,
                label.process_valid,
                label.first_error_step,
                label.taxonomy,
            ) != (
                observation.sample_id,
                observation.gold_final_correct,
                observation.gold_process_valid,
                observation.gold_first_error_step,
                observation.gold_taxonomy,
            ):
                return False
        return True

    @staticmethod
    def _entry(name: str, ref: ArtifactRef) -> ArtifactHashEntry:
        return ArtifactHashEntry(
            name=name,
            path=str(ref.path),
            content_hash=ref.content_hash,
        )
