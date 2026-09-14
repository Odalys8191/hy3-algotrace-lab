from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import FunctionType, MethodType, ModuleType

import httpx
import pytest
from test_artifacts_catalog import bundle

from hy3_algotrace.contracts import ErrorTaxonomy, ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.hy3_client import (
    Hy3AttemptContext,
    Hy3AttemptOutcome,
    Hy3Client,
    Hy3Config,
    Hy3ConfigurationError,
    Hy3ResponseError,
    Hy3SpendLimitError,
    Hy3TokenLimitError,
    Hy3Usage,
    Hy3ValidationIssue,
    JsonResponseCache,
    RmbCostGuard,
    TokenQuotaGuard,
    build_cache_key,
    endpoint_identity,
    generation_input,
    sanitize_json_schema,
)
from hy3_algotrace.prompts import GENERATOR_PROMPT_VERSION


def problem() -> ProblemRecord:
    return ProblemRecord(
        problem_id="cf-1-a",
        title="Maximum",
        statement_en="Print the maximum of two integers.",
        source_url="https://codeforces.com/problemset/problem/1/A",
        attribution="Codeforces",
        cf_contest_id=1,
        cf_index="A",
        cf_tags=("implementation",),
        source_split="validation",
        topic=Topic.CONSTRUCTION_SIMULATION,
        rating=1200,
        time_limit_ms=1000,
        memory_limit_mb=256,
        public_tests=(),
        hidden_tests=(),
        generated_tests=(),
        content_hash="a" * 64,
    )


def valid_trace_payload() -> dict[str, object]:
    return {
        "schema_version": "1.2",
        "trace_id": "trace-1",
        "problem_id": "cf-1-a",
        "language": "cpp17",
        "steps": [
            {
                "schema_version": "1.2",
                "step_id": "understand",
                "step_number": 1,
                "stage": "problem_understanding",
                "claim": "There are two integers.",
                "rationale": "This follows from the statement.",
                "depends_on": [],
                "status": "correct",
            }
        ],
        "problem_understanding": "Read two integers.",
        "algorithm": "Print their maximum.",
        "correctness_argument": "A maximum comparison returns the larger input.",
        "time_complexity": "O(1)",
        "space_complexity": "O(1)",
        "edge_cases": ["Equal values."],
        "code": "int main() { return 0; }",
    }


def completion(content: object, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def valid_verdict_payload(reviewer_id: str) -> dict[str, object]:
    problem_bundle = bundle()
    return {
        "schema_version": "1.2",
        "reviewer_id": reviewer_id,
        "trace_id": problem_bundle.gold_trace.trace_id,
        "material_error": False,
        "explanation": "No material error found.",
        "per_step_reviews": [
            {
                "schema_version": "1.2",
                "step_id": step.step_id,
                "status": "correct",
                "material": False,
                "taxonomy": None,
                "evidence": "Checked.",
                "confidence": 1.0,
            }
            for step in problem_bundle.gold_trace.steps
        ],
        "error_taxonomy": None,
        "first_error_step_id": None,
        "confidence": 1.0,
    }


def client(
    tmp_path: Path,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    api_key: str = "test-key",
) -> Hy3Client:
    return Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key=api_key),
        cache=JsonResponseCache(tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
    )


