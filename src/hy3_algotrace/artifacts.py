"""Canonical JSON and create-only storage rooted at a trusted directory handle."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any


class ArtifactStoreError(RuntimeError):
    """Base error for local immutable artifact storage."""


class UnsafeArtifactPathError(ArtifactStoreError):
    """Raised when a path is absolute, traverses, or contains a symlink."""


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
    """Atomic create-only JSON store that never resolves an untrusted child path.

    Every operation after initialization is relative to ``_root_fd``. Child
    directories use ``O_NOFOLLOW`` and publication uses link, which atomically
    fails rather than replacing an existing final path.
    """

    def __init__(self, root: Path | str) -> None:
        root_path = Path(root)
        root_path.mkdir(parents=True, exist_ok=True)
        self._root = root_path.resolve(strict=True)
        try:
            self._root_fd = os.open(self._root, _DIRECTORY_FLAGS)
        except OSError as error:
            raise ArtifactStoreError(f"cannot open artifact root: {self._root}") from error

    def __del__(self) -> None:  # pragma: no cover - shutdown timing is implementation-defined
        try:
            os.close(self._root_fd)
        except (AttributeError, OSError):
            pass

    @property
    def root(self) -> Path:
        return self._root

    def create(self, artifact_type: str, payload: Any) -> ArtifactRef:
        """Create a hash-addressed JSON artifact beneath ``artifact_type``."""

        self._validate_artifact_type(artifact_type)
        content_hash = sha256_json(payload)
        return self.write_json(
            Path(artifact_type) / f"{content_hash}.json",
            payload,
            expected_hash=content_hash,
        )

    def write_json(
        self,
        relative_path: Path | str,
        payload: Any,
        *,
        expected_hash: str | None = None,
    ) -> ArtifactRef:
        """Complete, fsync, then atomically publish a JSON file exactly once."""

        normalized = _normalize_relative_path(relative_path)
        contents = canonical_json_bytes(payload)
        content_hash = sha256_bytes(contents)
        if expected_hash is not None and expected_hash != content_hash:
            raise ArtifactStoreError("expected hash does not match canonical JSON content")
        parent_fd, filename = self._open_parent(normalized, create=True)
        temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
        temporary_fd: int | None = None
        try:
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            _write_all(temporary_fd, contents)
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            try:
                os.link(
                    temporary_name,
                    filename,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise ArtifactExistsError(f"artifact already exists: {normalized}") from error
            _fsync_directory(parent_fd)
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)
        return ArtifactRef(path=normalized, content_hash=content_hash)

    def read_json(self, relative_path: Path | str) -> Any:
        """Read JSON through no-follow file descriptors rooted at the store."""

        normalized = _normalize_relative_path(relative_path)
        parent_fd, filename = self._open_parent(normalized, create=False)
        try:
            file_fd = os.open(filename, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        except FileNotFoundError as error:
            os.close(parent_fd)
            raise ArtifactStoreError(f"artifact does not exist: {normalized}") from error
        try:
            with os.fdopen(file_fd, "r", encoding="utf-8") as handle:
                return json.load(handle)
        finally:
            os.close(parent_fd)

    def _open_parent(self, relative_path: Path, *, create: bool) -> tuple[int, str]:
        parent_fd = os.dup(self._root_fd)
        try:
            for component in relative_path.parts[:-1]:
                if create:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=parent_fd)
                    except FileExistsError:
                        pass
                try:
                    child_fd = os.open(component, _DIRECTORY_FLAGS, dir_fd=parent_fd)
                except OSError as error:
                    if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                        raise UnsafeArtifactPathError(
                            f"unsafe artifact path: {relative_path}"
                        ) from error
                    raise
                os.close(parent_fd)
                parent_fd = child_fd
            return parent_fd, relative_path.name
        except BaseException:
            os.close(parent_fd)
            raise

    @staticmethod
    def _validate_artifact_type(artifact_type: str) -> None:
        if not artifact_type or any(separator in artifact_type for separator in ("/", "\\")):
            raise UnsafeArtifactPathError(f"unsafe artifact type: {artifact_type!r}")


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW


def _normalize_relative_path(candidate: Path | str) -> Path:
    path = Path(candidate)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeArtifactPathError(f"unsafe artifact path: {candidate!s}")
    return Path(*PurePath(path).parts)


def _write_all(file_descriptor: int, contents: bytes) -> None:
    offset = 0
    while offset < len(contents):
        written = os.write(file_descriptor, contents[offset:])
        if written <= 0:
            raise ArtifactStoreError("failed to write complete artifact content")
        offset += written


def _fsync_directory(file_descriptor: int) -> None:
    try:
        os.fsync(file_descriptor)
    except OSError as error:
        if error.errno != errno.EINVAL:
            raise
