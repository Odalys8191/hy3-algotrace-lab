"""Validate the Python distributions contained in a digest-pinned runtime image."""

from __future__ import annotations

import json
import sys
from importlib import metadata
from pathlib import Path


def main() -> int:
    """Compare every recorded distribution to image contents without resolving PyPI."""

    lock = json.loads(Path("/tmp/release-runtime-lock.json").read_text(encoding="utf-8"))
    if lock.get("schema_version") != 1 or lock.get("lock_kind") != "immutable_runtime_image":
        raise SystemExit("invalid runtime lock schema")
    if lock.get("python") != ".".join(map(str, sys.version_info[:2])):
        raise SystemExit("runtime lock Python version mismatch")
    distributions = lock.get("distributions")
    if not isinstance(distributions, dict) or not distributions:
        raise SystemExit("runtime lock distributions are missing")
    mismatches = [
        name
        for name, expected in sorted(distributions.items())
        if not isinstance(name, str)
        or not isinstance(expected, str)
        or _installed_version(name) != expected
    ]
    if mismatches:
        raise SystemExit("runtime lock mismatch: " + ", ".join(mismatches))
    return 0


def _installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


if __name__ == "__main__":  # pragma: no cover - Docker build entry point
    raise SystemExit(main())
