"""Canonical, create-only JSON artifact storage."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any


class ArtifactStoreError(RuntimeError):
    """Base error for local immutable artifact storage."""


class UnsafeArtifactPathError(ArtifactStoreError):
    """Raised when an artifact path could leave the configured store."""


class ArtifactExistsError(ArtifactStoreError):
    """Raised when a create-only write would replace an existing artifact."""


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """The relative location and content hash of an immutable JSON artifact."""

    path: Path
    content_hash: str


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON deterministically for hashing and persistence."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    """Hash the canonical JSON representation of ``value``."""

    return sha256_bytes(canonical_json_bytes(value))


class ArtifactStore:
    """A local store that permits only atomic JSON creation."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def create(self, artifact_type: str, payload: Any) -> ArtifactRef:
        """Create a hash-addressed JSON artifact beneath ``artifact_type``."""

        self._validate_artifact_type(artifact_type)
        content_hash = sha256_json(payload)
        path = Path(artifact_type) / f"{content_hash}.json"
        return self.write_json(path, payload, expected_hash=content_hash)

    def write_json(
        self,
        relative_path: Path | str,
        payload: Any,
        *,
        expected_hash: str | None = None,
    ) -> ArtifactRef:
        """Atomically create ``relative_path`` and reject every overwrite."""

        target, normalized = self._safe_path(relative_path)
        contents = canonical_json_bytes(payload)
        content_hash = sha256_bytes(contents)
        if expected_hash is not None and expected_hash != content_hash:
            raise ArtifactStoreError("expected hash does not match canonical JSON content")
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as error:
            raise ArtifactExistsError(f"artifact already exists: {normalized}") from error
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                target.unlink()
            except FileNotFoundError:
                pass
            raise
        return ArtifactRef(path=normalized, content_hash=content_hash)

    def read_json(self, relative_path: Path | str) -> Any:
        """Read a JSON artifact without relaxing path containment checks."""

        target, _ = self._safe_path(relative_path)
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as error:
            raise ArtifactStoreError(f"artifact does not exist: {relative_path}") from error

    def _safe_path(self, candidate: Path | str) -> tuple[Path, Path]:
        path = Path(candidate)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise UnsafeArtifactPathError(f"unsafe artifact path: {candidate!s}")
        normalized = Path(*PurePath(path).parts)
        target = (self._root / normalized).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as error:
            raise UnsafeArtifactPathError(f"unsafe artifact path: {candidate!s}") from error
        return target, normalized

    @staticmethod
    def _validate_artifact_type(artifact_type: str) -> None:
        if not artifact_type or any(separator in artifact_type for separator in ("/", "\\")):
            raise UnsafeArtifactPathError(f"unsafe artifact type: {artifact_type!r}")