def exception_graph_text(error: BaseException) -> str:
    """Serialize reachable exception state and library traceback locals for leak tests."""

    serialized: list[str] = []
    pending: list[object] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, str):
            serialized.append(current)
            continue
        if isinstance(current, bytes):
            serialized.append(current.decode(errors="replace"))
            continue
        if isinstance(current, BaseException):
            serialized.extend((str(current), repr(current)))
            pending.extend(current.args)
            pending.extend(vars(current).values())
            pending.extend(
                linked for linked in (current.__cause__, current.__context__) if linked is not None
            )
            traceback = current.__traceback__
            while traceback is not None:
                if Path(traceback.tb_frame.f_code.co_filename).name == "hy3_client.py":
                    pending.append(traceback.tb_frame.f_locals)
                traceback = traceback.tb_next
            continue
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
            continue
        if isinstance(current, (list, tuple, set, frozenset)):
            pending.extend(current)
            continue
        if isinstance(current, FunctionType):
            if current.__closure__ is not None:
                for cell in current.__closure__:
                    try:
                        value = cell.cell_contents
                    except ValueError:
                        # An explicitly deleted closure binding holds no object.
                        # Continue inspecting every other reachable, live cell.
                        continue
                    pending.append(value)
            continue
        if isinstance(current, MethodType):
            pending.extend((current.__self__, current.__func__))
            continue
        if isinstance(current, (ModuleType, type, int, float, bool, type(None))):
            continue
        serialized.append(repr(current))
        try:
            pending.extend(vars(current).values())
        except TypeError:
            pass
        slots = getattr(type(current), "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        pending.extend(getattr(current, slot) for slot in slots if hasattr(current, slot))
    return "\n".join(serialized)


def test_cache_key_is_canonical_and_excludes_endpoint_credentials(tmp_path: Path) -> None:
    first = build_cache_key(
        model="hy3",
        endpoint="https://alice:secret@hy3.example/v1?api_key=secret",
        prompt_version="generate-v1",
        parameters={"temperature": 0.2, "reasoning_effort": "high"},
        canonical_input={"b": 2, "a": 1},
    )
    second = build_cache_key(
        model="hy3",
        endpoint="https://bob:different@hy3.example/v1?api_key=different",
        prompt_version="generate-v1",
        parameters={"reasoning_effort": "high", "temperature": 0.2},
        canonical_input={"a": 1, "b": 2},
    )

    assert first == second
    assert len(first) == 64
    assert endpoint_identity("https://alice:secret@hy3.example/v1?api_key=secret") == (
        "https://hy3.example/v1"
    )
    assert "secret" not in first

    cache = JsonResponseCache(tmp_path / "cache")
    assert cache.put(first, {"result": 1}) is True
    assert cache.put(first, {"result": 2}) is False
    assert cache.get(first) == {"result": 1}


def test_environment_interface_defaults_model_and_does_not_repr_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HY3_BASE_URL", "https://hy3.example/v1")
    monkeypatch.setenv("HY3_API_KEY", "sk-environment-secret")
    monkeypatch.delenv("HY3_MODEL", raising=False)
    monkeypatch.delenv("HY3_TIMEOUT_SECONDS", raising=False)

    config = Hy3Config.from_env()

    assert config.base_url == "https://hy3.example/v1"
    assert config.model == "hy3"
    assert config.timeout_seconds == 60.0
    assert "sk-environment-secret" not in repr(config)


def test_environment_timeout_reaches_outbound_generation_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HY3_BASE_URL", "https://hy3.example/v1")
    monkeypatch.setenv("HY3_API_KEY", "test-key")
    monkeypatch.setenv("HY3_TIMEOUT_SECONDS", "300")
    observed_timeouts: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed_timeouts.append(request.extensions["timeout"]["read"])
        return completion(json.dumps(valid_trace_payload()))

    hy3 = Hy3Client(Hy3Config.from_env(), transport=httpx.MockTransport(handler))
    try:
        assert hy3.generate(problem()).trace_id == "trace-1"
    finally:
        hy3.close()
    assert observed_timeouts == [300.0]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "", "bad-timeout"])
