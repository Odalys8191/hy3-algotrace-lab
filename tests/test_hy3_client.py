from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import FunctionType, MethodType, ModuleType

import httpx
import pytest

from hy3_algotrace.contracts import ErrorTaxonomy, ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.hy3_client import (
    Hy3AttemptContext,
    Hy3Client,
    Hy3Config,
    Hy3ResponseError,
    JsonResponseCache,
    build_cache_key,
    endpoint_identity,
    generation_input,
)


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
                linked
                for linked in (current.__cause__, current.__context__)
                if linked is not None
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
                pending.extend(cell.cell_contents for cell in current.__closure__)
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
        pending.extend(
            getattr(current, slot)
            for slot in slots
            if hasattr(current, slot)
        )
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

    config = Hy3Config.from_env()

    assert config.base_url == "https://hy3.example/v1"
    assert config.model == "hy3"
    assert "sk-environment-secret" not in repr(config)


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
        ),
        Hy3AttemptContext(
            operation="solution-trace-v1",
            phase="request",
            retry_number=2,
        ),
        Hy3AttemptContext(
            operation="solution-trace-v1",
            phase="schema_repair",
            retry_number=1,
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
    assert (
        getattr(captured.value, "error_taxonomy", None)
        is ErrorTaxonomy.FORMAT_SCHEMA
    )


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
            linked
            for linked in (error.__cause__, error.__context__)
            if linked is not None
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
    assert (
        captured.value.error_taxonomy is ErrorTaxonomy.FORMAT_SCHEMA
    )


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
