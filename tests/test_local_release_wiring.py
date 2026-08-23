from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
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


def test_formal_readiness_stays_pending_without_task7_judge_replay() -> None:
    """Selection/corpus lint alone can never convert a missing Judge replay into green."""

    result = subprocess.run(
        ["sh", "scripts/formal-readiness.sh"],
        cwd=REPOSITORY_ROOT,
        env={"PATH": os.environ["PATH"]},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 3
    assert "dataset CLI" in result.stderr


def test_task7_combined_tree_contract_uses_current_secure_selection_commands() -> None:
    """Task 8 may use Task 7's secure receipt, but cannot mistake it for eligibility."""

    script = (REPOSITORY_ROOT / "scripts/formal-readiness.sh").read_text(encoding="utf-8")
    assert "validate-selection-preliminary" in script
    assert "verify-selection-chain" in script
    assert "capability_persisted=false" in script
    assert "validate_persisted_formal_judge_evidence" in script
    assert "formal_judge_cli" not in script
    data_lint = (REPOSITORY_ROOT / "scripts/data-lint.sh").read_text(encoding="utf-8")
    assert "validate-acquisition" in data_lint
    assert "--validation-id" not in data_lint


def test_formal_readiness_creates_current_task7_outputs_without_overwrite(
    tmp_path: Path,
) -> None:
    """The combined-tree path may create receipts/audits once, never treat them as inputs."""

    package_root = tmp_path / "src" / "hy3_algotrace"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "dataset_cli.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "arguments = sys.argv[1:]\n"
        "if '--output' in arguments:\n"
        "    output = Path(arguments[arguments.index('--output') + 1])\n"
        "    if output.exists():\n"
        "        raise SystemExit(2)\n"
        "    output.write_text(arguments[0], encoding='utf-8')\n",
        encoding="utf-8",
    )
    formal_root = tmp_path / "formal"
    formal_root.mkdir()
    output_audit = formal_root / "corpus-audit.json"
    output_receipt = formal_root / "selection-replay-receipt.json"
    input_names = (
        "selection",
        "acquisition",
        "acquisition-validation",
        "conversion-validation",
        "conversion-test",
        "quota",
        "bundles",
        "corpus",
        "judge-evidence",
        "judge-raw-evidence",
        "validation-raw",
        "test-raw",
        "validation-reviews",
        "test-reviews",
        "review-manifest",
    )
    inputs = {name: formal_root / f"{name}.json" for name in input_names}
    for path in inputs.values():
        path.write_text("input", encoding="utf-8")
    environment = {
        "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        "PYTHONPATH": str(tmp_path / "src"),
        "HY3_FORMAL_SELECTION": str(inputs["selection"]),
        "HY3_FORMAL_ACQUISITION": str(inputs["acquisition"]),
        "HY3_FORMAL_ACQUISITION_VALIDATION": str(inputs["acquisition-validation"]),
        "HY3_FORMAL_CONVERSION_VALIDATION": str(inputs["conversion-validation"]),
        "HY3_FORMAL_CONVERSION_TEST": str(inputs["conversion-test"]),
        "HY3_FORMAL_QUOTA": str(inputs["quota"]),
        "HY3_FORMAL_BUNDLES": str(inputs["bundles"]),
        "HY3_FORMAL_CORPUS": str(inputs["corpus"]),
        "HY3_FORMAL_JUDGE_EVIDENCE": str(inputs["judge-evidence"]),
        "HY3_FORMAL_JUDGE_RAW_EVIDENCE": str(inputs["judge-raw-evidence"]),
        "HY3_FORMAL_VALIDATION_RAW": str(inputs["validation-raw"]),
        "HY3_FORMAL_TEST_RAW": str(inputs["test-raw"]),
        "HY3_FORMAL_VALIDATION_FORMAT": "json",
        "HY3_FORMAL_TEST_FORMAT": "jsonl",
        "HY3_FORMAL_VALIDATION_REVIEWS": str(inputs["validation-reviews"]),
        "HY3_FORMAL_TEST_REVIEWS": str(inputs["test-reviews"]),
        "HY3_FORMAL_REVIEW_MANIFEST": str(inputs["review-manifest"]),
        "HY3_FORMAL_SELECTION_REPLAY_RECEIPT": str(output_receipt),
        "HY3_FORMAL_CORPUS_AUDIT": str(output_audit),
        "HY3_FORMAL_DATA_ROOT": str(formal_root),
    }
    script = REPOSITORY_ROOT / "scripts/formal-readiness.sh"

    first = subprocess.run(
        ["sh", str(script)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert first.returncode == 3
    assert output_receipt.read_text(encoding="utf-8") == "verify-selection-chain"
    assert output_audit.read_text(encoding="utf-8") == "lint-corpus"

    second = subprocess.run(
        ["sh", str(script)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert second.returncode == 3
    assert output_receipt.read_text(encoding="utf-8") == "verify-selection-chain"
    assert output_audit.read_text(encoding="utf-8") == "lint-corpus"

    missing_output_parent = formal_root / "missing-output-parent"
    environment["HY3_FORMAL_SELECTION_REPLAY_RECEIPT"] = str(
        missing_output_parent / "selection-replay-receipt.json"
    )
    environment["HY3_FORMAL_CORPUS_AUDIT"] = str(missing_output_parent / "corpus-audit.json")
    missing_parent = subprocess.run(
        ["sh", str(script)],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert missing_parent.returncode == 3
    assert "parent directory" in missing_parent.stderr
    assert not missing_output_parent.exists()


def test_ci_separates_no_docker_unit_checks_from_actual_docker_and_formal_gates() -> None:
    """A missing daemon or pending formal evidence cannot be silently called CI success."""

    workflow = (REPOSITORY_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert 'python -m pytest -q -m "not docker_integration"' in workflow
    assert "python -m pytest -q -m docker_integration" in workflow
    assert "scripts/formal-release-gate.sh" in workflow
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