def test_invalid_environment_timeout_fails_before_http(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HY3_BASE_URL", "https://hy3.example/v1")
    monkeypatch.setenv("HY3_API_KEY", "test-key")
    monkeypatch.setenv("HY3_TIMEOUT_SECONDS", value)

    with pytest.raises(Hy3ConfigurationError, match="timeout"):
        Hy3Config.from_env()


def test_generate_uses_high_reasoning_and_cache_without_hidden_inputs(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return completion(json.dumps(valid_trace_payload()))

    record = problem().model_copy(
        update={
            "hidden_tests": (
                ContractTestCase(
                    test_id="hidden-secret",
                    input_data="classified input",
                    expected_output="classified output",
                ),
            )
        }
    )
    hy3 = client(tmp_path, handler)

    first = hy3.generate(record)
    second = hy3.generate(record)

    assert first == second
    assert first.trace_id == "trace-1"
    assert len(requests) == 1
    assert requests[0]["model"] == "hy3"
    assert requests[0]["reasoning_effort"] == "high"
    serialized_request = json.dumps(requests[0])
    assert "classified input" not in serialized_request
    assert "classified output" not in serialized_request
    assert "hidden-secret" not in serialized_request
    assert generation_input(record)["public_tests"] == []


def test_review_and_arbiter_requests_exclude_oracle_and_hidden_evidence(tmp_path: Path) -> None:
    problem_bundle = bundle()
    observed: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed.append(body)
        user = json.loads(body["messages"][1]["content"])
        verdict = {
            "schema_version": "1.2",
            "reviewer_id": user["reviewer_id"],
            "trace_id": problem_bundle.gold_trace.trace_id,
            "material_error": False,
            "explanation": "No material error found.",
            "per_step_reviews": [
                {
                    "schema_version": "1.2",
                    "step_id": step.step_id,
                    "status": "correct",
                    "material": False,
                    "taxonomy": None,
                    "evidence": "Checked from the public problem and supplied trace.",
                    "confidence": 1.0,
                }
                for step in problem_bundle.gold_trace.steps
            ],
            "error_taxonomy": None,
            "first_error_step_id": None,
            "confidence": 1.0,
        }
        return completion(json.dumps(verdict))

    hy3 = client(tmp_path, handler)
    try:
        logic = hy3.review(
            problem_bundle.record,
            problem_bundle.oracle,
            problem_bundle.gold_trace,
            reviewer_id="logic-reviewer",
        )
        adversarial = hy3.review(
            problem_bundle.record,
            problem_bundle.oracle,
            problem_bundle.gold_trace,
            reviewer_id="adversarial-reviewer",
        )
        hy3.arbitrate(
            problem_bundle.record,
            problem_bundle.oracle,
            problem_bundle.gold_trace,
            (logic, adversarial),
        )
    finally:
        hy3.close()

    assert len(observed) == 3
    forbidden_values = {
        problem_bundle.oracle.reference_solution_hash,
        *problem_bundle.oracle.key_invariants,
        *problem_bundle.oracle.known_traps,
        *problem_bundle.oracle.adversarial_cases,
        *problem_bundle.oracle.decisive_facts,
        *(test.input_data for test in problem_bundle.record.hidden_tests),
        *(test.expected_output for test in problem_bundle.record.hidden_tests),
    }
    for request in observed:
        serialized = json.dumps(request, sort_keys=True)
        user = json.loads(request["messages"][1]["content"])
        assert "oracle" not in user
        assert "hidden_tests" not in user["problem"]
        assert all(value not in serialized for value in forbidden_values if value)


def test_generate_sends_structure_only_json_schema(tmp_path: Path) -> None:
    observed_schemas: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        observed_schemas.append(body["response_format"]["json_schema"]["schema"])
        return completion(json.dumps(valid_trace_payload()))

    client(tmp_path, handler).generate(problem())

    assert len(observed_schemas) == 1
    serialized = json.dumps(observed_schemas[0])
    for keyword in ("minLength", "maxLength", "pattern", "exclusiveMinimum", "minimum"):
        assert keyword not in serialized, keyword
    schema = observed_schemas[0]
    assert schema["type"] == "object"
    assert "code" in schema["properties"]
    assert "steps" in schema["properties"]


def test_sanitize_json_schema_keeps_structure_and_drops_bounds() -> None:
    raw = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "minLength": 1, "maxLength": 64},
            "count": {"type": "integer", "exclusiveMinimum": 0, "minimum": 1},
            "stage": {"enum": ["a", "b"]},
            "flag": {"const": True},
        },
        "required": ["code"],
        "additionalProperties": False,
        "$defs": {
            "Step": {
                "type": "object",
                "properties": {"claim": {"type": "string", "minLength": 1}},
            }
        },
        "$ref_placeholder": {"type": "string"},
    }

    sanitized = sanitize_json_schema(raw)

    assert sanitized == {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "count": {"type": "integer"},
            "stage": {"enum": ["a", "b"]},
            "flag": {"const": True},
        },
        "required": ["code"],
        "additionalProperties": False,
        "$defs": {"Step": {"type": "object", "properties": {"claim": {"type": "string"}}}},
    }
    # The caller's schema object is not mutated.
    assert raw["properties"]["code"] == {"type": "string", "minLength": 1, "maxLength": 64}


