"""Verify a closed runtime image manifest before copying application code into it."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    """Reject a runtime whose identity, closure, or Docker CLI attestation differs."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-image", required=True)
    parser.add_argument("--docker-cli-package", required=True)
    parser.add_argument("--lock", type=Path, default=Path("/tmp/release-runtime-lock.json"))
    arguments = parser.parse_args(argv)
    try:
        lock = json.loads(arguments.lock.read_text(encoding="utf-8"))
        if not isinstance(lock, Mapping):
            raise ValueError("invalid runtime lock schema")
        _validate_lock(lock, arguments.runtime_image, arguments.docker_cli_package)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    return 0


def _validate_lock(lock: Mapping[str, object], runtime_image: str, docker_cli_package: str) -> None:
    """Compare the full installed distribution set and immutable image inputs exactly."""

    if lock.get("schema_version") != 1 or lock.get("lock_kind") != "immutable_runtime_image":
        raise ValueError("invalid runtime lock schema")
    if lock.get("python") != ".".join(map(str, sys.version_info[:2])):
        raise ValueError("runtime lock Python version mismatch")
    if lock.get("runtime_image_identity") != runtime_image:
        raise ValueError("runtime image identity does not match the locked image")
    if lock.get("docker_cli_package") != docker_cli_package:
        raise ValueError("Docker CLI package does not match the locked runtime")
    expected_hash = lock.get("content_sha256")
    if not isinstance(expected_hash, str) or expected_hash != _lock_hash(lock):
        raise ValueError("runtime lock content hash is invalid")
    expected = lock.get("distributions")
    if not isinstance(expected, Mapping) or not expected:
        raise ValueError("runtime lock distributions are missing")
    expected_versions = _versions(expected)
    installed_versions = _installed_versions()
    if installed_versions != expected_versions:
        missing = sorted(set(expected_versions) - set(installed_versions))
        extra = sorted(set(installed_versions) - set(expected_versions))
        changed = sorted(
            name
            for name in set(expected_versions) & set(installed_versions)
            if expected_versions[name] != installed_versions[name]
        )
        categories = []
        if missing:
            categories.append("missing=" + ",".join(missing))
        if extra:
            categories.append("extra=" + ",".join(extra))
        if changed:
            categories.append("changed=" + ",".join(changed))
        raise ValueError("runtime lock mismatch: " + "; ".join(categories))


def _lock_hash(lock: Mapping[str, object]) -> str:
    """Hash the canonical lock body, including the immutable runtime identity."""

    body = {key: value for key, value in lock.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _versions(raw: Mapping[object, object]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_name, raw_version in raw.items():
        if not isinstance(raw_name, str) or not isinstance(raw_version, str):
            raise ValueError("runtime lock distributions are invalid")
        name = _canonical_distribution_name(raw_name)
        if name in versions:
            raise ValueError("runtime lock duplicate distribution")
        versions[name] = raw_version
    return versions


def _installed_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in metadata.distributions():
        raw_name = distribution.metadata.get("Name")
        if not raw_name:
            continue
        name = _canonical_distribution_name(raw_name)
        if name in versions:
            raise ValueError("runtime has duplicate distribution metadata")
        versions[name] = distribution.version
    return versions


def _canonical_distribution_name(name: str) -> str:
    return "".join("-" if character in "_." else character.casefold() for character in name)


if __name__ == "__main__":  # pragma: no cover - Docker build entry point
    raise SystemExit(main())
