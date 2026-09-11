"""Freeze a formal execution intent and write ``config.runtime`` plus its manifest.

Hy3 AlgoTrace Lab is a personal activity project and not an official Tencent release.

``docs/FORMAL_CORPUS_LIFECYCLE.md`` §2.2 requires the script that writes
``config.runtime`` to write the intent manifest as well. This script owns the
runtime-derived half of the frozen identity — derived ``benchmark_id``, code
revision, worktree cleanliness, model read timeout, Judge image digest, model,
and endpoint — so no operator can choose them by hand. Everything else
(selection hash, corpus hash, prompt versions, sample specs, budget, seed)
comes from the corpus/selection pipeline and stays in the template.

The model read timeout is frozen in both the config and the manifest: the
config field is what :class:`~hy3_algotrace.live_benchmark.LiveExecutor` compares
against the process environment, and the manifest field is what the sealed
``intent_hash`` covers. A timeout that disagrees with ``HY3_TIMEOUT_SECONDS``
cannot be frozen at all.

Write order matters: the identity hash is computed before ``benchmark_id``
exists, the config bytes are hashed after ``benchmark_id`` is embedded, and the
manifest hash binds both. Nothing is ever rewritten — an existing config or
manifest for the same tag fails closed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hy3_algotrace.artifacts import canonical_json_bytes
from hy3_algotrace.benchmark_models import BenchmarkConfig
from hy3_algotrace.hy3_client import endpoint_identity
from hy3_algotrace.intent import (
    IntentIdentity,
    IntentManifest,
    IntentManifestError,
    IntentPromptVersions,
    seal_intent_manifest,
    verify_intent_manifest,
)

RUNTIME_DERIVED_KEYS = (
    "benchmark_id",
    "code_revision",
    "endpoint_identity",
    "judge_image_digest",
    "model",
    "timeout_seconds",
)
GA_MODEL = "hy3"
JUDGE_REFERENCE_PATTERN = re.compile(r"[^\s@]+@(sha256:[0-9a-f]{64})")
CONFIG_FILENAME = "config.runtime-{tag}.json"
MANIFEST_FILENAME = "intent-manifest-{tag}.json"
_GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


class IntentFreezeError(RuntimeError):
    """Raised when a runtime identity or template cannot be frozen."""


def _git(repo_root: Path, *argv: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *argv],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            env=_GIT_ENV,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise IntentFreezeError(f"cannot read repository state: git {' '.join(argv)}") from error
    return completed.stdout.strip()


def repository_state(repo_root: Path) -> tuple[str, bool]:
    """Return ``(HEAD revision, worktree clean)`` from the repository at ``repo_root``."""

    revision = _git(repo_root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise IntentFreezeError("git rev-parse HEAD did not return a commit hash")
    return revision, _git(repo_root, "status", "--porcelain") == ""


def _read_template(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise IntentFreezeError("config template cannot be read as JSON") from error
    if not isinstance(payload, dict):
        raise IntentFreezeError("config template must be a JSON object")
    chosen = sorted(key for key in RUNTIME_DERIVED_KEYS if key in payload)
    if chosen:
        raise IntentFreezeError(
            "config template must not choose runtime-derived fields: " + ", ".join(chosen)
        )
    return payload


def _runtime_identity(timeout_flag: float) -> dict[str, Any]:
    reference = os.environ.get("HY3_JUDGE_IMAGE", "")
    match = JUDGE_REFERENCE_PATTERN.fullmatch(reference)
    if match is None:
        raise IntentFreezeError("HY3_JUDGE_IMAGE must pin a digest with name@sha256:...")
    try:
        environment_timeout = float(os.environ.get("HY3_TIMEOUT_SECONDS", ""))
    except ValueError as error:
        raise IntentFreezeError("HY3_TIMEOUT_SECONDS must be a number") from error
    if environment_timeout != timeout_flag:
        raise IntentFreezeError(
            "HY3_TIMEOUT_SECONDS disagrees with the timeout being frozen; "
            "changing it changes the intent"
        )
    model = os.environ.get("HY3_MODEL", "")
    if model != GA_MODEL:
        raise IntentFreezeError(f"formal execution intent fixes the GA model {GA_MODEL}")
    base_url = os.environ.get("HY3_BASE_URL", "")
    return {
        "timeout_seconds": timeout_flag,
        "judge_image_digest": match.group(1),
        "model": model,
        "endpoint_identity": endpoint_identity(base_url),
    }


def _write_once(path: Path, payload: bytes) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload.decode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise IntentFreezeError(f"refusing to overwrite a frozen artifact: {path.name}") from error


def freeze(
    *,
    template: Path,
    tag: str,
    slug: str,
    timeout_seconds: float,
    out_dir: Path,
    repo_root: Path,
    recorded_at: datetime,
) -> tuple[BenchmarkConfig, IntentManifest, str]:
    """Freeze one intent and return ``(config, manifest, config_sha256)``."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", tag):
        raise IntentFreezeError("tag must be a nonempty alphanumeric token")
    payload = _read_template(template) | _runtime_identity(timeout_seconds)
    revision, clean = repository_state(repo_root)
    if not clean:
        raise IntentFreezeError("worktree must be clean before freezing an intent")
    payload["code_revision"] = revision
    identity = IntentIdentity(
        recorded_at=recorded_at,
        formal=payload["formal"],
        selection_hash=payload["selection_hash"],
        corpus_hash=payload["corpus_hash"],
        prompt_versions=IntentPromptVersions(
            generator=payload["generator_prompt_version"],
            logic_review=payload["logic_review_prompt_version"],
            adversarial_review=payload["adversarial_review_prompt_version"],
            arbiter=payload["arbiter_prompt_version"],
        ),
        code_revision=revision,
        worktree_clean=clean,
        judge_image_digest=payload["judge_image_digest"],
        timeout_seconds=payload["timeout_seconds"],
        model=payload["model"],
        endpoint_identity=payload["endpoint_identity"],
        remote_attempt_budget=payload["remote_attempt_budget"],
    )
    payload["benchmark_id"] = identity.derive_benchmark_id(slug)
    config = BenchmarkConfig.model_validate(payload)
    config_bytes = canonical_json_bytes(config.model_dump(mode="json"))
    manifest = seal_intent_manifest(identity, slug=slug, config_bytes=config_bytes)
    verify_intent_manifest(manifest, config_bytes=config_bytes, code_revision=revision)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_once(out_dir / CONFIG_FILENAME.format(tag=tag), config_bytes)
    _write_once(
        out_dir / MANIFEST_FILENAME.format(tag=tag),
        canonical_json_bytes(manifest.model_dump(mode="json")),
    )
    return config, manifest, manifest.config_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hy3 AlgoTrace Lab: personal activity project, not an official "
        "Tencent release. Freeze a formal execution intent (config.runtime + manifest)."
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--timeout-seconds", type=float, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        config, manifest, config_sha256 = freeze(
            template=args.template,
            tag=args.tag,
            slug=args.slug,
            timeout_seconds=args.timeout_seconds,
            out_dir=args.out_dir,
            repo_root=args.repo_root,
            recorded_at=datetime.now(UTC),
        )
    except (
        IntentFreezeError,
        IntentManifestError,
        ValueError,
        OSError,
    ) as error:  # fail closed on any unsealed intent
        print(f"error: {error}", file=sys.stderr)
        print(json.dumps({"status": "intent_freeze_failed"}, sort_keys=True, separators=(",", ":")))
        return 2
    print(
        json.dumps(
            {
                "benchmark_id": config.benchmark_id,
                "config_sha256": config_sha256,
                "intent_hash": manifest.intent_hash,
                "status": "intent_frozen",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main in tests
    raise SystemExit(main())