def test_generate_rejects_wrong_problem_identity_before_cache(tmp_path: Path) -> None:
    payload = valid_trace_payload() | {"problem_id": "other-problem"}

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(json.dumps(payload))

    with pytest.raises(Hy3ResponseError, match="problem identity"):
        client(tmp_path, handler).generate(problem())

    assert not list((tmp_path / "cache").glob("*.json"))


def test_generate_allows_exactly_one_schema_repair(tmp_path: Path) -> None:
    responses = iter(
        [
            completion("not json"),
            completion(json.dumps(valid_trace_payload())),
        ]
    )
    request_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(request.content.decode())
        return next(responses)

    result = client(tmp_path, handler).generate(problem())

    assert result.trace_id == "trace-1"
    assert len(request_bodies) == 2
    assert "repair" in request_bodies[1].lower()


def test_review_identity_failure_is_repaired_with_whitelisted_attempt_diagnostics(
    tmp_path: Path,
) -> None:
    problem_bundle = bundle()
    private_marker = "provider-private-data-that-must-not-be-persisted"
    invalid = valid_verdict_payload("wrong-reviewer")
    valid = valid_verdict_payload("logic-reviewer")
    responses = iter(
        (
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": json.dumps(invalid)},
                            "finish_reason": "length",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 13,
                        "completion_tokens": 17,
                        "total_tokens": 30,
                        "provider_debug": private_marker,
                    },
                    "provider_debug": private_marker,
                },
            ),
            httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": json.dumps(valid)},
                            "finish_reason": "stop",
                        }
                    ],
                    "provider_debug": private_marker,
                },
            ),
        )
    )
    request_bodies: list[dict[str, object]] = []
    contexts: list[Hy3AttemptContext] = []
    outcomes: list[Hy3AttemptOutcome] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(json.loads(request.content))
        return next(responses)

    def observe(context: Hy3AttemptContext) -> int:
        contexts.append(context)
        return len(contexts)

    guard = RmbCostGuard(limit_rmb="1", max_output_tokens=1_000)
    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        parameters={"reasoning_effort": "high", "max_tokens": 1_000},
        transport=httpx.MockTransport(handler),
        attempt_observer=observe,
        attempt_outcome_observer=outcomes.append,
        cost_guard=guard,
    )
    try:
        verdict = hy3.review(
            problem_bundle.record,
            problem_bundle.oracle,
            problem_bundle.gold_trace,
            reviewer_id="logic-reviewer",
        )
    finally:
        hy3.close()

    assert verdict.reviewer_id == "logic-reviewer"
    assert [context.phase for context in contexts] == ["request", "schema_repair"]
    assert all(context.reviewer == "logic-reviewer" for context in contexts)
    assert all(context.reservation_upper_bound_rmb is not None for context in contexts)
    assert [outcome.category for outcome in outcomes] == ["validation_error", "accepted"]
    assert outcomes[0].sequence == 1
    assert outcomes[0].http_status == 200
    assert outcomes[0].finish_reason == "length"
    assert outcomes[0].usage == Hy3Usage(
        prompt_tokens=13,
        completion_tokens=17,
        total_tokens=30,
    )
    assert outcomes[0].validation_issues == (
        Hy3ValidationIssue(path="reviewer_id", code="identity_mismatch"),
    )
    assert outcomes[1].usage is None
    assert outcomes[1].usage_status == "missing_or_invalid"
    serialized = repr((contexts, outcomes))
    assert private_marker not in serialized
    assert "wrong-reviewer" not in serialized
    initial_system_prompt = request_bodies[0]["messages"][0]["content"]
    assert "reviewer_id" in initial_system_prompt
    assert "trace_id" in initial_system_prompt
    assert "per_step_reviews" in initial_system_prompt
    allowed_step_ids = json.dumps(
        [step.step_id for step in problem_bundle.gold_trace.steps],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert f"Allowed trace step IDs: {allowed_step_ids}" in initial_system_prompt
    repair_instruction = request_bodies[1]["messages"][-1]["content"]
    assert f"Allowed trace step IDs: {allowed_step_ids}" in repair_instruction


def test_adversarial_identity_repair_failure_reports_exact_step_coverage_issue(
    tmp_path: Path,
) -> None:
    problem_bundle = bundle()
    identity_invalid = valid_verdict_payload("logic-reviewer")
    coverage_invalid = valid_verdict_payload("adversarial-reviewer")
    coverage_invalid["per_step_reviews"] = coverage_invalid["per_step_reviews"] * 2
    responses = iter(
        (
            completion(json.dumps(identity_invalid)),
            completion(json.dumps(coverage_invalid)),
        )
    )
    outcomes: list[Hy3AttemptOutcome] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        transport=httpx.MockTransport(handler),
        attempt_outcome_observer=outcomes.append,
    )
    with pytest.raises(Hy3ResponseError, match="cover every trace step") as captured:
        hy3.review(
            problem_bundle.record,
            problem_bundle.oracle,
            problem_bundle.gold_trace,
            reviewer_id="adversarial-reviewer",
        )

    assert captured.value.diagnostic is not None
    assert captured.value.diagnostic.category == "validation_error"
    assert [outcome.category for outcome in outcomes] == [
        "validation_error",
        "validation_error",
    ]
    assert outcomes[0].validation_issues == (
        Hy3ValidationIssue(path="reviewer_id", code="identity_mismatch"),
    )
    assert outcomes[1].validation_issues == (
        Hy3ValidationIssue(path="per_step_reviews", code="step_coverage_mismatch"),
    )


