"""Fail-closed checks for the repository's public release surface."""

from __future__ import annotations

import argparse
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

DISCLAIMER = "个人活动实战作品，非腾讯官方发布"
REQUIRED_RELEASE_FILES = (
    "README.md",
    ".env.example",
    "compose.yaml",
    ".github/workflows/ci.yml",
    "docs/release-security.md",
    "docs/reproducibility.md",
    "docs/demo.md",
    "docs/license-and-attribution.md",
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?m)^\s*(?:export\s+)?([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PRIVATE_KEY))"
    r"\s*=\s*[\"']?([^\s#\"']+)"
)
_PUBLIC_BIND = re.compile(r"(?:^|[\"'\s\[])0\.0\.0\.0:\d+:")
_SKIP_DIRECTORIES = frozenset({".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"})


class ReleaseValidationError(ValueError):
    """Raised when a release artifact is incomplete or unsafe to publish."""


@dataclass(frozen=True, slots=True)
class ReleaseValidationReport:
    """A successful validation record with no credential values retained."""

    checked_files: tuple[str, ...]
    secret_findings: tuple[str, ...] = ()


def validate_release_tree(root: Path | str) -> ReleaseValidationReport:
    """Validate required release files and scan tracked-style text files safely."""

    root_path = Path(root)
    missing = [path for path in REQUIRED_RELEASE_FILES if not (root_path / path).is_file()]
    if missing:
        raise ReleaseValidationError("missing required release file: " + ", ".join(sorted(missing)))
    files = {
        path.relative_to(root_path).as_posix(): _read_release_text(path)
        for path in _release_files(root_path)
    }
    report = validate_release_files(files)
    return ReleaseValidationReport(
        checked_files=tuple(sorted(files)), secret_findings=report.secret_findings
    )


def validate_release_files(files: Mapping[str, str]) -> ReleaseValidationReport:
    """Validate release text without retaining or echoing possible secret values."""

    violations: list[str] = []
    readme = files.get("README.md", "")
    if DISCLAIMER not in readme:
        violations.append("README must contain the required non-official disclaimer")
    compose = files.get("compose.yaml", "")
    if "127.0.0.1:" not in compose:
        violations.append("Compose port mappings must bind to localhost")
    if _PUBLIC_BIND.search(compose):
        violations.append("Compose must not publish a non-localhost port mapping")
    secret_findings = tuple(
        sorted(
            f"secret-like value in {path} ({name})"
            for path, text in files.items()
            for name, value in _SECRET_ASSIGNMENT.findall(text)
            if not _is_placeholder(value)
        )
    )
    violations.extend(secret_findings)
    if violations:
        raise ReleaseValidationError("; ".join(violations))
    return ReleaseValidationReport(checked_files=tuple(sorted(files)), secret_findings=())


def main(argv: Sequence[str] | None = None) -> int:
    """Run repository release checks without printing potentially secret content."""

    parser = argparse.ArgumentParser(
        description="Validate release documentation and safe defaults."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    arguments = parser.parse_args(argv)
    try:
        report = validate_release_tree(arguments.root)
    except (OSError, ReleaseValidationError):
        print("release validation failed")
        return 1
    print(f"release validation passed ({len(report.checked_files)} files checked)")
    return 0


def _is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return (
        normalized in {"", "changeme", "placeholder"}
        or normalized.startswith("your_")
        or normalized.startswith("<")
        or normalized.startswith("${")
    )


def _release_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts)
        and path.suffix in {"", ".example", ".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"}
    )


def _read_release_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
