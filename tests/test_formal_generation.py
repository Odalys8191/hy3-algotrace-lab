"""Local transport tests only: no credentials, remote service or Judge required."""

from __future__ import annotations

import json

import httpx
import pytest
from test_dataset_corpus import _problem_record
from test_formal_lifecycle import DIGEST, ROOT, freeze
from test_hy3_client import completion, valid_trace_payload

from hy3_algotrace.artifacts import ArtifactStore
from hy3_algotrace.benchmark import BudgetExceededError
from hy3_algotrace.formal_generation import FormalNaturalGenerator
from hy3_algotrace.formal_lifecycle import FORMAL_ENDPOINT, LifecycleError
from hy3_algotrace.hy3_client import Hy3AttemptContext, Hy3Config, Hy3ResponseError
from hy3_algotrace.prompts import GENERATOR_PROMPT_VERSION


def session(tmp_path, handler, **config_changes):
    intent, selection, bundles, corpus = freeze(tmp_path)
    generator = FormalNaturalGenerator(
        intent=intent,
        selection=selection,
        pending_corpus=corpus,
        bundle_manifest=bundles,
        data_root=tmp_path,
        repo_root=ROOT,
        artifacts=ArtifactStore(tmp_path / "runs"),
        hy3_config=Hy3Config(
            **(
                dict(
                    base_url=FORMAL_ENDPOINT,
                    **{"api_key": "placeholder"},
                    model="hy3",
                    timeout_seconds=600,
                )
                | config_changes
            )
        ),
        judge_image_digest=DIGEST,
        transport=httpx.MockTransport(handler),
    )
    row = selection.entries[0]
    problem = _problem_record(
        problem_id=row.problem_id, source_split=row.source_split, topic=row.topic, rating=row.rating
    )
    return generator, intent, problem


def response_for(request):
    visible = json.loads(json.loads(request.content)["messages"][1]["content"])
    return completion(
        json.dumps(
            valid_trace_payload()
            | {
                "problem_id": visible["problem_id"],
                "trace_id": visible["trace_id"],
            }
        )
    )


def test_mock_success_reserves_before_transport_and_shares_ledger_across_samples(tmp_path):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        sequence = len(requests)
        event = (
            tmp_path
            / "runs"
            / "benchmarks"
            / intent.benchmark_id
            / "ledger"
            / f"{sequence:06d}.json"
        )
        assert json.loads(event.read_bytes())["sequence"] == sequence
        assert generator.budget.used == sequence
        return response_for(request)

    generator, intent, problem = session(tmp_path, handler)
    for sample_id in intent.natural_sample_ids[:2]:
        assert generator.generate(sample_id, problem).trace_id == sample_id
    assert generator.budget.used == 2
    assert generator.ledger.events == generator.budget.events
    for request in requests:
        assert {
            key: value
            for key, value in request.items()
            if key not in {"messages", "model", "response_format"}
        } == {parameter.name: parameter.value for parameter in intent.model_parameters}
        visible = request["messages"][1]["content"]
        assert "hidden_tests" not in visible and "generated_tests" not in visible
    index = generator.ledger.finalize()
    assert len(json.loads((tmp_path / "runs" / index.path).read_bytes())["event_hashes"]) == 2
    with pytest.raises(LifecycleError):
        generator.generate(intent.natural_sample_ids[0], problem)
    assert len(requests) == 2
    # A run marker is create-only, so reconstruction cannot reset consumed attempts.
    with pytest.raises(Exception, match="already exists"):
        session(tmp_path, handler)


