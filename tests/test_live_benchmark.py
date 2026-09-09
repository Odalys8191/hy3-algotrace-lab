from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from test_artifacts_catalog import bundle
from test_benchmark import config as benchmark_config

from hy3_algotrace import live_benchmark
from hy3_algotrace.artifacts import ArtifactStore
from hy3_algotrace.benchmark import ArtifactAttemptLedger, BenchmarkRunner, RemoteAttemptBudget
from hy3_algotrace.benchmark_cli import main as cli_main
from hy3_algotrace.benchmark_models import BenchmarkSampleSpec, SampleKind
from hy3_algotrace.catalog import ProblemCatalog
from hy3_algotrace.contracts import JudgeEvidence, JudgeStatus
from hy3_algotrace.hy3_client import Hy3Config
from hy3_algotrace.prompts import (
    ADVERSARIAL_REVIEW_PROMPT_VERSION,
    ARBITER_PROMPT_VERSION,
    GENERATOR_PROMPT_VERSION,
    LOGIC_REVIEW_PROMPT_VERSION,
)


def setup_live(tmp_path: Path, *, budget: int = 6):  # type: ignore[no-untyped-def]
    problem_bundle = bundle()
    catalog = ProblemCatalog([problem_bundle])
    inputs = live_benchmark.LiveInputs(
        samples=tuple(
            live_benchmark.LiveSampleInput(sample_id=sid) for sid in ("natural-1", "natural-2")
        )
    )
    record = problem_bundle.record
    cfg = benchmark_config(
        sample_ids=("natural-1", "natural-2"),
        generation_ids=("natural-1", "natural-2"),
        audit_ids=("natural-1", "natural-2"),
        sample_specs=tuple(
            BenchmarkSampleSpec(
                sample_id=sid,
                problem_id=record.problem_id,
                sample_kind=SampleKind.NATURAL,
                topic=record.topic,
                rating_band=record.rating_band,
            )
            for sid in ("natural-1", "natural-2")
        ),
        budget=budget,
    ).model_copy(
        update={
            "selection_hash": live_benchmark.catalog_hash(catalog),
            "corpus_hash": inputs.content_hash,
            "generator_prompt_version": GENERATOR_PROMPT_VERSION,
            "logic_review_prompt_version": LOGIC_REVIEW_PROMPT_VERSION,
            "adversarial_review_prompt_version": ADVERSARIAL_REVIEW_PROMPT_VERSION,
            "arbiter_prompt_version": ARBITER_PROMPT_VERSION,
        }
    )
    store = ArtifactStore(tmp_path / "artifacts")
    return problem_bundle, catalog, inputs, cfg, store


