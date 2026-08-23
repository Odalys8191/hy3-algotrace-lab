from __future__ import annotations

import inspect
import json
import os
import subprocess
from pathlib import Path

from hy3_algotrace.local_app import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_zero_argument_composition_factory_is_real_uvicorn_target() -> None:
    """Compose may use the factory directly rather than a configurable placeholder."""

    assert tuple(inspect.signature(create_app).parameters) == ()
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "hy3_algotrace.local_app:create_app" in compose
    for name in ("HY3_BASE_URL", "HY3_API_KEY", "HY3_MODEL"):
        assert f"{name}: ${{{name}:?" in compose


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
