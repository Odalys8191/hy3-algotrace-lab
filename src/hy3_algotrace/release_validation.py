"""Fail-closed checks for the repository's public release surface."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

DISCLAIMER = "个人活动实战作品，非腾讯官方发布"
REQUIRED_RELEASE_FILES = (
    "README.md",
    ".env.example",
    ".dockerignore",
    "compose.yaml",
    "docker/release-runtime-lock.json",
    "docker/verify-runtime-lock.py",
    ".github/workflows/ci.yml",
    ".gitleaks.toml",
    "docs/release-security.md",
    "docs/reproducibility.md",
    "docs/demo.md",
    "docs/license-and-attribution.md",
    "docs/method-report-template.md",
    "docs/results-report-template.md",
    "docs/audit-record-template.md",
)
_SECRET_NAME = r"(?:API(?:_|)?KEY|TOKEN|SECRET|PASSWORD|PRIVATE(?:_|)?KEY|CREDENTIAL)"
_SECRET_ASSIGNMENT = re.compile(
    rf"(?mi)^\s*(?:export\s+)?([A-Z][A-Z0-9_]*{_SECRET_NAME})\s*(?:=|:)\s*"
    r"[\"']?([^\s#\"']+)"
)
_AUTHORIZATION_VALUE = re.compile(r"(?mi)^\s*authorization\s*[:=]\s*bearer\s+([^\s#]+)")
_SKIP_DIRECTORIES = frozenset({".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv"})
_TEXT_SUFFIXES = frozenset({"", ".example", ".json", ".md", ".py", ".sh", ".toml", ".yaml", ".yml"})
_RUNTIME_LOCK_REQUIRED_DISTRIBUTIONS = frozenset(
    {"fastapi", "hatchling", "httpx", "pydantic", "streamlit", "uvicorn"}
)
_PINNED_VERSION = re.compile(r"\d+(?:[A-Za-z0-9.+!_-]*\d)?\Z")
# A deliberate redaction fixture proves that an asynchronous exception cannot publish a raw
# secret. It is the only static source fixture exemption: both path and identifier must match.
_CONTROLLED_TEST_SECRET_IDENTIFIERS = frozenset({("tests/test_run_service.py", "raw_secret")})


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
    """Validate static release text without retaining or echoing secret values."""

    violations: list[str] = []
    if DISCLAIMER not in files.get("README.md", ""):
        violations.append("README must contain the required non-official disclaimer")
    try:
        _validate_compose_text_ports(files.get("compose.yaml", ""))
    except ReleaseValidationError as error:
        violations.append(str(error))
    runtime_lock = files.get("docker/release-runtime-lock.json")
    if runtime_lock is not None:
        try:
            _validate_runtime_lock(runtime_lock)
        except ReleaseValidationError as error:
            violations.append(str(error))
    secret_findings = _find_secret_assignments(files)
    violations.extend(secret_findings)
    if violations:
        raise ReleaseValidationError("; ".join(violations))
    return ReleaseValidationReport(checked_files=tuple(sorted(files)), secret_findings=())


def validate_rendered_compose(rendered: Mapping[str, object]) -> None:
    """Require rendered Docker Compose ports to bind only to ``127.0.0.1``.

    It consumes ``docker compose config --format json`` output, so comments, short
    YAML syntax, interpolation, and formatting cannot become public port exposure.
    An absent ``host_ip`` is Docker's public default and is therefore rejected.
    """

    services = rendered.get("services")
    if not isinstance(services, Mapping):
        raise ReleaseValidationError("rendered Compose must contain a services mapping")
    for service_name, raw_service in services.items():
        if not isinstance(service_name, str) or not isinstance(raw_service, Mapping):
            raise ReleaseValidationError("rendered Compose service is malformed")
        if raw_service.get("network_mode") == "host":
            raise ReleaseValidationError("Compose must not use host network mode")
        raw_ports = raw_service.get("ports", ())
        if not isinstance(raw_ports, Sequence) or isinstance(raw_ports, (str, bytes)):
            raise ReleaseValidationError("rendered Compose ports must be a list")
        for raw_port in raw_ports:
            if _rendered_host_ip(raw_port) != "127.0.0.1":
                raise ReleaseValidationError("Compose port mappings must bind to localhost")


def main(argv: Sequence[str] | None = None) -> int:
    """Run repository release checks without printing possible secret material."""

    parser = argparse.ArgumentParser(
        description="Validate release documentation and safe defaults."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--rendered-compose",
        type=Path,
        help="JSON from docker compose config --format json; required by the Docker CI job",
    )
    arguments = parser.parse_args(argv)
    try:
        report = validate_release_tree(arguments.root)
        if arguments.rendered_compose is not None:
            rendered = json.loads(arguments.rendered_compose.read_text(encoding="utf-8"))
            if not isinstance(rendered, Mapping):
                raise ReleaseValidationError("rendered Compose document must be an object")
            validate_rendered_compose(cast(Mapping[str, object], rendered))
    except (OSError, json.JSONDecodeError, ReleaseValidationError):
        print("release validation failed")
        return 1
    print(f"release validation passed ({len(report.checked_files)} files checked)")
    return 0


def _validate_compose_text_ports(compose: str) -> None:
    """Fail closed on source Compose syntax before Docker is available.

    CI also validates Docker's rendered JSON. This small parser accepts only the two
    documented Compose port forms and requires a literal loopback address in each.
    Unknown syntax is unsafe rather than silently ignored.
    """

    lines = tuple(_strip_yaml_comment(line) for line in compose.splitlines())
    ports_seen = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped_line = line.strip()
        if not stripped_line.startswith("ports:"):
            index += 1
            continue
        ports_seen = True
        section_indent = _indent(line)
        inline = stripped_line.removeprefix("ports:").strip()
        if inline:
            entries = [{"first": item} for item in _flow_sequence_values(inline)]
            index += 1
        else:
            entries = []
            index += 1
        while not inline and index < len(lines):
            current = lines[index]
            stripped = current.strip()
            if stripped and _indent(current) <= section_indent:
                break
            if not stripped:
                index += 1
                continue
            if stripped.startswith("- "):
                entries.append({"first": stripped[2:].strip()})
            elif entries and ":" in stripped:
                key, value = stripped.split(":", maxsplit=1)
                entries[-1][key.strip()] = _unquote(value.strip())
            elif stripped.startswith("["):
                entries.extend({"first": item} for item in _flow_sequence_values(stripped))
            else:
                raise ReleaseValidationError("Compose port mappings must bind to localhost")
            index += 1
        for entry in entries:
            first = _unquote(entry["first"])
            if "target" in entry or first.startswith("target:"):
                if first.startswith("target:"):
                    _, value = first.split(":", maxsplit=1)
                    entry["target"] = _unquote(value.strip())
                if entry.get("host_ip") != "127.0.0.1":
                    raise ReleaseValidationError("Compose port mappings must bind to localhost")
            elif not first.startswith("127.0.0.1:"):
                raise ReleaseValidationError("Compose port mappings must bind to localhost")
    if not ports_seen:
        raise ReleaseValidationError("Compose port mappings must bind to localhost")


def _rendered_host_ip(port: object) -> str | None:
    if isinstance(port, str):
        parts = port.rsplit(":", maxsplit=2)
        return parts[0] if len(parts) == 3 else None
    if isinstance(port, Mapping):
        host_ip = port.get("host_ip")
        return host_ip if isinstance(host_ip, str) else None
    return None


def _validate_runtime_lock(text: str) -> None:
    """Check the checked-in manifest for a complete immutable-runtime dependency closure."""

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ReleaseValidationError("runtime lock is invalid") from error
    if not isinstance(payload, Mapping):
        raise ReleaseValidationError("runtime lock is invalid")
    distributions = payload.get("distributions")
    if (
        payload.get("schema_version") != 1
        or payload.get("lock_kind") != "immutable_runtime_image"
        or payload.get("python") != "3.12"
        or not isinstance(distributions, Mapping)
        or len(distributions) < 40
        or not _RUNTIME_LOCK_REQUIRED_DISTRIBUTIONS.issubset(distributions)
        or any(
            not isinstance(name, str)
            or not isinstance(version, str)
            or _PINNED_VERSION.fullmatch(version) is None
            for name, version in distributions.items()
        )
    ):
        raise ReleaseValidationError("runtime lock is invalid")


def _find_secret_assignments(files: Mapping[str, str]) -> tuple[str, ...]:
    findings: set[str] = set()
    for path, text in files.items():
        for name, value in _SECRET_ASSIGNMENT.findall(text):
            if (path, name.casefold()) in _CONTROLLED_TEST_SECRET_IDENTIFIERS:
                continue
            if not _is_placeholder(value):
                findings.add(f"secret-like value in {path} ({name})")
        for value in _AUTHORIZATION_VALUE.findall(text):
            if not _is_placeholder(value):
                findings.add(f"secret-like Authorization value in {path}")
    return tuple(sorted(findings))


def _is_placeholder(value: str) -> bool:
    normalized = value.casefold()
    return (
        normalized in {"", "changeme", "placeholder", "redacted"}
        or normalized.startswith("your_")
        or normalized.startswith("replace_")
        or normalized.startswith("<")
        or normalized.startswith("${")
    )


def _release_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in _SKIP_DIRECTORIES for part in path.relative_to(root).parts)
        and path.name != ".env"
        and path.suffix in _TEXT_SUFFIXES
    )


def _read_release_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_yaml_comment(line: str) -> str:
    quote: str | None = None
    for index, character in enumerate(line):
        if character in {"'", '"'}:
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        elif character == "#" and quote is None:
            return line[:index].rstrip()
    return line.rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _flow_sequence_values(value: str) -> tuple[str, ...]:
    if not value.endswith("]"):
        raise ReleaseValidationError("Compose port mappings must bind to localhost")
    return tuple(_unquote(item.strip()) for item in value[1:-1].split(",") if item.strip())


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())
