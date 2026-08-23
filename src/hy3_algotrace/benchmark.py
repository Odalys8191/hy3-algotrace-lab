"""Immutable benchmark orchestration, remote-attempt budget, and ledger."""

from __future__ import annotations

import hashlib
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api_models import InternalRunReport
from .artifacts import ArtifactRef, ArtifactStore, sha256_json
from .benchmark_models import (
    ArtifactHashEntry,
    BenchmarkConfig,
    BenchmarkExecutionKind,
    BenchmarkRunReport,
    BenchmarkStatus,
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
from .contracts import JudgeEvidence, SolutionTrace
from .hy3_client import Hy3AttemptContext
from .metrics import compute_metrics


class BudgetExceededError(RuntimeError):
    """No further remote attempt may be transmitted."""


class Task7BridgeUnavailableError(RuntimeError):
    """Task-7 production capability is not present on this isolated branch."""


@dataclass(frozen=True, slots=True)
class FormalRunArtifacts:
    """Concrete Task-7 corpus bytes and Task-5 run evidence for one sample."""

    sample_id: str
    trace_artifact_bytes: bytes
    cpp_source_bytes: bytes
    internal_report: InternalRunReport
    judge_evidence: JudgeEvidence
    human_label: HumanConfirmedLabel


_TASK7_BRIDGE_TOKEN = object()
_TASK7_BENCHMARK_CAPABILITIES: weakref.WeakSet[Any] = weakref.WeakSet()


class Task7FormalBenchmarkCapability:
    """Opaque, non-persistable result of replaying Task-7 and run evidence."""

    _config_hash: str
    _observation_hashes: tuple[str, ...]
    _human_label_hashes: tuple[str, ...]
    __slots__ = (
        "_config_hash",
        "_observation_hashes",
        "_human_label_hashes",
        "__weakref__",
    )

    def __init__(
        self,
        *,
        _bridge_token: object,
        config_hash: str = "",
        observation_hashes: tuple[str, ...] = (),
        human_label_hashes: tuple[str, ...] = (),
    ) -> None:
        if _bridge_token is not _TASK7_BRIDGE_TOKEN:
            raise ValueError("formal eligibility requires the integrated Task-7 bridge")
        object.__setattr__(self, "_config_hash", config_hash)
        object.__setattr__(self, "_observation_hashes", observation_hashes)
        object.__setattr__(self, "_human_label_hashes", human_label_hashes)
        _TASK7_BENCHMARK_CAPABILITIES.add(self)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("Task-7 benchmark capabilities are immutable")

    def _matches(
        self,
        config: BenchmarkConfig,
        observations: tuple[MetricObservation, ...],
        human_labels: tuple[HumanConfirmedLabel, ...],
    ) -> bool:
        return (
            self in _TASK7_BENCHMARK_CAPABILITIES
            and self._config_hash == sha256_json(config.model_dump(mode="json"))
            and self._observation_hashes
            == tuple(sha256_json(row.model_dump(mode="json")) for row in observations)
            and self._human_label_hashes
            == tuple(sha256_json(label.model_dump(mode="json")) for label in human_labels)
        )


def issue_task7_formal_benchmark_capability(
    *,
    config: BenchmarkConfig,
    observations: tuple[MetricObservation, ...],
    selection_chain: object,
    corpus: object,
    judge_validation: object,
    run_artifacts: tuple[FormalRunArtifacts, ...],
) -> Task7FormalBenchmarkCapability:
    """Replay integrated Task-7 capabilities and concrete per-run evidence.

    Imports are deliberately local: this Task-6 branch stays isolated, while the
    bridge becomes live only after Task 7 is integrated by the controller.
    """

    try:
        from .corpus import (  # type: ignore[import-untyped]
            CorpusManifest,
            CorpusSampleKind,
            CorpusStatus,
        )
        from .dataset_models import VerifiedSelectionChain  # type: ignore[import-untyped]
        from .differential import (  # type: ignore[import-untyped]
            FormalCorpusJudgeValidationResult,
        )
    except ImportError as error:
        raise Task7BridgeUnavailableError(
            "integrate Task 7 before issuing formal benchmark capability"
        ) from error
    if (
        not isinstance(selection_chain, VerifiedSelectionChain)
        or not selection_chain._is_verified()
        or not isinstance(corpus, CorpusManifest)
        or corpus.status is not CorpusStatus.COMPLETE
        or not isinstance(judge_validation, FormalCorpusJudgeValidationResult)
        or judge_validation.formal_eligibility is not True
    ):
        raise ValueError("formal benchmark requires replayed Task-7 capabilities")
    selection = selection_chain.selection
    if (
        config.selection_hash != selection.content_hash
        or config.corpus_hash != corpus.content_hash
        or corpus.selection_manifest_hash != selection.content_hash
        or judge_validation.evidence_manifest.corpus_manifest_hash != corpus.content_hash
        or judge_validation.evidence_manifest.selection_manifest_hash != selection.content_hash
    ):
        raise ValueError("formal benchmark does not match the Task-7 evidence chain")
    locator = config.verified_data_evidence
    if locator is None or locator.artifact_hash != judge_validation.evidence_manifest.content_hash:
        raise ValueError("formal benchmark locator does not bind Task-7 judge replay")
    natural_run = corpus.natural_run_config
    task7_parameters = tuple(
        (parameter.name, parameter.value) for parameter in natural_run.model_parameters
    )
    benchmark_parameters = tuple(
        (parameter.name, parameter.value) for parameter in config.model_parameters
    )
    if (
        config.model != natural_run.model_name
        or config.endpoint_identity != natural_run.endpoint_url
        or config.generator_prompt_version != natural_run.prompt_version
        or benchmark_parameters != task7_parameters
    ):
        raise ValueError("formal benchmark generation config does not match Task 7")
    samples = {sample.sample_id: sample for sample in corpus.samples}
    bindings = {binding.sample_id: binding for binding in run_artifacts}
    if (
        len(samples) != 165
        or set(samples) != set(config.ordered_sample_ids)
        or set(bindings) != set(samples)
        or len(bindings) != len(run_artifacts)
    ):
        raise ValueError("formal run artifacts must exactly cover all 165 corpus samples")
    observation_by_id = {row.sample_id: row for row in observations}
    if set(observation_by_id) != set(samples) or len(observation_by_id) != len(observations):
        raise ValueError("formal observations must exactly cover the Task-7 corpus")
    kind_map = {
        CorpusSampleKind.GOLD: SampleKind.GOLD,
        CorpusSampleKind.CONTROLLED_WRONG: SampleKind.CONTROLLED_WRONG,
        CorpusSampleKind.PARADOX: SampleKind.PARADOX,
        CorpusSampleKind.NATURAL: SampleKind.NATURAL,
    }
    selection_by_problem = {entry.problem_id: entry for entry in selection.entries}
    if set(selection_by_problem) != {sample.problem_id for sample in samples.values()}:
        raise ValueError("formal corpus problem identities do not match Task 7 selection")
    specs = {spec.sample_id: spec for spec in config.sample_specs}
    for sample_id in config.ordered_sample_ids:
        sample = samples[sample_id]
        binding = bindings[sample_id]
        observation = observation_by_id[sample_id]
        selection_entry = selection_by_problem[sample.problem_id]
        spec = specs[sample_id]
        if (
            spec.problem_id != sample.problem_id
            or spec.topic is not selection_entry.topic
            or spec.rating_band is not selection_entry.rating_band
        ):
            raise ValueError("formal benchmark stratum does not match Task 7 selection")
        _validate_formal_run_binding(
            sample=sample,
            expected_kind=kind_map[sample.kind],
            binding=binding,
            observation=observation,
        )
    return Task7FormalBenchmarkCapability(
        _bridge_token=_TASK7_BRIDGE_TOKEN,
        config_hash=sha256_json(config.model_dump(mode="json")),
        observation_hashes=tuple(sha256_json(row.model_dump(mode="json")) for row in observations),
        human_label_hashes=tuple(
            sha256_json(bindings[sample_id].human_label.model_dump(mode="json"))
            for sample_id in config.ordered_sample_ids
        ),
    )


def _validate_formal_run_binding(
    *,
    sample: Any,
    expected_kind: SampleKind,
    binding: FormalRunArtifacts,
    observation: MetricObservation,
) -> None:
    if (
        hashlib.sha256(binding.trace_artifact_bytes).hexdigest() != sample.trace.sha256
        or hashlib.sha256(binding.cpp_source_bytes).hexdigest() != sample.cpp_source.sha256
    ):
        raise ValueError("formal run bytes do not match the Task-7 corpus")
    try:
        trace = SolutionTrace.model_validate_json(binding.trace_artifact_bytes)
        source = binding.cpp_source_bytes.decode("utf-8")
    except (ValueError, UnicodeError) as error:
        raise ValueError("formal Task-7 trace/source artifacts are invalid") from error
    internal = binding.internal_report
    audit = internal.audit_report
    human = binding.human_label
    reviewer_ids = tuple(verdict.reviewer_id for verdict in audit.reviewer_verdicts)
    if reviewer_ids not in {
        ("logic-reviewer", "adversarial-reviewer"),
        ("logic-reviewer", "adversarial-reviewer", "arbiter"),
    }:
        raise ValueError("formal observation is not bound to run and human evidence")
    primary_agreement = _review_signature(audit.reviewer_verdicts[0]) == _review_signature(
        audit.reviewer_verdicts[1]
    )
    arbitration_used = len(audit.reviewer_verdicts) == 3
    if (
        trace.code != source
        or binding.sample_id != sample.sample_id
        or internal.run_id != audit.run_id
        or internal.trace != trace
        or internal.problem_id != sample.problem_id
        or audit.problem_id != sample.problem_id
        or audit.trace_id != trace.trace_id
        or audit.judge_evidence != binding.judge_evidence
        or human.sample_id != sample.sample_id
        or observation.sample_id != sample.sample_id
        or observation.problem_id != sample.problem_id
        or observation.sample_kind is not expected_kind
        or observation.gold_final_correct is not human.final_correct
        or observation.gold_process_valid is not human.process_valid
        or observation.predicted_final_correct is not audit.final_correct
        or observation.predicted_process_valid is not audit.process_valid
        or observation.predicted_taxonomy is not audit.final_error_taxonomy
        or observation.needs_human_review is not audit.needs_human_review
        or observation.primary_review_agreement is not primary_agreement
        or observation.arbitration_used is not arbitration_used
    ):
        raise ValueError("formal observation is not bound to run and human evidence")
    expected_step_number = None
    if audit.first_material_error_step_id is not None:
        expected_step_number = next(
            (
                step.step_number
                for step in trace.steps
                if step.step_id == audit.first_material_error_step_id
            ),
            None,
        )
    if observation.predicted_first_error_step != expected_step_number:
        raise ValueError("formal observation localization does not match AuditReport")
    if expected_kind is not SampleKind.NATURAL:
        gold_step_number = None
        if sample.first_error_step_id is not None:
            gold_step_number = next(
                (
                    step.step_number
                    for step in trace.steps
                    if step.step_id == sample.first_error_step_id
                ),
                None,
            )
            if gold_step_number is None:
                raise ValueError("formal corpus gold localization is not in the trace")
        if (
            human.final_correct is not sample.final_expected_correct
            or human.process_valid is not (sample.primary_error is None)
            or human.taxonomy is not sample.primary_error
            or human.first_error_step != gold_step_number
        ):
            raise ValueError("formal human label does not match controlled corpus gold")


def _review_signature(verdict: Any) -> tuple[Any, ...]:
    material_steps = tuple(
        sorted(
            (
                (review.step_id, review.status, review.taxonomy)
                for review in verdict.per_step_reviews
                if review.material
            ),
            key=lambda item: item[0],
        )
    )
    return (
        verdict.material_error,
        verdict.error_taxonomy,
        verdict.first_error_step_id,
        material_steps,
    )


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


class BenchmarkRunner:
    """Execute ordered samples and publish immutable complete or partial outputs."""

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        artifacts: ArtifactStore,
        budget: RemoteAttemptBudget,
        ledger: ArtifactAttemptLedger,
        formal_capability: Task7FormalBenchmarkCapability | None = None,
        human_labels: tuple[HumanConfirmedLabel, ...] = (),
        execution_kind: BenchmarkExecutionKind = BenchmarkExecutionKind.LIVE,
        replay_input: ObservationReplayInput | None = None,
    ) -> None:
        self._config = config
        self._artifacts = artifacts
        self._budget = budget
        self._ledger = ledger
        self._formal_capability = formal_capability
        self._human_labels = human_labels
        self._execution_kind = execution_kind
        self._replay_input = replay_input
        self._specs = {item.sample_id: item for item in config.sample_specs}
        self._human_label_set = (
            HumanConfirmedLabelSet(
                benchmark_id=config.benchmark_id,
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
        formal_evidence_verified = self._verify_formal_evidence(stable_observations)
        formal_attempt_profile_valid = self._formal_attempt_profile_valid(stable_observations)
        report = BenchmarkRunReport(
            benchmark_id=self._config.benchmark_id,
            execution_kind=self._execution_kind,
            status=(BenchmarkStatus.COMPLETE if complete else BenchmarkStatus.PARTIAL),
            complete=complete,
            formal_eligible=(
                complete
                and self._config.formal
                and formal_evidence_verified
                and formal_attempt_profile_valid
            ),
            formal_evidence_verified=formal_evidence_verified,
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

    def _verify_formal_evidence(self, observations: tuple[MetricObservation, ...]) -> bool:
        if (
            not self._config.formal
            or self._execution_kind is not BenchmarkExecutionKind.LIVE
            or self._formal_capability is None
            or len(observations) != len(self._config.ordered_sample_ids)
        ):
            return False
        return self._formal_capability._matches(self._config, observations, self._human_labels)

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
        expected_sequences = tuple(range(1, len(events) + 1))
        if tuple(event.sequence for event in events) != expected_sequences:
            return False
        known = set(self._config.ordered_sample_ids)
        natural = set(self._config.generation_sample_ids)
        allowed_operations = {
            self._config.generator_prompt_version,
            self._config.logic_review_prompt_version,
            self._config.adversarial_review_prompt_version,
            self._config.arbiter_prompt_version,
        }
        for event in events:
            if (
                event.benchmark_id != self._config.benchmark_id
                or event.sample_id not in known
                or event.operation not in allowed_operations
                or event.phase not in {"request", "schema_repair"}
                or (
                    event.operation == self._config.generator_prompt_version
                    and event.sample_id not in natural
                )
            ):
                return False
        required = [
            (sample_id, self._config.logic_review_prompt_version)
            for sample_id in self._config.audit_sample_ids
        ]
        required.extend(
            (sample_id, self._config.adversarial_review_prompt_version)
            for sample_id in self._config.audit_sample_ids
        )
        required.extend(
            (sample_id, self._config.generator_prompt_version)
            for sample_id in self._config.generation_sample_ids
        )
        return all(
            sum(
                event.sample_id == sample_id
                and event.operation == operation
                and event.phase == "request"
                and event.retry_number == 1
                for event in events
            )
            == 1
            for sample_id, operation in required
        )

    @staticmethod
    def _entry(name: str, ref: ArtifactRef) -> ArtifactHashEntry:
        return ArtifactHashEntry(
            name=name,
            path=str(ref.path),
            content_hash=ref.content_hash,
        )