def test_schema_diagnostic_replaces_provider_field_names_and_omits_input_values(
    tmp_path: Path,
) -> None:
    secret_field = "PRIVATE_PROVIDER_FIELD_NAME"
    secret_value = "PRIVATE_PROVIDER_INPUT_VALUE"
    invalid = valid_trace_payload() | {secret_field: secret_value}
    responses = iter(
        (
            completion(json.dumps(invalid)),
            completion(json.dumps(valid_trace_payload())),
        )
    )
    outcomes: list[Hy3AttemptOutcome] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    result = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        transport=httpx.MockTransport(handler),
        attempt_outcome_observer=outcomes.append,
    ).generate(problem())

    assert result.trace_id == "trace-1"
    assert outcomes[0].validation_issues == (Hy3ValidationIssue(path="*", code="extra_forbidden"),)
    serialized = repr(outcomes)
    assert secret_field not in serialized
    assert secret_value not in serialized


def test_attempt_observer_counts_retry_and_repair_but_not_cache_hit(
    tmp_path: Path,
) -> None:
    responses = iter(
        (
            httpx.Response(503, json={"error": {"message": "busy"}}),
            completion("not json"),
            completion(json.dumps(valid_trace_payload())),
        )
    )
    contexts: list[Hy3AttemptContext] = []
    transport_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return next(responses)

    hy3 = Hy3Client(
        Hy3Config(
            base_url="https://hy3.example/v1",
            api_key="test-key",
            max_attempts=3,
        ),
        cache=JsonResponseCache(tmp_path / "cache"),
        transport=httpx.MockTransport(handler),
        attempt_observer=contexts.append,
    )

    first = hy3.generate(problem())
    second = hy3.generate(problem())

    assert first == second
    assert transport_calls == 3
    assert contexts == [
        Hy3AttemptContext(
            operation="solution-trace-v1",
            phase="request",
            retry_number=1,
            reviewer="generator",
        ),
        Hy3AttemptContext(
            operation="solution-trace-v1",
            phase="request",
            retry_number=2,
            reviewer="generator",
        ),
        Hy3AttemptContext(
            operation="solution-trace-v1",
            phase="schema_repair",
            retry_number=1,
            reviewer="generator",
        ),
    ]