def test_real_client_makes_two_uncached_generations_and_counts_all_requests(tmp_path: Path) -> None:
    b, catalog, inputs, cfg, store = setup_live(tmp_path)
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        user = json.loads(payload["messages"][1]["content"])
        if payload["response_format"]["json_schema"]["name"] == "SolutionTrace":
            assert "oracle" not in user and "hidden_tests" not in user
            assert b.record.hidden_tests[0].input_data not in payload["messages"][1]["content"]
            result = b.gold_trace.model_dump(mode="json")
        else:
            result = {
                "schema_version": "1.2",
                "reviewer_id": user["reviewer_id"],
                "trace_id": b.gold_trace.trace_id,
                "material_error": False,
                "explanation": "No material error found.",
                "per_step_reviews": [
                    {
                        "schema_version": "1.2",
                        "step_id": s.step_id,
                        "status": "correct",
                        "material": False,
                        "taxonomy": None,
                        "evidence": "Checked.",
                        "confidence": 1.0,
                    }
                    for s in b.gold_trace.steps
                ],
                "error_taxonomy": None,
                "first_error_step_id": None,
                "confidence": 1.0,
            }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})

    class Judge:
        def judge(self, problem, cpp_source):  # type: ignore[no-untyped-def]
            return JudgeEvidence(compile_status=JudgeStatus.AC, verdict=JudgeStatus.AC)

    execute = live_benchmark.LiveExecutor(
        config=cfg,
        catalog=catalog,
        inputs=inputs,
        artifacts=store,
        hy3_config=Hy3Config(base_url=cfg.endpoint_identity, model=cfg.model, api_key="unit-only"),
        judge=Judge(),
        image_reference="judge@" + cfg.judge_image_digest,
        transport=httpx.MockTransport(handle),
    )
    ledger = ArtifactAttemptLedger(store, benchmark_id=cfg.benchmark_id)
    budget = RemoteAttemptBudget(limit=6, event_sink=ledger.record, benchmark_id=cfg.benchmark_id)
    report = BenchmarkRunner(config=cfg, artifacts=store, budget=budget, ledger=ledger).run(execute)
    assert report.complete and report.remote_attempts_used == 6
    assert report.formal_eligible is False
    assert len(requests) == 6
    assert [e.sample_id for e in ledger.events] == ["natural-1"] * 3 + ["natural-2"] * 3
    for sid in cfg.ordered_sample_ids:
        evidence = store.read_json(
            Path("benchmarks") / cfg.benchmark_id / "live-evidence" / sid / "result.json"
        )
        assert evidence["judge"]["verdict"] == JudgeStatus.AC.value
        assert evidence["trace"]["problem_id"] == b.record.problem_id
        assert evidence["formal_eligibility"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"model": "other"},
        {"corpus_hash": "0" * 64},
        {"selection_hash": "0" * 64},
        {"logic_review_prompt_version": "invented"},
        {"judge_image_digest": "sha256:" + "0" * 64},
        {"formal": True},
    ],
)
def test_frozen_mismatch_fails_before_network(tmp_path: Path, change: dict[str, object]) -> None:
    _, catalog, inputs, cfg, store = setup_live(tmp_path)
    with pytest.raises(ValueError):
        live_benchmark.LiveExecutor(
            config=cfg.model_copy(update=change),
            catalog=catalog,
            inputs=inputs,
            artifacts=store,
            hy3_config=Hy3Config(
                base_url=cfg.endpoint_identity, model=cfg.model, api_key="unit-only"
            ),
            judge=object(),
            image_reference="judge@" + cfg.judge_image_digest,
        )


def test_infrastructure_failure_stops_before_review_and_preserves_safe_marker(
    tmp_path: Path,
) -> None:
    b, catalog, inputs, cfg, store = setup_live(tmp_path)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": b.gold_trace.model_dump_json()}}]}
        )

    class Judge:
        def judge(self, problem, cpp_source):  # type: ignore[no-untyped-def]
            return JudgeEvidence(
                compile_status=JudgeStatus.INFRASTRUCTURE_ERROR,
                verdict=JudgeStatus.INFRASTRUCTURE_ERROR,
                diagnostics="PRIVATE_RUNTIME_DIAGNOSTIC",
            )

    execute = live_benchmark.LiveExecutor(
        config=cfg,
        catalog=catalog,
        inputs=inputs,
        artifacts=store,
        hy3_config=Hy3Config(base_url=cfg.endpoint_identity, model=cfg.model, api_key="unit-only"),
        judge=Judge(),
        image_reference="judge@" + cfg.judge_image_digest,
        transport=httpx.MockTransport(handle),
    )
    with pytest.raises(live_benchmark.LiveExecutionError):
        execute("natural-1", lambda context: None)
    assert len(calls) == 1
    failure = store.read_json(
        Path("benchmarks") / cfg.benchmark_id / "live-evidence" / "natural-1" / "failure.json"
    )
    assert failure["phase"] == "judge"
    assert "PRIVATE_RUNTIME_DIAGNOSTIC" not in json.dumps(failure)


def test_cli_assembles_adapter_without_python_executor_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from hy3_algotrace.benchmark_models import MetricObservation

    b, _, _, cfg, store = setup_live(tmp_path)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(cfg.model_dump_json())
    called = []

    def build(**kwargs):  # type: ignore[no-untyped-def]
        called.append(kwargs)

        def execute(sid, observer):  # type: ignore[no-untyped-def]
            return MetricObservation(
                sample_id=sid,
                problem_id=b.record.problem_id,
                sample_kind=SampleKind.NATURAL,
                topic=b.record.topic,
                rating_band=b.record.rating_band,
                predicted_final_correct=True,
                predicted_process_valid=True,
                needs_human_review=False,
                primary_review_agreement=True,
                arbitration_used=False,
            )

        return execute

    monkeypatch.setattr(live_benchmark, "build_live_executor", build)
    result = cli_main(
        [
            "run",
            "--config",
            str(cfg_path),
            "--artifact-root",
            str(store.root),
            "--catalog-root",
            str(tmp_path / "catalog"),
            "--live-inputs",
            str(tmp_path / "inputs.json"),
        ]
    )
    assert result == 0 and len(called) == 1
    assert json.loads(capsys.readouterr().out)["formal_eligible"] is False