def test_mock_repair_and_transient_retry_charge_one_shared_budget(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        assert generator.budget.used == len(requests)
        if len(requests) == 1:
            return httpx.Response(503)
        if len(requests) == 2:
            return completion("{")
        return response_for(request)

    generator, intent, problem = session(tmp_path, handler)
    generator.generate(intent.natural_sample_ids[0], problem)
    assert [(event.phase, event.retry_number) for event in generator.ledger.events] == [
        ("request", 1),
        ("request", 2),
        ("schema_repair", 1),
    ]
    assert generator.budget.used == 3


@pytest.mark.parametrize("failure", ["http", "repair", "output_identity"])
def test_mock_failure_persists_partial_and_prohibits_repeating_sample(tmp_path, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "http":
            return httpx.Response(400)
        if failure == "repair":
            return completion("{")
        return completion(json.dumps(valid_trace_payload()))

    generator, intent, problem = session(tmp_path, handler)
    sample_id = intent.natural_sample_ids[0]
    with pytest.raises(Hy3ResponseError):
        generator.generate(sample_id, problem)
    failure_path = (
        tmp_path
        / "runs"
        / "benchmarks"
        / intent.benchmark_id
        / "natural"
        / sample_id
        / "failure.json"
    )
    failure_record = json.loads(failure_path.read_bytes())
    assert failure_record["remote_attempts_used"] == len(calls) == generator.budget.used
    assert failure_record["intent_hash"] == intent.intent_hash
    assert failure_record["formal_eligibility"] is False
    assert not failure_path.with_name("trace.json").exists()
    with pytest.raises(LifecycleError):
        generator.generate(sample_id, problem)


def test_budget_exhaustion_before_repair_never_transmits_501st_request(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        assert generator.budget.used == 500
        return completion("{")

    generator, intent, problem = session(tmp_path, handler)
    # Reserve actual local events in the very same budget/ledger; no counter reset.
    for _ in range(499):
        generator.budget.reserve(
            Hy3AttemptContext(GENERATOR_PROMPT_VERSION, "request", 1),
            sample_id=intent.natural_sample_ids[1],
        )
    with pytest.raises(BudgetExceededError):
        generator.generate(intent.natural_sample_ids[0], problem)
    assert len(calls) == 1 and generator.budget.used == 500
    assert len(generator.ledger.events) == 500


@pytest.mark.parametrize("change", ["sample", "problem", "A", "source", "parameters"])
def test_changed_identity_makes_zero_transport_requests(tmp_path, monkeypatch, change):
    calls = []
    generator, intent, problem = session(tmp_path, lambda request: calls.append(request))
    sample_id = intent.natural_sample_ids[0]
    if change == "sample":
        sample_id = "unreserved-sample"
    elif change == "problem":
        problem = problem.model_copy(update={"title": "changed"})
    elif change == "A":
        generator._capability.intent = intent.model_copy(update={"intent_hash": "0" * 64})
    elif change == "parameters":
        generator._capability.intent = intent.model_copy(update={"model_parameters": ()})
    else:
        from hy3_algotrace import formal_lifecycle

        original = formal_lifecycle.current_code_identity
        monkeypatch.setattr(
            formal_lifecycle,
            "current_code_identity",
            lambda root: original(root).model_copy(update={"tree_hash": "0" * 64}),
        )
    with pytest.raises(ValueError):
        generator.generate(sample_id, problem)
    assert calls == [] and generator.budget.used == 0


def test_a_is_revalidated_between_http_retry_attempts(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        generator._capability.intent = intent.model_copy(update={"intent_hash": "0" * 64})
        return httpx.Response(503)

    generator, intent, problem = session(tmp_path, handler)
    with pytest.raises(ValueError):
        generator.generate(intent.natural_sample_ids[0], problem)
    assert len(calls) == generator.budget.used == 1


@pytest.mark.parametrize(
    "config_changes",
    [
        {"model": "hy3-preview"},
        {"base_url": "https://other.example/v1"},
        {"timeout_seconds": 60},
        {"max_attempts": 4},
    ],
)
def test_runtime_configuration_mismatch_is_rejected_before_transport(tmp_path, config_changes):
    calls = []
    with pytest.raises(ValueError):
        session(tmp_path, lambda request: calls.append(request), **config_changes)
    assert calls == []
