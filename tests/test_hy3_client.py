from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from hy3_algotrace.contracts import ProblemRecord, Topic
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.hy3_client import (
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


def test_generate_stops_after_one_failed_schema_repair(tmp_path: Path) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return completion("still not json")

    with pytest.raises(Hy3ResponseError, match="schema"):
        client(tmp_path, handler).generate(problem())

    assert calls == 2


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
