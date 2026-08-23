from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from test_hy3_client import problem
from test_metrics import literal_rows

from hy3_algotrace.artifacts import ArtifactExistsError, ArtifactStore, sha256_json
from hy3_algotrace.benchmark import (
    ArtifactAttemptLedger,
    BenchmarkRunner,
    BudgetExceededError,
    RemoteAttemptBudget,
)
from hy3_algotrace.benchmark_models import (
    BenchmarkConfig,
    BenchmarkParameter,
    BenchmarkSampleSpec,
    BenchmarkStatus,
    LedgerEvent,
    MetricObservation,
    SampleKind,
    VerifiedDataEvidence,
)
from hy3_algotrace.contracts import ErrorTaxonomy, RatingBand, Topic
from hy3_algotrace.hy3_client import Hy3AttemptContext, Hy3Client, Hy3Config


def config(
    *,
    benchmark_id: str = "bench-1",
    sample_ids: tuple[str, ...] = ("n1", "n2"),
    generation_ids: tuple[str, ...] = (),
    audit_ids: tuple[str, ...] = ("n1", "n2"),
    budget: int = 4,
    formal: bool = False,
    sample_specs: tuple[BenchmarkSampleSpec, ...] | None = None,
    verified_data_evidence: VerifiedDataEvidence | None = None,
    bootstrap_replicates: int = 10,
) -> BenchmarkConfig:
    known_rows = {row.sample_id: row for row in literal_rows()}
    resolved_specs = sample_specs or tuple(
        BenchmarkSampleSpec(
            sample_id=sample_id,
            problem_id=(
                known_rows[sample_id].problem_id
                if sample_id in known_rows
                else f"p-{index}"
            ),
            sample_kind=(
                known_rows[sample_id].sample_kind
                if sample_id in known_rows
                else SampleKind.NATURAL
            ),
            topic=(known_rows[sample_id].topic if sample_id in known_rows else Topic.GREEDY),
            rating_band=(
                known_rows[sample_id].rating_band
                if sample_id in known_rows
                else RatingBand.FOUNDATION
            ),
        )
        for index, sample_id in enumerate(sample_ids)
    )
    return BenchmarkConfig(
        benchmark_id=benchmark_id,
        selection_hash="a" * 64,
        corpus_hash="b" * 64,
        ordered_sample_ids=sample_ids,
        sample_specs=resolved_specs,
        generation_sample_ids=generation_ids,
        audit_sample_ids=audit_ids,
        model="hy3",
        endpoint_identity="https://hy3.example/v1",
        generator_prompt_version="solution-trace-v1",
        logic_review_prompt_version="logic-reviewer-v1",
        adversarial_review_prompt_version="adversarial-reviewer-v1",
        arbiter_prompt_version="arbiter-v1",
        model_parameters=(BenchmarkParameter(name="reasoning_effort", value="high"),),
        code_revision="revision-1",
        judge_image_digest=f"sha256:{'c' * 64}",
        metric_version="task6-metrics-v1",
        chart_version="task6-chart-v1",
        seed=17,
        bootstrap_replicates=bootstrap_replicates,
        remote_attempt_budget=budget,
        formal=formal,
        verified_data_evidence=verified_data_evidence,
    )


