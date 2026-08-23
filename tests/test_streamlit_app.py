from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from test_run_service import valid_trace

from hy3_algotrace.api_models import RunCreateRequest, RunMode
from hy3_algotrace.streamlit_app import (
    RUN_MODE_LABELS,
    AlgoTraceApiClient,
    ApiClientError,
    AuditTraceInputError,
    build_run_request,
    build_run_view,
    default_api_base_url,
    should_offer_refresh,
)

PROBLEM_LIST = {
    "schema_version": "1.2",
    "problems": [
        {
            "schema_version": "1.2",
            "problem_id": "cf-123-a",
            "title": "Add One",
            "topic": "greedy",
            "rating": 1200,
        }
    ],
}
PROBLEM_DETAIL = {
    "schema_version": "1.2",
    "problem_id": "cf-123-a",
    "title": "Add One",
    "statement_en": "Add one.",
    "source_url": "https://codeforces.com/problemset/problem/123/A",
    "attribution": "Codeforces",
    "source": "codeforces",
    "cf_contest_id": 123,
    "cf_index": "A",
    "cf_tags": ["greedy"],
    "source_split": "validation",
    "is_description_translated": False,
    "input_file": "",
    "output_file": "",
    "topic": "greedy",
    "rating": 1200,
    "language": "cpp17",
    "time_limit_ms": 1000,
    "memory_limit_mb": 256,
    "public_tests": [{"schema_version": "1.2", "test_id": "public-1", "input_data": "1\n"}],
    "content_hash": "a" * 64,
}
COMPLETED_RUN = {
    "schema_version": "1.2",
    "run_id": "run-1",
    "status": "completed",
    "failure": None,
    "degraded_failure": None,
    "report": {
        "schema_version": "1.2",
        "run_id": "run-1",
        "problem_id": "cf-123-a",
        "mode": "solve_and_audit",
        "trace": {
            "schema_version": "1.2",
            "trace_id": "trace-1",
            "problem_id": "cf-123-a",
            "language": "cpp17",
            "steps": [
                {
                    "schema_version": "1.2",
                    "step_id": "step-1",
                    "step_number": 1,
                    "stage": "algorithm_design",
                    "claim": "Add one.",
                    "rationale": "This matches the task.",
                    "depends_on": [],
                    "status": "correct",
                }
            ],
            "problem_understanding": "Read x.",
            "algorithm": "Add one.",
            "correctness_argument": "The result is x+1.",
            "time_complexity": "O(1)",
            "space_complexity": "O(1)",
            "edge_cases": ["negative x"],
            "code": "int main(){}",
        },
        "audit": {
            "schema_version": "1.2",
            "run_id": "run-1",
            "problem_id": "cf-123-a",
            "trace_id": "trace-1",
            "judge": {
                "schema_version": "1.2",
                "compile_status": "ac",
                "verdict": "wa",
                "tests": [
                    {
                        "schema_version": "1.2",
                        "test_number": 1,
                        "status": "wa",
                        "time_ms": 4,
                        "memory_kb": 128,
                    }
                ],
            },
            "final_correct": False,
            "process_score": 72.0,
            "process_valid": False,
            "final_error_taxonomy": "algorithm_logic",
            "first_material_error_step_id": "step-1",
            "needs_human_review": True,
        },
    },
}


def test_http_client_uses_only_the_four_public_routes_and_strict_dtos() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/api/v1/problems":
            return httpx.Response(200, json=PROBLEM_LIST)
        if request.method == "GET" and request.url.path == "/api/v1/problems/cf-123-a":
            return httpx.Response(200, json=PROBLEM_DETAIL)
        if request.method == "POST" and request.url.path == "/api/v1/runs":
            return httpx.Response(
                202,
                json={"schema_version": "1.2", "run_id": "run-1", "status": "queued"},
            )
        if request.method == "GET" and request.url.path == "/api/v1/runs/run-1":
            return httpx.Response(200, json=COMPLETED_RUN)
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = AlgoTraceApiClient("https://local.example", client=transport)
        listing = client.list_problems()
        detail = client.get_problem("cf-123-a")
        accepted = client.create_run(
            RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
        )
        completed = client.get_run(accepted.run_id)

    assert listing.problems[0].title == "Add One"
    assert detail.statement_en == "Add one."
    assert completed.status.value == "completed"
    assert requests == [
        ("GET", "/api/v1/problems"),
        ("GET", "/api/v1/problems/cf-123-a"),
        ("POST", "/api/v1/runs"),
        ("GET", "/api/v1/runs/run-1"),
    ]