def test_generate_stops_after_one_failed_schema_repair(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion("still not json")

    with pytest.raises(Hy3ResponseError, match="schema") as captured:
        client(tmp_path, handler).generate(problem())

    assert calls == 2
    assert getattr(captured.value, "error_taxonomy", None) is ErrorTaxonomy.FORMAT_SCHEMA


def test_transient_status_is_retried_before_success(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return completion(json.dumps(valid_trace_payload()))

    result = client(tmp_path, handler).generate(problem())

    assert result.trace_id == "trace-1"
    assert calls == 2


def test_transport_failure_retains_full_reservation_and_emits_no_raw_error(
    tmp_path: Path,
) -> None:
    private_marker = "transport-private-detail"
    contexts: list[Hy3AttemptContext] = []
    outcomes: list[Hy3AttemptOutcome] = []

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(private_marker, request=request)

    def observe(context: Hy3AttemptContext) -> int:
        contexts.append(context)
        return 7

    guard = RmbCostGuard(limit_rmb="1", max_output_tokens=1_000)
    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only", max_attempts=1),
        parameters={"reasoning_effort": "high", "max_tokens": 1_000},
        transport=httpx.MockTransport(handler),
        attempt_observer=observe,
        attempt_outcome_observer=outcomes.append,
        cost_guard=guard,
    )
    with pytest.raises(Hy3ResponseError) as captured:
        hy3.generate(problem())

    assert captured.value.diagnostic is not None
    assert captured.value.diagnostic.category == "transport_error"
    assert captured.value.diagnostic.reviewer == "generator"
    assert len(contexts) == len(outcomes) == 1
    assert outcomes[0].sequence == 7
    assert outcomes[0].category == "transport_error"
    assert outcomes[0].usage_status == "missing_or_invalid"
    assert outcomes[0].charged_attempt_upper_bound_rmb == contexts[0].reservation_upper_bound_rmb
    assert outcomes[0].remaining_upper_bound_rmb == contexts[0].remaining_upper_bound_rmb
    assert private_marker not in repr(outcomes)


def test_http_failure_diagnostic_keeps_only_status_and_known_finish_reason(
    tmp_path: Path,
) -> None:
    private_marker = "provider-error-body"
    outcomes: list[Hy3AttemptOutcome] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "choices": [{"finish_reason": "provider-specific-secret-reason"}],
                "error": {"message": private_marker},
            },
        )

    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        transport=httpx.MockTransport(handler),
        attempt_outcome_observer=outcomes.append,
    )
    with pytest.raises(Hy3ResponseError) as captured:
        hy3.generate(problem())

    assert captured.value.diagnostic is not None
    assert captured.value.diagnostic.http_status == 422
    assert captured.value.diagnostic.finish_reason == "other"
    assert len(outcomes) == 1
    assert outcomes[0].category == "http_error"
    assert outcomes[0].http_status == 422
    assert outcomes[0].finish_reason == "other"
    assert private_marker not in repr(outcomes)


def test_http_errors_redact_api_keys_and_response_secrets(tmp_path: Path) -> None:
    secret = "sk-super-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": f"invalid bearer {secret}"}},
        )

    with pytest.raises(Hy3ResponseError) as captured:
        client(tmp_path, handler, api_key=secret).generate(problem())

    message = str(captured.value)
    assert secret not in message
    assert "[REDACTED]" in message


def test_transport_errors_do_not_retain_secret_in_exception_chain(tmp_path: Path) -> None:
    secret = "sk-transport-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"Bearer {secret} refused", request=request)

    with pytest.raises(Hy3ResponseError) as captured:
        client(tmp_path, handler, api_key=secret).generate(problem())

    reachable: list[BaseException] = []
    pending: list[BaseException] = [captured.value]
    while pending:
        error = pending.pop()
        if error in reachable:
            continue
        reachable.append(error)
        pending.extend(
            linked for linked in (error.__cause__, error.__context__) if linked is not None
        )

    serialized = "\n".join(
        text
        for error in reachable
        for text in (str(error), repr(error), repr(error.args), repr(vars(error)))
    )
    assert secret not in serialized
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_structured_response_echoing_api_key_is_rejected_before_cache(
    tmp_path: Path,
) -> None:
    secret = "sk-cache-secret"
    payload = valid_trace_payload() | {"trace_id": secret}

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(json.dumps(payload))

    with pytest.raises(Hy3ResponseError) as captured:
        client(tmp_path, handler, api_key=secret).generate(problem())

    assert secret not in str(captured.value)
    assert not list((tmp_path / "cache").glob("*.json"))