def formal_profile(
    *, benchmark_id: str = "formal-profile"
) -> tuple[BenchmarkConfig, tuple[MetricObservation, ...]]:
    specs: list[BenchmarkSampleSpec] = []
    observations: list[MetricObservation] = []
    problems: list[tuple[str, Topic, RatingBand]] = []
    for topic_index, topic in enumerate(Topic):
        for band_index, band in enumerate(RatingBand):
            for problem_number in range(2):
                problems.append(
                    (f"problem-{topic_index}-{band_index}-{problem_number}", topic, band)
                )

    def add(
        sample_id: str,
        problem: tuple[str, Topic, RatingBand],
        kind: SampleKind,
        taxonomy: ErrorTaxonomy | None,
    ) -> None:
        problem_id, topic, rating_band = problem
        invalid = taxonomy is not None
        specs.append(
            BenchmarkSampleSpec(
                sample_id=sample_id,
                problem_id=problem_id,
                sample_kind=kind,
                topic=topic,
                rating_band=rating_band,
            )
        )
        observations.append(
            MetricObservation(
                sample_id=sample_id,
                problem_id=problem_id,
                sample_kind=kind,
                topic=topic,
                rating_band=rating_band,
                gold_final_correct=kind is not SampleKind.CONTROLLED_WRONG,
                gold_process_valid=not invalid,
                gold_first_error_step=1 if invalid else None,
                gold_taxonomy=taxonomy,
                predicted_final_correct=kind is not SampleKind.CONTROLLED_WRONG,
                predicted_process_valid=not invalid,
                predicted_first_error_step=1 if invalid else None,
                predicted_taxonomy=taxonomy,
                needs_human_review=False,
                primary_review_agreement=True,
                arbitration_used=False,
            )
        )

    for index, problem_entry in enumerate(problems):
        add(f"gold-{index}", problem_entry, SampleKind.GOLD, None)
    taxonomies = tuple(ErrorTaxonomy)
    for index in range(60):
        add(
            f"wrong-{index}",
            problems[index // 2],
            SampleKind.CONTROLLED_WRONG,
            taxonomies[index % len(taxonomies)],
        )
    for index in range(15):
        add(
            f"paradox-{index}",
            problems[index * 2],
            SampleKind.PARADOX,
            taxonomies[index % len(taxonomies)],
        )
    for index in range(60):
        add(f"natural-{index}", problems[index // 2], SampleKind.NATURAL, None)
    ordered = tuple(spec.sample_id for spec in specs)
    generation = tuple(
        spec.sample_id for spec in specs if spec.sample_kind is SampleKind.NATURAL
    )
    evidence = VerifiedDataEvidence(
        evidence_kind="verified-task7-replay",
        artifact_path="verified/task7-replay.json",
        artifact_hash="d" * 64,
        selection_hash="a" * 64,
        corpus_hash="b" * 64,
    )
    return (
        config(
            benchmark_id=benchmark_id,
            sample_ids=ordered,
            generation_ids=generation,
            audit_ids=ordered,
            budget=390,
            formal=True,
            sample_specs=tuple(specs),
            verified_data_evidence=evidence,
            bootstrap_replicates=1,
        ),
        tuple(observations),
    )


def test_config_freezes_static_lower_bound_and_exact_formal_profile() -> None:
    frozen, _ = formal_profile()

    assert frozen.static_attempt_lower_bound == 390
    with pytest.raises(ValidationError, match="static remote-attempt lower bound"):
        BenchmarkConfig.model_validate(
            {
                **frozen.model_dump(mode="json"),
                "remote_attempt_budget": 389,
            }
        )
    with pytest.raises(ValidationError):
        frozen.remote_attempt_budget = 500


def test_formal_config_rejects_tiny_self_authored_profile_even_with_evidence() -> None:
    evidence = VerifiedDataEvidence(
        evidence_kind="verified-task7-replay",
        artifact_path="verified/fake.json",
        artifact_hash="d" * 64,
        selection_hash="a" * 64,
        corpus_hash="b" * 64,
    )

    with pytest.raises(ValidationError, match="formal profile"):
        config(formal=True, verified_data_evidence=evidence)

    valid, _ = formal_profile()
    with pytest.raises(ValidationError, match="verified-data evidence"):
        BenchmarkConfig.model_validate(
            {**valid.model_dump(mode="json"), "verified_data_evidence": None}
        )


def test_returned_observation_must_match_frozen_problem_kind_and_strata(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    benchmark_config = config(
        benchmark_id="identity-mismatch",
        sample_ids=("n1",),
        audit_ids=("n1",),
        budget=2,
    )
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id="identity-mismatch")
    budget = RemoteAttemptBudget(limit=2, event_sink=ledger.record)
    wrong = literal_rows()[0].model_copy(update={"sample_kind": SampleKind.GOLD})

    with pytest.raises(ValueError, match="frozen sample specification"):
        BenchmarkRunner(
            config=benchmark_config,
            artifacts=artifacts,
            budget=budget,
            ledger=ledger,
        ).run(lambda _sample_id, _observer: wrong)


def test_formal_complete_run_needs_external_verified_evidence_gate(
    tmp_path: Path,
) -> None:
    benchmark_config, rows = formal_profile(benchmark_id="formal-gated")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id="formal-gated")
    budget = RemoteAttemptBudget(
        limit=390, event_sink=ledger.record, benchmark_id="formal-gated"
    )
    by_id = {row.sample_id: row for row in rows}

    def execute(
        sample_id: str, observer: Callable[[Hy3AttemptContext], None]
    ) -> MetricObservation:
        spec = next(item for item in benchmark_config.sample_specs if item.sample_id == sample_id)
        attempts = 3 if spec.sample_kind is SampleKind.NATURAL else 2
        for retry_number in range(1, attempts + 1):
            observer(
                Hy3AttemptContext(
                    operation="formal-operation",
                    phase="request",
                    retry_number=retry_number,
                )
            )
        return by_id[sample_id]

    self_authored = BenchmarkRunner(
        config=benchmark_config,
        artifacts=artifacts,
        budget=budget,
        ledger=ledger,
    ).run(execute)

    assert self_authored.complete is True
    assert self_authored.formal_evidence_verified is False
    assert self_authored.formal_eligible is False


def test_trusted_verifier_can_confirm_hash_bound_formal_evidence(
    tmp_path: Path,
) -> None:
    benchmark_config, rows = formal_profile(benchmark_id="formal-verified")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id="formal-verified")
    budget = RemoteAttemptBudget(
        limit=390, event_sink=ledger.record, benchmark_id="formal-verified"
    )
    by_id = {row.sample_id: row for row in rows}
    verified_paths: list[str] = []

    def execute(
        sample_id: str, observer: Callable[[Hy3AttemptContext], None]
    ) -> MetricObservation:
        spec = next(item for item in benchmark_config.sample_specs if item.sample_id == sample_id)
        for retry_number in range(
            1, 4 if spec.sample_kind is SampleKind.NATURAL else 3
        ):
            observer(
                Hy3AttemptContext(
                    operation="formal-operation",
                    phase="request",
                    retry_number=retry_number,
                )
            )
        return by_id[sample_id]

    def verify(config_value, evidence, observations) -> bool:  # type: ignore[no-untyped-def]
        verified_paths.append(evidence.artifact_path)
        return (
            config_value.corpus_hash == evidence.corpus_hash
            and evidence.artifact_hash == "d" * 64
            and len(observations) == 165
        )

    report = BenchmarkRunner(
        config=benchmark_config,
        artifacts=artifacts,
        budget=budget,
        ledger=ledger,
        formal_evidence_verifier=verify,
    ).run(execute)

    assert report.formal_evidence_verified is True
    assert report.formal_eligible is True
    assert verified_paths == ["verified/task7-replay.json"]


def test_budget_reservation_is_atomic_under_concurrency() -> None:
    budget = RemoteAttemptBudget(limit=7)
    context = Hy3AttemptContext(
        operation="generator-v1",
        phase="request",
        retry_number=1,
    )

    def reserve(_index: int) -> int | None:
        try:
            return budget.reserve(context, sample_id="sample")
        except BudgetExceededError:
            return None

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = tuple(pool.map(reserve, range(20)))

    assert sorted(item for item in results if item is not None) == list(range(1, 8))
    assert sum(item is None for item in results) == 13
    assert budget.used == 7


def test_ledger_rejects_cross_benchmark_event_identity(tmp_path: Path) -> None:
    ledger = ArtifactAttemptLedger(
        ArtifactStore(tmp_path / "artifacts"), benchmark_id="expected-benchmark"
    )

    with pytest.raises(ValueError, match="benchmark identity"):
        ledger.record(
            LedgerEvent(
                benchmark_id="other-benchmark",
                sequence=1,
                sample_id="n1",
                operation="logic-reviewer-v1",
                phase="request",
                retry_number=1,
            )
        )


def test_attempt_501_never_reaches_transport() -> None:
    transport_calls = 0
    budget = RemoteAttemptBudget(limit=500, consumed_attempts=500)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(500)

    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="test-key"),
        transport=httpx.MockTransport(handler),
        attempt_observer=budget.for_sample("sample-501"),
    )

    with pytest.raises(BudgetExceededError, match="remote attempt budget exhausted"):
        hy3.generate(problem())

    assert transport_calls == 0
    assert budget.used == 500


