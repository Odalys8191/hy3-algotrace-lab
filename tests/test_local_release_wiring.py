from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_run_service import CleanReviews, FakeGenerator, FakeJudge, formal_bundle

from hy3_algotrace.catalog import ProblemCatalog
from hy3_algotrace.executor import SynchronousExecutor
from hy3_algotrace.local_app import _judge_image_digest, create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_zero_argument_composition_factory_is_real_uvicorn_target() -> None:
    """Compose may use the factory directly rather than a configurable placeholder."""

    assert tuple(inspect.signature(create_app).parameters) == ()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "hy3_algotrace.local_app:create_app" in compose
    for name in ("HY3_BASE_URL", "HY3_API_KEY", "HY3_MODEL"):
        assert f"{name}: ${{{name}:?" in compose


@pytest.mark.parametrize(
    ("image_reference", "expected"),
    (
        ("registry.example/hy3/judge@sha256:" + "a" * 64, "sha256:" + "a" * 64),
        ("docker.io/acme/judge@sha256:" + "B" * 64, "sha256:" + "b" * 64),
    ),
)
def test_judge_image_reference_is_reduced_to_a_bare_manifest_digest(
    image_reference: str, expected: str
) -> None:
    """Run manifests never receive a repository-qualified image reference."""

    assert _judge_image_digest(image_reference) == expected


@pytest.mark.parametrize(
    "image_reference",
    ("", "latest", "sha256:" + "a" * 64, "repo:tag", "repo@sha256:not-a-digest"),
)
def test_judge_image_reference_requires_a_repository_digest(image_reference: str) -> None:
    """A mutable or malformed Judge selection stops before any request exists."""

    with pytest.raises(ValueError, match="HY3_JUDGE_IMAGE"):
        _judge_image_digest(image_reference)


