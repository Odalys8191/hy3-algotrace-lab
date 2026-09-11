"""Tests for the execution-intent freeze: non-circular intent hashing and manifest sealing."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_benchmark import config as benchmark_config

from hy3_algotrace import intent
from hy3_algotrace.artifacts import canonical_json_bytes, sha256_bytes
from hy3_algotrace.benchmark_models import BenchmarkConfig

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_formal_intent.py"
_spec = importlib.util.spec_from_file_location("prepare_formal_intent", _SCRIPT)
assert _spec is not None and _spec.loader is not None
prepare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prepare)

_JUDGE_DIGEST = f"sha256:{'c' * 64}"
_IMAGE_REFERENCE = f"localhost:15088/hy3-algotrace-judge@{_JUDGE_DIGEST}"
_RECORDED_AT = datetime(2026, 9, 11, 4, 30, tzinfo=UTC)
_DERIVED_CONFIG_KEYS = ("benchmark_id", "config_sha256", "intent_hash")


def identity(**changes: Any) -> intent.IntentIdentity:
    payload: dict[str, Any] = {
        "recorded_at": _RECORDED_AT,
        "formal": False,
        "selection_hash": "a" * 64,
        "corpus_hash": "b" * 64,
        "prompt_versions": intent.IntentPromptVersions(
            generator="solution-trace-v1",
            logic_review="logic-reviewer-v1",
            adversarial_review="adversarial-reviewer-v1",
            arbiter="arbiter-v1",
        ),
        "code_revision": "revision-1",
        "worktree_clean": True,
        "judge_image_digest": _JUDGE_DIGEST,
        "timeout_seconds": 600.0,
        "model": "hy3",
        "endpoint_identity": "https://hy3.example/v1",
        "remote_attempt_budget": 12,
    }
    payload.update(changes)
    return intent.IntentIdentity.model_validate(payload)


def config_bytes_for(frozen: intent.IntentIdentity, **changes: Any) -> bytes:
    payload = benchmark_config(
        benchmark_id=frozen.derive_benchmark_id("intent-demo"),
        budget=frozen.remote_attempt_budget,
    ).model_copy(
        update={
            "selection_hash": frozen.selection_hash,
            "corpus_hash": frozen.corpus_hash,
            "model": frozen.model,
            "endpoint_identity": frozen.endpoint_identity,
            "code_revision": frozen.code_revision,
            "judge_image_digest": frozen.judge_image_digest,
            "timeout_seconds": frozen.timeout_seconds,
            "generator_prompt_version": frozen.prompt_versions.generator,
            "logic_review_prompt_version": frozen.prompt_versions.logic_review,
            "adversarial_review_prompt_version": frozen.prompt_versions.adversarial_review,
            "arbiter_prompt_version": frozen.prompt_versions.arbiter,
        }
    )
    payload = payload.model_dump(mode="json")
    payload.update(changes)
    return canonical_json_bytes(payload)


def sealed() -> tuple[intent.IntentManifest, bytes]:
    frozen = identity()
    config_bytes = config_bytes_for(frozen)
    return (
        intent.seal_intent_manifest(frozen, slug="intent-demo", config_bytes=config_bytes),
        config_bytes,
    )


def test_identity_hash_is_stable_and_timeout_sensitive() -> None:
    base = identity()
    assert base.identity_hash() == identity().identity_hash()
    assert base.identity_hash() != identity(timeout_seconds=60.0).identity_hash()
    assert base.identity_hash() != identity(code_revision="revision-2").identity_hash()


def test_benchmark_id_is_derived_from_identity_hash() -> None:
    base = identity()
    assert base.derive_benchmark_id("intent-demo") == f"intent-demo-{base.identity_hash()[:12]}"
    slower = identity(timeout_seconds=60.0).derive_benchmark_id("intent-demo")
    assert base.derive_benchmark_id("intent-demo") != slower
    with pytest.raises(intent.IntentManifestError):
        base.derive_benchmark_id("bad slug")


def test_identity_hash_ignores_the_derived_identifier() -> None:
    manifest, _ = sealed()
    payload = {
        key: value
        for key, value in manifest.model_dump(mode="json").items()
        if key not in _DERIVED_CONFIG_KEYS
    }
    assert intent.IntentIdentity.model_validate(payload).derive_benchmark_id("intent-demo") == (
        manifest.benchmark_id
    )
    assert intent.IntentIdentity.model_validate(payload).identity_hash() == (
        manifest.identity_hash()
    )


def test_sealed_manifest_binds_config_bytes_and_verifies() -> None:
    manifest, config_bytes = sealed()
    assert intent.compute_intent_hash(manifest) == manifest.intent_hash
    assert sha256_bytes(config_bytes) == manifest.config_sha256
    assert manifest.config_sha256 == intent.compute_config_sha256(config_bytes)
    intent.verify_intent_manifest(
        manifest, config_bytes=config_bytes, code_revision=manifest.code_revision
    )


@pytest.mark.parametrize(
    "update",
    [
        {"timeout_seconds": 60.0},
        {"model": "other"},
        {"benchmark_id": "intent-demo-deadbeef0000"},
        {"selection_hash": "0" * 64},
        {"corpus_hash": "0" * 64},
        {"judge_image_digest": "sha256:" + "0" * 64},
        {"remote_attempt_budget": 11},
        {"arbiter_prompt_version": "invented"},
    ],
)
def test_verify_rejects_config_that_does_not_match_the_manifest(update: dict[str, Any]) -> None:
    manifest, config_bytes = sealed()
    drifted = config_bytes_for(identity(), **update)
    with pytest.raises(intent.IntentManifestError):
        intent.verify_intent_manifest(manifest, config_bytes=drifted)


def test_verify_rejects_byte_drift_and_manifest_tamper() -> None:
    manifest, config_bytes = sealed()
    with pytest.raises(intent.IntentManifestError):
        intent.verify_intent_manifest(manifest, config_bytes=config_bytes + b"\n")
    rehashed = manifest.model_copy(update={"intent_hash": "0" * 64})
    with pytest.raises(intent.IntentManifestError):
        intent.verify_intent_manifest(rehashed, config_bytes=config_bytes)
    with pytest.raises(intent.IntentManifestError):
        intent.verify_intent_manifest(manifest, config_bytes=config_bytes, code_revision="other")
    assert intent.expected_benchmark_id_suffix(manifest) == manifest.benchmark_id[-12:]


def test_verify_reports_derived_id_drift() -> None:
    manifest, config_bytes = sealed()
    with pytest.raises(intent.IntentManifestError):
        intent.verify_intent_manifest(
            manifest.model_copy(update={"benchmark_id": "intent-demo-000000000000"}),
            config_bytes=config_bytes,
        )


@pytest.mark.parametrize(
    "update",
    [
        {"recorded_at": datetime(2026, 9, 11, 4, 30)},
        {"timeout_seconds": 0.0},
        {"timeout_seconds": float("inf")},
        {"selection_hash": "A" * 64},
        {"judge_image_digest": "sha256:short"},
        {"remote_attempt_budget": 0},
    ],
)
def test_identity_rejects_invalid_freeze_inputs(update: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        identity(**update)


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("frozen input\n", encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "user.name=fixture",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "init",
        ],
    ):
        subprocess.run(argv, cwd=repo, check=True, env=_git_env(), capture_output=True)
    return repo


def _template() -> dict[str, Any]:
    payload = benchmark_config(budget=12).model_dump(mode="json")
    for runtime_derived in (
        "benchmark_id",
        "timeout_seconds",
        "code_revision",
        "model",
        "endpoint_identity",
        "judge_image_digest",
    ):
        payload.pop(runtime_derived)
    return payload


def _frozen_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HY3_JUDGE_IMAGE", _IMAGE_REFERENCE)
    monkeypatch.setenv("HY3_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("HY3_MODEL", "hy3")
    monkeypatch.setenv("HY3_BASE_URL", "https://hy3.example/v1")


def _prepare_argv(tmp_path: Path, repo: Path, template: Path) -> list[str]:
    return [
        "--template",
        str(template),
        "--tag",
        "freeze-v1",
        "--slug",
        "intent-demo",
        "--timeout-seconds",
        "600",
        "--out-dir",
        str(tmp_path / "config-root"),
        "--repo-root",
        str(repo),
    ]


def _write_template(tmp_path: Path, payload: dict[str, Any]) -> Path:
    template = tmp_path / "config.template.json"
    template.write_text(json.dumps(payload), encoding="utf-8")
    return template


def test_prepare_writes_create_only_config_and_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    template = _write_template(tmp_path, _template())
    _frozen_env(monkeypatch)
    argv = _prepare_argv(tmp_path, repo, template)
    assert prepare.main(argv) == 0
    summary = json.loads(capsys.readouterr().out)
    root = tmp_path / "config-root"
    config_bytes = (root / "config.runtime-freeze-v1.json").read_bytes()
    manifest = intent.IntentManifest.model_validate_json(
        (root / "intent-manifest-freeze-v1.json").read_bytes()
    )
    assert summary == {
        "benchmark_id": manifest.benchmark_id,
        "config_sha256": manifest.config_sha256,
        "intent_hash": manifest.intent_hash,
        "status": "intent_frozen",
    }
    assert manifest.code_revision == prepare.repository_state(repo)[0]
    assert manifest.worktree_clean is True
    assert manifest.timeout_seconds == 600.0
    assert manifest.config_sha256 == sha256_bytes(config_bytes)
    intent.verify_intent_manifest(manifest, config_bytes=config_bytes)
    assert prepare.main(argv) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "intent_freeze_failed"}


def test_prepare_rejects_timeout_that_disagrees_with_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    template = _write_template(tmp_path, _template())
    _frozen_env(monkeypatch)
    monkeypatch.setenv("HY3_TIMEOUT_SECONDS", "60")
    assert prepare.main(_prepare_argv(tmp_path, repo, template)) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "intent_freeze_failed"}


def test_prepare_rejects_dirty_worktree_and_hand_chosen_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    template = _write_template(tmp_path, _template())
    _frozen_env(monkeypatch)
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert prepare.main(_prepare_argv(tmp_path, repo, template)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "intent_freeze_failed"
    subprocess.run(
        ["git", "checkout", "--", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_git_env(),
    )
    _write_template(
        tmp_path, _template() | {"benchmark_id": "chosen-by-hand", "code_revision": "chosen"}
    )
    assert prepare.main(_prepare_argv(tmp_path, repo, template)) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "intent_freeze_failed"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("HY3_JUDGE_IMAGE", "hy3-algotrace-judge:latest"),
        ("HY3_MODEL", "hy3-preview"),
        ("HY3_BASE_URL", "http://hy3.example/v1"),
        ("HY3_TIMEOUT_SECONDS", ""),
    ],
)
def test_prepare_rejects_unfrozen_runtime_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
    value: str,
) -> None:
    repo = _git_repo(tmp_path)
    template = _write_template(tmp_path, _template())
    _frozen_env(monkeypatch)
    monkeypatch.setenv(name, value)
    assert prepare.main(_prepare_argv(tmp_path, repo, template)) == 2
    assert json.loads(capsys.readouterr().out) == {"status": "intent_freeze_failed"}


def test_prepare_reports_repository_state(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    revision, clean = prepare.repository_state(repo)
    assert len(revision) == 40 and clean is True
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")
    assert prepare.repository_state(repo)[1] is False


def test_config_bytes_helper_is_canonical() -> None:
    _, config_bytes = sealed()
    assert config_bytes == canonical_json_bytes(json.loads(config_bytes))
    assert BenchmarkConfig.model_validate_json(config_bytes).timeout_seconds == 600.0