def test_budget_partial_is_immutable_and_never_formal(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    benchmark_config = config(benchmark_id="bench-partial")
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id="bench-partial")
    budget = RemoteAttemptBudget(
        limit=4, event_sink=ledger.record, benchmark_id="bench-partial"
    )
    runner = BenchmarkRunner(
        config=benchmark_config,
        artifacts=artifacts,
        budget=budget,
        ledger=ledger,
    )
    rows = {row.sample_id: row for row in literal_rows()}

    def execute(
        sample_id: str,
        observer: Callable[[Hy3AttemptContext], None],
    ):
        attempts = 3 if sample_id == "n1" else 2
        for retry_number in range(1, attempts + 1):
            observer(
                Hy3AttemptContext(
                    operation="logic-reviewer-v1",
                    phase="request",
                    retry_number=retry_number,
                )
            )
        return rows[sample_id]

    report = runner.run(execute)

    assert report.status is BenchmarkStatus.PARTIAL
    assert report.complete is False
    assert report.formal_eligible is False
    assert report.completed_sample_ids == ("n1",)
    assert report.remote_attempts_used == 4
    assert (artifacts.root / "benchmarks/bench-partial/config.json").is_file()
    assert (artifacts.root / "benchmarks/bench-partial/observations/n1.json").is_file()
    assert (artifacts.root / "benchmarks/bench-partial/report.json").is_file()
    assert (artifacts.root / "benchmarks/bench-partial/ledger-index.json").is_file()
    assert not (artifacts.root / "benchmarks/bench-partial/metrics.json").exists()
    with pytest.raises(ArtifactExistsError):
        runner.run(execute)