def test_context_validation_error_traceback_locals_do_not_retain_api_key(
    tmp_path: Path,
) -> None:
    secret = "sk-context-secret"
    payload = valid_trace_payload() | {"problem_id": secret}

    def handler(request: httpx.Request) -> httpx.Response:
        return completion(json.dumps(payload))

    with pytest.raises(Hy3ResponseError) as captured:
        client(tmp_path, handler, api_key=secret).generate(problem())

    assert secret not in exception_graph_text(captured.value)
    assert not list((tmp_path / "cache").glob("*.json"))


def test_failed_repair_traceback_locals_do_not_retain_api_key(tmp_path: Path) -> None:
    secret = "sk-repaired-response-secret"
    responses = iter(
        [
            completion(json.dumps({"trace_id": f"Bearer {secret}"})),
            completion(json.dumps({"problem_id": secret})),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    with pytest.raises(Hy3ResponseError) as captured:
        client(tmp_path, handler, api_key=secret).generate(problem())

    assert secret not in exception_graph_text(captured.value)
    assert captured.value.error_taxonomy is ErrorTaxonomy.FORMAT_SCHEMA


def test_schema_repair_request_redacts_secret_from_response_and_validation_error(
    tmp_path: Path,
) -> None:
    secret = "sk-repair-token"
    invalid = {
        "schema_version": "1.2",
        "trace_id": f"Bearer {secret}",
        "problem_id": "cf-1-a",
    }
    responses = iter(
        [
            completion(json.dumps(invalid)),
            completion(json.dumps(valid_trace_payload())),
        ]
    )
    request_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_bodies.append(request.content.decode())
        return next(responses)

    result = client(tmp_path, handler, api_key=secret).generate(problem())

    assert result.problem_id == problem().problem_id
    assert len(request_bodies) == 2
    assert secret not in request_bodies[1]
    assert "[REDACTED]" in request_bodies[1]


def test_exception_graph_checks_live_cells_after_an_empty_cell() -> None:
    def closure():
        empty = "deleted"
        retained = "detect-this-retained-value"

        def nested():
            return empty, retained

        assert nested.__closure__ is not None
        del nested.__closure__[0].cell_contents
        return nested

    error = RuntimeError("outer")
    error.payload = {"nested": closure()}
    error.__cause__ = ValueError("cause-sentinel")
    text = exception_graph_text(error)
    assert "detect-this-retained-value" in text
    assert "cause-sentinel" in text


def test_explicit_parameters_drive_http_and_cache_hash_without_implicit_defaults(tmp_path):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return completion(json.dumps(valid_trace_payload()))

    parameters = {"temperature": 0.25, "max_tokens": 8192}
    cache = JsonResponseCache(tmp_path / "parameter-cache")
    with_client = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="test-only"),
        parameters=parameters,
        cache=cache,
        transport=httpx.MockTransport(handler),
    )
    parameters["temperature"] = 0.99
    with_client.generate(problem())
    frozen = {"temperature": 0.25, "max_tokens": 8192}
    assert {
        key: value
        for key, value in requests[0].items()
        if key not in {"messages", "model", "response_format"}
    } == frozen
    key = build_cache_key(
        model="hy3",
        endpoint="https://hy3.example/v1",
        prompt_version=GENERATOR_PROMPT_VERSION,
        parameters=frozen,
        canonical_input=generation_input(problem()),
    )
    assert cache.get(key) is not None
    assert (
        cache.get(
            build_cache_key(
                model="hy3",
                endpoint="https://hy3.example/v1",
                prompt_version=GENERATOR_PROMPT_VERSION,
                parameters=parameters,
                canonical_input=generation_input(problem()),
            )
        )
        is None
    )
    with_client.close()


