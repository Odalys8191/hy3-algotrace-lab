from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _runtime_lock_module() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "verify_runtime_lock", REPOSITORY_ROOT / "docker/verify-runtime-lock.py"
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_runtime_lock_binds_full_closure_and_digest_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matching image is valid only when no extra distribution can enter the runtime."""

    module = _runtime_lock_module()
    lock = json.loads((REPOSITORY_ROOT / "docker/release-runtime-lock.json").read_text())
    expected = module._versions(lock["distributions"])
    monkeypatch.setattr(module, "_installed_versions", lambda: expected)

    module._validate_lock(lock, lock["runtime_image_identity"], lock["docker_cli_package"])

    monkeypatch.setattr(module, "_installed_versions", lambda: {**expected, "unlocked-extra": "1"})
    with pytest.raises(ValueError, match="extra=unlocked-extra"):
        module._validate_lock(lock, lock["runtime_image_identity"], lock["docker_cli_package"])

    with pytest.raises(ValueError, match="identity"):
        module._validate_lock(
            lock, "registry.example/runtime@sha256:" + "a" * 64, lock["docker_cli_package"]
        )


def test_runtime_lock_hash_covers_the_image_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing a repository digest invalidates the lock before a build can proceed."""

    module = _runtime_lock_module()
    lock = json.loads((REPOSITORY_ROOT / "docker/release-runtime-lock.json").read_text())
    expected = module._versions(lock["distributions"])
    monkeypatch.setattr(module, "_installed_versions", lambda: expected)
    lock["runtime_image_identity"] = "registry.example/runtime@sha256:" + "a" * 64

    with pytest.raises(ValueError, match="content hash"):
        module._validate_lock(lock, lock["runtime_image_identity"], lock["docker_cli_package"])


def test_linux_runtime_lock_includes_streamlit_watcher_and_build_pip() -> None:
    """The Linux production image closure covers Streamlit's watcher and Dockerfile pip."""

    lock = json.loads((REPOSITORY_ROOT / "docker/release-runtime-lock.json").read_text())

    assert lock["distributions"]["watchdog"] == "6.0.0"
    assert lock["distributions"]["pip"] == "25.0.1"
    dockerfile = (REPOSITORY_ROOT / "docker/app/Dockerfile").read_text(encoding="utf-8")
    assert "python -m pip install" in dockerfile