def test_cli_live_failure_finalizes_ledger_and_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from hy3_algotrace.hy3_client import Hy3AttemptContext

    _, _, _, cfg, store = setup_live(tmp_path)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(cfg.model_dump_json())

    def build(**kwargs):  # type: ignore[no-untyped-def]
        def execute(sid, observer):  # type: ignore[no-untyped-def]
            observer(
                Hy3AttemptContext(
                    operation=GENERATOR_PROMPT_VERSION, phase="request", retry_number=1
                )
            )
            raise live_benchmark.LiveExecutionError("DO_NOT_PRINT_PRIVATE_DETAILS")

        return execute

    monkeypatch.setattr(live_benchmark, "build_live_executor", build)
    result = cli_main(
        [
            "run",
            "--config",
            str(cfg_path),
            "--artifact-root",
            str(store.root),
            "--catalog-root",
            str(tmp_path / "catalog"),
            "--live-inputs",
            str(tmp_path / "inputs.json"),
        ]
    )
    assert result == 2
    assert "DO_NOT_PRINT_PRIVATE_DETAILS" not in str(capsys.readouterr())
    root = Path("benchmarks") / cfg.benchmark_id
    assert len(store.read_json(root / "ledger-index.json")["event_hashes"]) == 1
    assert store.read_json(root / "failure.json")["formal_eligibility"] is False
    assert not (store.root / root / "metrics.json").exists()


def test_retry_attempts_stop_at_budget_without_completed_metrics(tmp_path: Path) -> None:
    b, catalog, inputs, cfg, store = setup_live(tmp_path)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        # Valid JSON but invalid schema triggers the client's repair cycle.
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    execute = live_benchmark.LiveExecutor(
        config=cfg,
        catalog=catalog,
        inputs=inputs,
        artifacts=store,
        hy3_config=Hy3Config(base_url=cfg.endpoint_identity, model=cfg.model, api_key="unit-only"),
        judge=object(),
        image_reference="judge@" + cfg.judge_image_digest,
        transport=httpx.MockTransport(handle),
    )
    ledger = ArtifactAttemptLedger(store, benchmark_id=cfg.benchmark_id)
    budget = RemoteAttemptBudget(limit=1, event_sink=ledger.record, benchmark_id=cfg.benchmark_id)
    from hy3_algotrace.benchmark import BudgetExceededError

    with pytest.raises(BudgetExceededError):
        execute("natural-1", budget.for_sample("natural-1"))
    assert len(calls) == 1 and len(ledger.events) == 1
    assert not (store.root / "benchmarks" / cfg.benchmark_id / "metrics.json").exists()


def test_static_validation_does_not_print_private_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, _, cfg, _ = setup_live(tmp_path)
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(cfg.model_dump_json())

    def invalid_catalog(path):  # type: ignore[no-untyped-def]
        raise ValueError("PRIVATE_ORACLE_SENTINEL")

    monkeypatch.setattr(ProblemCatalog, "from_directory", invalid_catalog)
    result = cli_main(
        [
            "validate-live-inputs",
            "--config",
            str(cfg_path),
            "--catalog-root",
            str(tmp_path),
            "--live-inputs",
            str(tmp_path / "inputs.json"),
        ]
    )
    captured = capsys.readouterr()
    assert result == 2
    assert "PRIVATE_ORACLE_SENTINEL" not in captured.out + captured.err
    assert json.loads(captured.out)["inputs_valid"] is False