def test_completed_run_view_contains_timeline_code_judge_and_audit_decision() -> None:
    from hy3_algotrace.api_models import RunReadResponse

    view = build_run_view(RunReadResponse.model_validate(COMPLETED_RUN))

    assert view.model_dump(mode="json") == {
        "schema_version": "1.2",
        "run_id": "run-1",
        "status": "completed",
        "timeline": [
            {
                "schema_version": "1.2",
                "step_id": "step-1",
                "step_number": 1,
                "stage": "algorithm_design",
                "claim": "Add one.",
                "rationale": "This matches the task.",
                "status": "correct",
            }
        ],
        "code": "int main(){}",
        "compile_status": "ac",
        "judge_verdict": "wa",
        "judge_tests": [
            {
                "schema_version": "1.2",
                "test_number": 1,
                "status": "wa",
                "time_ms": 4,
                "memory_kb": 128,
            }
        ],
        "first_error_step_id": "step-1",
        "taxonomy": "algorithm_logic",
        "process_score": 72.0,
        "needs_human_review": True,
        "failure_message": None,
    }


def test_pasted_structured_trace_builds_strict_audit_request() -> None:
    assert RUN_MODE_LABELS == {
        "Hy3 生成并审计": RunMode.SOLVE_AND_AUDIT,
        "粘贴结构化解答审计": RunMode.AUDIT,
    }
    trace = valid_trace()

    request = build_run_request(
        mode=RunMode.AUDIT,
        problem_id=trace.problem_id,
        structured_trace_json=trace.model_dump_json(),
    )

    assert request.mode is RunMode.AUDIT
    assert request.trace == trace


def test_pasted_trace_reports_safe_validation_and_identity_errors() -> None:
    with pytest.raises(AuditTraceInputError, match="valid SolutionTrace JSON"):
        build_run_request(
            mode=RunMode.AUDIT,
            problem_id="cf-123-a",
            structured_trace_json="{not json}",
        )
    with pytest.raises(AuditTraceInputError, match="selected problem"):
        build_run_request(
            mode=RunMode.AUDIT,
            problem_id="cf-123-a",
            structured_trace_json=valid_trace(problem_id="cf-999-z").model_dump_json(),
        )


def test_nonterminal_status_offers_refresh_but_terminal_status_does_not() -> None:
    from hy3_algotrace.api_models import RunReadResponse

    queued = RunReadResponse(run_id="run-queued", status="queued")
    completed = RunReadResponse.model_validate(COMPLETED_RUN)

    assert should_offer_refresh(queued) is True
    assert should_offer_refresh(completed) is False


@pytest.mark.parametrize(
    ("operation", "message"),
    (
        ("list", "Problem list unavailable."),
        ("detail", "Problem details unavailable."),
        ("create", "Run creation unavailable."),
        ("refresh", "Run status unavailable."),
    ),
)
def test_http_failures_are_fixed_safe_messages_without_url_or_userinfo(
    operation: str, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"connection failed for {request.url}", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as transport:
        client = AlgoTraceApiClient("https://user:secret@internal.example", client=transport)
        with pytest.raises(ApiClientError) as caught:
            if operation == "list":
                client.list_problems()
            elif operation == "detail":
                client.get_problem("cf-123-a")
            elif operation == "create":
                client.create_run(
                    RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a")
                )
            else:
                client.poll_run("run-1", max_polls=1)

    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "internal.example" not in str(caught.value)
    assert "user" not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_compose_api_base_url_env_is_used_only_when_credential_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HY3_API_BASE_URL", "http://api:8000")
    assert default_api_base_url() == "http://api:8000"

    for unsafe in (
        "https://user:secret@api:8000",
        "https://api:8000?api_key=secret",
        "https://api:8000#fragment",
        "api:8000",
    ):
        monkeypatch.setenv("HY3_API_BASE_URL", unsafe)
        assert default_api_base_url() == "http://127.0.0.1:8000"


def test_streamlit_module_has_no_internal_service_or_storage_imports() -> None:
    source_path = Path(__file__).parents[1] / "src/hy3_algotrace/streamlit_app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    forbidden = {"catalog", "artifacts", "judge", "hy3_client", "evaluator"}
    assert not any(name.rsplit(".", 1)[-1] in forbidden for name in imported)