def test_rmb_cost_guard_blocks_before_request_when_conservative_cap_is_exhausted() -> None:
    requests: list[httpx.Request] = []
    attempts: list[Hy3AttemptContext] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        user = json.loads(json.loads(request.content)["messages"][1]["content"])
        return completion(json.dumps(valid_trace_payload() | {"trace_id": user["trace_id"]}))

    guard = RmbCostGuard(limit_rmb="0.08", max_output_tokens=10_000)
    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        parameters={"reasoning_effort": "high", "max_tokens": 10_000},
        transport=httpx.MockTransport(handler),
        attempt_observer=attempts.append,
        cost_guard=guard,
    )
    try:
        hy3.generate(problem(), trace_id="first")
        with pytest.raises(Hy3SpendLimitError, match="spend cap"):
            hy3.generate(problem(), trace_id="second")
    finally:
        hy3.close()

    assert len(requests) == 1
    assert len(attempts) == 1
    assert 0 < guard.charged_upper_bound_rmb <= 0.08


def test_rmb_cost_guard_carries_predecessor_charge_before_any_request() -> None:
    guard = RmbCostGuard(
        limit_rmb="15",
        max_output_tokens=10_000,
        initial_charged_upper_bound_rmb="15",
    )

    with pytest.raises(Hy3SpendLimitError, match="spend cap"):
        guard.reserve({"model": "hy3"})

    assert guard.charged_upper_bound_rmb == 15
    assert guard.remaining_upper_bound_rmb == 0


def test_rmb_cost_guard_reconciles_valid_usage_and_releases_unused_reserve() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = valid_trace_payload() | {
            "trace_id": json.loads(json.loads(request.content)["messages"][1]["content"])[
                "trace_id"
            ]
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100},
            },
        )

    guard = RmbCostGuard(limit_rmb="0.05", max_output_tokens=10_000)
    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        parameters={"reasoning_effort": "high", "max_tokens": 10_000},
        transport=httpx.MockTransport(handler),
        cost_guard=guard,
    )
    try:
        hy3.generate(problem(), trace_id="first")
        hy3.generate(problem(), trace_id="second")
    finally:
        hy3.close()

    assert len(requests) == 2
    assert guard.charged_upper_bound_rmb == pytest.approx(0.001)


def test_token_quota_guard_blocks_before_request_and_reconciles_reported_usage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = valid_trace_payload() | {
            "trace_id": json.loads(json.loads(request.content)["messages"][1]["content"])[
                "trace_id"
            ]
        }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 100,
                    "total_tokens": 200,
                },
            },
        )

    guard = TokenQuotaGuard(limit_tokens=5_000_000, max_output_tokens=12_000)
    hy3 = Hy3Client(
        Hy3Config(base_url="https://hy3.example/v1", api_key="unit-only"),
        parameters={"reasoning_effort": "high", "max_tokens": 12_000},
        transport=httpx.MockTransport(handler),
        token_guard=guard,
    )
    try:
        hy3.generate(problem(), trace_id="first")
        with pytest.raises(Hy3TokenLimitError, match="token quota"):
            guard.reserve({"oversized": "x" * 4_990_000})
    finally:
        hy3.close()

    assert len(requests) == 1
    assert guard.charged_upper_bound_tokens == 200
    assert guard.remaining_upper_bound_tokens == 4_999_800


def test_token_quota_guard_keeps_full_reservation_when_usage_is_missing() -> None:
    guard = TokenQuotaGuard(limit_tokens=20_000, max_output_tokens=12_000)
    reservation = guard.reserve({"model": "hy3"})
    reserved = guard.charged_upper_bound_tokens

    state = guard.settle(reservation, None)

    assert state.charged_attempt_upper_bound_tokens == reserved
    assert guard.charged_upper_bound_tokens == reserved
    assert guard.remaining_upper_bound_tokens == 20_000 - reserved


@pytest.mark.parametrize(
    "parameters",
    [
        {"model": "substitute"},
        {"messages": "injected"},
        {"response_format": "text"},
        {"stream": True},
        {"temperature": float("nan")},
        {"temperature": []},
    ],
)
def test_parameters_cannot_override_identity_or_request_envelope(parameters):
    with pytest.raises(Hy3ConfigurationError):
        Hy3Client(
            Hy3Config(base_url="https://hy3.example/v1", api_key="test-only"),
            parameters=parameters,
            transport=httpx.MockTransport(lambda request: None),
        )