def test_zero_argument_factory_accepts_real_post_without_partial_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The full Docker ref drives Docker while the persisted manifest stores its digest."""

    image_reference = "registry.example/hy3/judge@sha256:" + "c" * 64
    bundle = formal_bundle()
    monkeypatch.setenv("HY3_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("HY3_CATALOG_ROOT", str(tmp_path / "catalog"))
    monkeypatch.setenv("HY3_BASE_URL", "https://hy3.example.test/v1")
    monkeypatch.setenv("HY3_API_KEY", "YOUR_HY3_API_KEY")
    monkeypatch.setenv("HY3_MODEL", "hy3-test")
    monkeypatch.setenv("HY3_JUDGE_IMAGE", image_reference)
    monkeypatch.setattr(
        ProblemCatalog,
        "from_directory",
        staticmethod(lambda _directory: ProblemCatalog((bundle,))),
    )
    monkeypatch.setattr(
        "hy3_algotrace.local_app.Hy3Client",
        lambda *_args, **_kwargs: FakeGenerator(bundle.gold_trace),
    )
    monkeypatch.setattr("hy3_algotrace.local_app.DockerJudge", FakeJudge)
    monkeypatch.setattr(
        "hy3_algotrace.local_app.ReviewOrchestrator", lambda _client: CleanReviews()
    )
    monkeypatch.setattr(
        "hy3_algotrace.local_app.InProcessBackgroundExecutor",
        lambda **_kwargs: SynchronousExecutor(),
    )

    client = TestClient(create_app())
    created = client.post(
        "/api/v1/runs",
        json={
            "schema_version": "1.2",
            "mode": "solve_and_audit",
            "problem_id": bundle.record.problem_id,
        },
    )

    assert created.status_code == 202
    fetched = client.get(f"/api/v1/runs/{created.json()['run_id']}")
    assert fetched.status_code == 200
    transitions = tuple((tmp_path / "artifacts" / "runs").rglob("*.json"))
    serialized = "\n".join(path.read_text(encoding="utf-8") for path in transitions)
    assert image_reference not in serialized
    assert "sha256:" + "c" * 64 in serialized


def test_compose_only_publishes_loopback_and_requires_controlled_socket() -> None:
    """The host Docker socket has no silent default and ports stay local-only."""

    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert '"127.0.0.1:${HY3_API_PORT:-8000}:8000"' in compose
    assert '"127.0.0.1:${HY3_UI_PORT:-8501}:8501"' in compose
    assert "HY3_DOCKER_SOCKET_PATH:?" in compose


def test_docker_smoke_fails_closed_without_pinned_ci_inputs() -> None:
    """A Docker job cannot silently substitute mutable image/package defaults."""

    result = subprocess.run(
        ["sh", "scripts/docker-smoke.sh"],
        cwd=REPOSITORY_ROOT,
        env={"PATH": os.environ["PATH"]},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 64
    assert "missing pinned Docker CI variable" in result.stderr


def test_docker_integration_runs_built_api_with_controlled_http_fixture() -> None:
    """The CI script must build both app args and exercise an actual Compose API POST."""

    script = (REPOSITORY_ROOT / "scripts/docker-smoke.sh").read_text(encoding="utf-8")
    assert '--build-arg "HY3_APP_RUNTIME_IMAGE=$HY3_APP_RUNTIME_IMAGE"' in script
    assert '--build-arg "HY3_DOCKER_CLI_PACKAGE=$HY3_DOCKER_CLI_PACKAGE"' in script
    assert "--tag hy3-algotrace-local:dev" in script
    assert "docker compose $compose_args up --detach --no-build api" in script
    assert "ci_stub_app" in script
    assert "http://127.0.0.1:8000/api/v1/problems" in script
    assert "http://127.0.0.1:8000/api/v1/runs" in script


def test_formal_readiness_stays_pending_without_complete_qualification_inputs() -> None:
    """Missing external inputs remain an explicit not-ready status."""

    result = subprocess.run(
        ["sh", "scripts/formal-readiness.sh"],
        cwd=REPOSITORY_ROOT,
        env={"PATH": os.environ["PATH"]},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 3
    assert "personal activity project and not an official Tencent release" in result.stderr
    assert "qualification inputs are absent" in result.stderr


def test_formal_readiness_invokes_only_the_same_process_qualification_boundary() -> None:
    """Readiness cannot pre-create receipts/audits or split the capability across CLIs."""

    script = (REPOSITORY_ROOT / "scripts/formal-readiness.sh").read_text(encoding="utf-8")
    assert "python -m hy3_algotrace.formal_qualification" in script
    assert "dataset_cli" not in script
    assert "SELECTION_REPLAY_RECEIPT" not in script
    assert "CORPUS_AUDIT" not in script
    data_lint = (REPOSITORY_ROOT / "scripts/data-lint.sh").read_text(encoding="utf-8")
    assert "validate-acquisition" in data_lint
    assert "--validation-id" not in data_lint


def test_formal_readiness_compose_profile_is_separate_from_http_only_streamlit() -> None:
    """Only the formal service sees formal filesystem roots; Streamlit remains HTTP-only."""

    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert 'formal-readiness:\n    profiles: ["formal-readiness"]' in compose
    formal_block = compose.split("  formal-readiness:", maxsplit=1)[1].split(
        "\nvolumes:", maxsplit=1
    )[0]
    streamlit_block = compose.split("  streamlit:", maxsplit=1)[1].split(
        "\n  formal-readiness:", maxsplit=1
    )[0]
    assert "HY3_FORMAL_INPUT_ROOT_HOST" in formal_block
    assert "HY3_FORMAL_OUTPUT_ROOT_HOST" in formal_block
    assert "build:" in formal_block
    assert "dockerfile: docker/app/Dockerfile" in formal_block
    assert "HY3_FORMAL" not in streamlit_block
    assert "HY3_API_BASE_URL: http://api:8000" in streamlit_block
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose --profile formal-readiness run --build --rm formal-readiness" in readme


def test_ci_separates_no_docker_unit_checks_from_actual_docker_and_formal_gates() -> None:
    """A missing daemon or pending formal evidence cannot be silently called CI success."""

    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'python -m pytest -q -m "not docker_integration"' in workflow
    assert "python -m pytest -q -m docker_integration" in workflow
    assert "scripts/formal-release-gate.sh" in workflow
    assert "expect not-ready without external inputs" in workflow
    assert "docker-release-not-ready" in workflow
    assert "--full-history --all --diff-filter=tuxdb" in workflow


def test_app_image_uses_a_complete_immutable_runtime_lock() -> None:
    """Docker must not resolve mutable Python transitive dependencies at build time."""

    lock = json.loads((REPOSITORY_ROOT / "docker/release-runtime-lock.json").read_text())
    assert lock["python"] == "3.12"
    assert lock["distributions"]["fastapi"]
    assert lock["distributions"]["streamlit"]
    assert lock["distributions"]["uvicorn"]
    dockerfile = (REPOSITORY_ROOT / "docker/app/Dockerfile").read_text(encoding="utf-8")
    assert "HY3_APP_RUNTIME_IMAGE" in dockerfile
    assert "release-runtime-lock.json" in dockerfile
    assert "pip install --no-cache-dir --no-build-isolation --no-deps ." in dockerfile


def test_docker_build_context_excludes_local_credentials_and_artifacts() -> None:
    """A copied local .env must never enter an app-image build context."""

    ignored = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert ".env" in ignored.splitlines()
    assert "artifacts/" in ignored.splitlines()
    assert ".git/" in ignored.splitlines()
