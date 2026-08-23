from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from test_run_service import (
    CleanReviews,
    FakeGenerator,
    FakeJudge,
    HoldingExecutor,
    formal_bundle,
    service,
    valid_trace,
)

from hy3_algotrace.api_models import RunCreateRequest, RunMode
from hy3_algotrace.app import create_app
from hy3_algotrace.artifacts import ArtifactStore
from hy3_algotrace.catalog import ProblemCatalog
from hy3_algotrace.executor import SynchronousExecutor
from hy3_algotrace.run_service import RunService


def test_problem_routes_expose_only_catalog_public_data(tmp_path: Path) -> None:
    bundle = formal_bundle()
    run_service, _, _ = service(tmp_path)
    client = TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=run_service))

    listing = client.get("/api/v1/problems")
    detail = client.get("/api/v1/problems/cf-123-a")

    assert listing.status_code == 200
    assert listing.json()["problems"] == [
        {
            "schema_version": "1.2",
            "problem_id": "cf-123-a",
            "title": "Add One",
            "topic": "greedy",
            "rating": 1200,
        }
    ]
    assert detail.status_code == 200
    serialized = detail.text.lower()
    assert "hidden" not in serialized
    assert "generated" not in serialized
    assert "expected_output" not in serialized
    assert "oracle" not in serialized
    assert "reference" not in serialized
    assert client.get("/api/v1/problems/unknown").status_code == 404


def test_post_returns_202_and_get_returns_completed_report(tmp_path: Path) -> None:
    bundle = formal_bundle()
    run_service, _, _ = service(tmp_path, id_factory=lambda: "run-api")
    client = TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=run_service))

    created = client.post(
        "/api/v1/runs",
        json={"schema_version": "1.2", "mode": "solve_and_audit", "problem_id": "cf-123-a"},
    )
    fetched = client.get("/api/v1/runs/run-api")

    assert created.status_code == 202
    assert created.json() == {
        "schema_version": "1.2",
        "run_id": "run-api",
        "status": "queued",
    }
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "completed"
    assert fetched.json()["report"]["audit"]["final_correct"] is True
    assert client.get("/api/v1/runs/missing").status_code == 404


def test_completed_run_get_redacts_path_and_credential_spans_without_erasing_trace(
    tmp_path: Path,
) -> None:
    bundle = formal_bundle()
    trace = valid_trace().model_copy(
        update={
            "problem_understanding": (
                "Keep the input invariant; quoted path is "
                '"/private/tmp/judge workspace/solution.cpp".'
            ),
            "algorithm": (
                "The symbolic token /variable stays; add exactly one to x; "
                "cache is (/var/lib/judge cache/case file.txt)."
            ),
            "correctness_argument": (
                "The arithmetic proof remains valid; "
                "workspace=/Users/odalys/judge workspace/main.cpp; "
                "therefore every output is correct."
            ),
            "edge_cases": (
                "HY3 API KEY is natural-secret",
                "HY3_API_KEY underscore-secret",
                "api key\ttab-secret",
            ),
            "code": (
                '#include <iostream>\n// source="/private/tmp/build dir/main.cpp"\n'
                "// HY3 API KEY is code-secret\n"
                "int main(){long long x;std::cin>>x;std::cout<<x+1;}"
            ),
        }
    )
    artifacts = ArtifactStore(tmp_path / "artifacts")
    run_service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=artifacts,
        generator=FakeGenerator(trace),
        judge=FakeJudge(),
        reviews=CleanReviews(),
        executor=SynchronousExecutor(),
        id_factory=lambda: "run-api-redaction",
    )
    client = TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=run_service))

    created = client.post(
        "/api/v1/runs",
        json={"mode": "solve_and_audit", "problem_id": "cf-123-a"},
    )
    fetched = client.get("/api/v1/runs/run-api-redaction")

    assert created.status_code == 202
    assert fetched.status_code == 200
    payload = fetched.json()
    public_trace = payload["report"]["trace"]
    serialized = fetched.text.casefold()
    for normal_fragment in (
        "keep the input invariant",
        "add exactly one to x",
        "/variable stays",
        "the arithmetic proof remains valid",
        "therefore every output is correct",
        "#include <iostream>",
        "std::cout<<x+1",
    ):
        assert normal_fragment in serialized
    for protected_fragment in (
        "/private/tmp",
        "/var/lib",
        "/users/odalys",
        "judge workspace",
        "judge cache",
        "natural-secret",
        "underscore-secret",
        "tab-secret",
        "code-secret",
        "hy3 api key",
        "hy3_api_key",
        "api key\\t",
    ):
        assert protected_fragment not in serialized
    assert "[REDACTED]" in tuple(public_trace["edge_cases"])
    assert "[REDACTED]" in public_trace["code"]


def test_invalid_problem_and_invalid_trace_create_no_run_artifacts(tmp_path: Path) -> None:
    bundle = formal_bundle()
    artifacts = ArtifactStore(tmp_path / "artifacts")
    generator = FakeGenerator(bundle.gold_trace)
    run_service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=artifacts,
        generator=generator,
        judge=FakeJudge(),
        reviews=CleanReviews(),
        executor=SynchronousExecutor(),
    )
    client = TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=run_service))

    unknown = client.post(
        "/api/v1/runs",
        json={"mode": "solve_and_audit", "problem_id": "does-not-exist"},
    )
    mismatched = client.post(
        "/api/v1/runs",
        json={
            "mode": "audit",
            "problem_id": "cf-123-a",
            "trace": valid_trace(problem_id="cf-999-z").model_dump(mode="json"),
        },
    )
    malformed = client.post(
        "/api/v1/runs",
        json={"mode": "audit", "problem_id": "cf-123-a", "trace": {"code": "x"}},
    )

    assert unknown.status_code == 404
    assert mismatched.status_code == 422
    assert malformed.status_code == 422
    assert artifacts.list_json("run-index") == ()
    assert generator.calls == 0


def test_audit_route_accepts_valid_trace_without_generation(tmp_path: Path) -> None:
    bundle = formal_bundle()
    generator = FakeGenerator(bundle.gold_trace)
    artifacts = ArtifactStore(tmp_path / "artifacts")
    run_service = RunService(
        catalog=ProblemCatalog((bundle,)),
        artifacts=artifacts,
        generator=generator,
        judge=FakeJudge(),
        reviews=CleanReviews(),
        executor=SynchronousExecutor(),
    )
    client = TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=run_service))

    response = client.post(
        "/api/v1/runs",
        json=RunCreateRequest(
            mode=RunMode.AUDIT,
            problem_id="cf-123-a",
            trace=valid_trace(),
        ).model_dump(mode="json"),
    )

    assert response.status_code == 202
    assert generator.calls == 0


def test_app_startup_reconciles_abandoned_runs(tmp_path: Path) -> None:
    bundle = formal_bundle()
    holding = HoldingExecutor()
    first, _, artifacts = service(
        tmp_path,
        executor=holding,
        id_factory=lambda: "run-before-restart",
    )
    accepted = first.submit(RunCreateRequest(mode=RunMode.SOLVE_AND_AUDIT, problem_id="cf-123-a"))
    second, _, _ = service(tmp_path, store=artifacts)

    with TestClient(create_app(catalog=ProblemCatalog((bundle,)), run_service=second)) as client:
        response = client.get(f"/api/v1/runs/{accepted.run_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["failure"]["code"] == "abandoned_on_restart"