def test_complete_run_persists_metrics_intervals_breakpoint_chart_and_hashes(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    rows = tuple(
        literal_rows()[index].model_copy(
            update={"sample_id": sample_id, "problem_id": f"problem-{sample_id}"}
        )
        for index, sample_id in enumerate(("n1", "n2", "n3"))
    )
    rows = (
        rows[0].model_copy(update={"rating_band": RatingBand.FOUNDATION}),
        rows[1].model_copy(update={"rating_band": RatingBand.INTERMEDIATE}),
        rows[2].model_copy(update={"rating_band": RatingBand.ADVANCED}),
    )
    benchmark_config = config(
        benchmark_id="bench-complete",
        sample_ids=("n1", "n2", "n3"),
        audit_ids=("n1", "n2", "n3"),
        budget=6,
        sample_specs=tuple(
            BenchmarkSampleSpec(
                sample_id=row.sample_id,
                problem_id=row.problem_id,
                sample_kind=row.sample_kind,
                topic=row.topic,
                rating_band=row.rating_band,
            )
            for row in rows
        ),
    )
    ledger = ArtifactAttemptLedger(artifacts, benchmark_id="bench-complete")
    budget = RemoteAttemptBudget(
        limit=6,
        event_sink=ledger.record,
        benchmark_id="bench-complete",
    )
    by_id = {row.sample_id: row for row in rows}

    def execute(
        sample_id: str,
        observer: Callable[[Hy3AttemptContext], None],
    ):
        for operation in ("logic-reviewer-v1", "adversarial-reviewer-v1"):
            observer(
                Hy3AttemptContext(operation=operation, phase="request", retry_number=1)
            )
        return by_id[sample_id]

    report = BenchmarkRunner(
        config=benchmark_config,
        artifacts=artifacts,
        budget=budget,
        ledger=ledger,
    ).run(execute)

    assert report.status is BenchmarkStatus.COMPLETE
    assert report.complete is True
    assert report.formal_eligible is False
    names = {entry.name for entry in report.artifacts}
    assert names == {
        "config",
        "observation:n1",
        "observation:n2",
        "observation:n3",
        "ledger_index",
        "metrics",
        "confidence_intervals",
        "breakpoint",
        "chart:overall_metrics",
    }
    for entry in report.artifacts:
        assert sha256_json(artifacts.read_json(entry.path)) == entry.content_hash
    assert artifacts.read_json(
        "benchmarks/bench-complete/breakpoint.json"
    )["not_evaluable"] is False