def test_runner_persists_partial_report_when_live_retry_budget_exhausts(tmp_path: Path) -> None:
    _, catalog, inputs, cfg, store = setup_live(tmp_path)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "temporarily unavailable"})

    execute = live_benchmark.LiveExecutor(
        config=cfg,
        catalog=catalog,
        inputs=inputs,
        artifacts=store,
        hy3_config=Hy3Config(
            base_url=cfg.endpoint_identity, model=cfg.model, api_key="unit-only", max_attempts=10
        ),
        judge=object(),
        image_reference="judge@" + cfg.judge_image_digest,
        transport=httpx.MockTransport(handle),
    )
    ledger = ArtifactAttemptLedger(store, benchmark_id=cfg.benchmark_id)
    budget = RemoteAttemptBudget(limit=6, event_sink=ledger.record, benchmark_id=cfg.benchmark_id)
    report = BenchmarkRunner(config=cfg, artifacts=store, budget=budget, ledger=ledger).run(execute)
    assert not report.complete and report.remote_attempts_used == 6
    assert len(calls) == 6
    root = Path("benchmarks") / cfg.benchmark_id
    assert len(store.read_json(root / "ledger-index.json")["event_hashes"]) == 6
    assert store.read_json(root / "report.json")["complete"] is False
    assert not (store.root / root / "metrics.json").exists()


@pytest.mark.parametrize("command", ["validate-live-inputs", "run"])
@pytest.mark.parametrize("invalid", ["missing", "json", "schema"])
def test_live_config_failure_is_safe_before_adapter_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    invalid: str,
) -> None:
    config_path = tmp_path / "config.json"
    if invalid == "json":
        config_path.write_text("PRIVATE_CONFIG_SENTINEL")
    elif invalid == "schema":
        config_path.write_text(json.dumps({"model": "PRIVATE_CONFIG_SENTINEL"}))

    def unexpected_build(**kwargs):  # type: ignore[no-untyped-def]
        pytest.fail("invalid config reached the live adapter")

    monkeypatch.setattr(live_benchmark, "build_live_executor", unexpected_build)
    args = [command, "--config", str(config_path), "--catalog-root", str(tmp_path),
            "--live-inputs", str(tmp_path / "inputs.json")]
    if command == "run":
        args.extend(["--artifact-root", str(tmp_path / "artifacts")])
    result = cli_main(args)
    captured = capsys.readouterr()
    assert result == 2
    assert "PRIVATE_CONFIG_SENTINEL" not in captured.out + captured.err
    payload = json.loads(captured.out)
    if command == "run":
        assert payload["status"] == "preflight_failed"
        assert payload["formal_eligible"] is False
    else:
        assert payload["inputs_valid"] is False
        assert payload["docker_checked"] is False


@pytest.mark.parametrize("failure", ["root_is_file", "existing_run", "failure_marker"])
def test_live_artifact_failure_is_safe_and_preserves_existing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    _, _, _, cfg, store = setup_live(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text(cfg.model_dump_json())
    artifact_root = store.root
    if failure == "root_is_file":
        artifact_root = tmp_path / "not-a-directory"
        preserved = artifact_root
    else:
        name = "config.json" if failure == "existing_run" else "failure.json"
        preserved = artifact_root / "benchmarks" / cfg.benchmark_id / name
        preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"PRIVATE_EXISTING_ARTIFACT_SENTINEL")

    def build(**kwargs):  # type: ignore[no-untyped-def]
        def execute(sid, observer):  # type: ignore[no-untyped-def]
            if failure == "failure_marker":
                raise live_benchmark.LiveExecutionError("PRIVATE_EXECUTION_SENTINEL")
            pytest.fail("unusable artifact output reached sample execution")

        return execute

    monkeypatch.setattr(live_benchmark, "build_live_executor", build)
    result = cli_main([
        "run", "--config", str(config_path), "--artifact-root", str(artifact_root),
        "--catalog-root", str(tmp_path), "--live-inputs", str(tmp_path / "inputs.json"),
    ])
    captured = capsys.readouterr()
    assert result == 2
    assert "PRIVATE_" not in captured.out + captured.err
    assert json.loads(captured.out)["formal_eligible"] is False
    assert preserved.read_bytes() == b"PRIVATE_EXISTING_ARTIFACT_SENTINEL"
