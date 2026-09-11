"""Execution-intent freeze: non-circular intent hashing and manifest verification.

``docs/FORMAL_CORPUS_LIFECYCLE.md`` §2.2 originally defined a circular hash:
``intent_hash`` covered ``benchmark_id`` and ``config_sha256``, the runtime config
embedded ``benchmark_id``, and ``benchmark_id`` was derived from ``intent_hash``.
This module splits that freeze into three explicitly named steps so the whole
chain can be computed in one pass:

1. :meth:`IntentIdentity.identity_hash` hashes only the execution-intent core
   fields, never ``benchmark_id``, ``config_sha256``, or ``intent_hash``, so the
   identifier can be derived from it.
2. :func:`compute_config_sha256` hashes the ``config.runtime`` file bytes after
   the derived ``benchmark_id`` has been embedded in the config.
3. :func:`compute_intent_hash` hashes the sealed manifest, which binds the
   identity to those config bytes. Run results cite this ``intent_hash``.

The manifest also carries the model read timeout, so a frozen timeout can no
longer disagree with the process environment without invalidating the intent.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .artifacts import canonical_json_bytes, sha256_bytes, sha256_json
from .benchmark_models import (
    BENCHMARK_SCHEMA_VERSION,
    BenchmarkConfig,
    BenchmarkModel,
    BenchmarkSchemaVersion,
)
from .hy3_client import endpoint_identity

INTENT_KIND: Literal["formal_execution_intent"] = "formal_execution_intent"
BENCHMARK_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
_DERIVED_INTENT_KEYS = ("benchmark_id", "config_sha256", "intent_hash")
_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
_ID_SUFFIX_LENGTH = 12


class IntentManifestError(RuntimeError):
    """Raised when a manifest, its config bytes, or its runtime identity disagree."""


class IntentPromptVersions(BenchmarkModel):
    """The four prompt versions frozen by execution-intent item #4."""

    generator: str = Field(min_length=1, strict=True)
    logic_review: str = Field(min_length=1, strict=True)
    adversarial_review: str = Field(min_length=1, strict=True)
    arbiter: str = Field(min_length=1, strict=True)


class IntentIdentity(BenchmarkModel):
    """The execution-intent core fields, excluding every derived identifier."""

    schema_version: BenchmarkSchemaVersion = BENCHMARK_SCHEMA_VERSION
    kind: Literal["formal_execution_intent"] = INTENT_KIND
    recorded_at: datetime
    formal: bool = Field(strict=True)
    selection_hash: str = Field(min_length=64, max_length=64, strict=True)
    corpus_hash: str = Field(min_length=64, max_length=64, strict=True)
    prompt_versions: IntentPromptVersions
    code_revision: str = Field(min_length=1, strict=True)
    worktree_clean: bool = Field(strict=True)
    judge_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    timeout_seconds: float
    model: str = Field(min_length=1, strict=True)
    endpoint_identity: str = Field(min_length=1, strict=True)
    remote_attempt_budget: int = Field(gt=0, le=500, strict=True)

    @model_validator(mode="after")
    def validate_frozen_identity(self) -> Self:
        for digest in (self.selection_hash, self.corpus_hash):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("intent selection and corpus hashes must be lowercase SHA-256")
        if self.recorded_at.tzinfo is None:
            raise ValueError("intent recorded_at must be timezone-aware")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("intent timeout_seconds must be finite and positive")
        parsed = urlsplit(self.endpoint_identity)
        if (
            parsed.scheme != "https"
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("intent endpoint identity must be credential-free absolute HTTPS")
        if self.endpoint_identity != endpoint_identity(self.endpoint_identity):
            raise ValueError("intent endpoint identity must already be normalized")
        return self

    def intent_payload(self) -> dict[str, Any]:
        """Return the hashed payload: every frozen field except derived identities."""

        payload = self.model_dump(mode="json")
        for derived in _DERIVED_INTENT_KEYS:
            payload.pop(derived, None)
        return payload

    def identity_hash(self) -> str:
        """Hash the execution-intent core fields such that ``benchmark_id`` can derive."""

        return sha256_json(self.intent_payload())

    def derive_benchmark_id(self, slug: str) -> str:
        """Derive ``<slug>-<identity_hash[:12]>`` so a changed intent cannot reuse an ID."""

        if not re.fullmatch(_SLUG_PATTERN, slug):
            raise IntentManifestError("intent slug must be a nonempty alphanumeric token")
        candidate = f"{slug}-{self.identity_hash()[:_ID_SUFFIX_LENGTH]}"
        if not re.fullmatch(BENCHMARK_ID_PATTERN, candidate):
            raise IntentManifestError("derived benchmark ID violates the frozen ID pattern")
        return candidate


class IntentManifest(IntentIdentity):
    """A sealed intent: the identity, its derived ID, and the frozen config bytes."""

    benchmark_id: str = Field(pattern=BENCHMARK_ID_PATTERN)
    config_sha256: str = Field(min_length=64, max_length=64, strict=True)
    intent_hash: str = Field(min_length=64, max_length=64, strict=True)

    @model_validator(mode="after")
    def validate_derived_hashes(self) -> Self:
        for digest in (self.config_sha256, self.intent_hash):
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("manifest hashes must be lowercase SHA-256")
        return self


def compute_config_sha256(config_bytes: bytes) -> str:
    """Hash the exact ``config.runtime`` file bytes."""

    return sha256_bytes(config_bytes)


def compute_intent_hash(manifest: IntentManifest) -> str:
    """Hash the sealed manifest content, excluding ``intent_hash`` itself."""

    payload = manifest.model_dump(mode="json")
    payload.pop("intent_hash")
    return sha256_json(payload)


def seal_intent_manifest(
    identity: IntentIdentity,
    *,
    slug: str,
    config_bytes: bytes,
) -> IntentManifest:
    """Derive the benchmark ID, bind the config bytes, and seal the intent hash."""

    payload = identity.intent_payload() | {
        "benchmark_id": identity.derive_benchmark_id(slug),
        "config_sha256": compute_config_sha256(config_bytes),
    }
    payload["intent_hash"] = sha256_json(payload)
    return IntentManifest.model_validate(payload)


def expected_benchmark_id_suffix(manifest: IntentIdentity) -> str:
    """Return the derived suffix every honest ``benchmark_id`` must end with."""

    return manifest.identity_hash()[:_ID_SUFFIX_LENGTH]


def assert_config_matches_manifest(config: BenchmarkConfig, manifest: IntentManifest) -> None:
    """Fail closed when the frozen config no longer matches its sealed intent."""
    config_prompts = {
        "generator": config.generator_prompt_version,
        "logic_review": config.logic_review_prompt_version,
        "adversarial_review": config.adversarial_review_prompt_version,
        "arbiter": config.arbiter_prompt_version,
    }
    frozen_prompts = manifest.prompt_versions.model_dump(mode="json")
    frozen_timeout = config.timeout_seconds
    if frozen_timeout is None:
        raise IntentManifestError("frozen config does not carry the sealed read timeout")
    disagreements = {
        "benchmark_id": (config.benchmark_id, manifest.benchmark_id),
        "formal": (config.formal, manifest.formal),
        "selection_hash": (config.selection_hash, manifest.selection_hash),
        "corpus_hash": (config.corpus_hash, manifest.corpus_hash),
        "code_revision": (config.code_revision, manifest.code_revision),
        "judge_image_digest": (config.judge_image_digest, manifest.judge_image_digest),
        "timeout_seconds": (frozen_timeout, manifest.timeout_seconds),
        "model": (config.model, manifest.model),
        "endpoint_identity": (config.endpoint_identity, manifest.endpoint_identity),
        "remote_attempt_budget": (
            config.remote_attempt_budget,
            manifest.remote_attempt_budget,
        ),
    }
    mismatched = sorted(name for name, pair in disagreements.items() if pair[0] != pair[1])
    if mismatched:
        raise IntentManifestError(
            "frozen config disagrees with the sealed intent: " + ", ".join(mismatched)
        )
    if config_prompts != frozen_prompts:
        raise IntentManifestError("frozen prompt versions disagree with the sealed intent")


def verify_intent_manifest(
    manifest: IntentManifest,
    *,
    config_bytes: bytes,
    code_revision: str | None = None,
) -> None:
    """Verify the intent hash, the config bytes, the derived ID, and the code revision."""

    if not manifest.benchmark_id.endswith(expected_benchmark_id_suffix(manifest)):
        raise IntentManifestError("benchmark_id is not derived from the frozen intent hash")
    sealed = compute_intent_hash(manifest)
    if sealed != manifest.intent_hash:
        raise IntentManifestError("manifest content does not match its own intent hash")
    if compute_config_sha256(config_bytes) != manifest.config_sha256:
        raise IntentManifestError("frozen config bytes do not match the sealed intent")
    try:
        config = BenchmarkConfig.model_validate_json(config_bytes)
    except ValueError as error:
        raise IntentManifestError("frozen config bytes are not a valid benchmark config") from error
    assert_config_matches_manifest(config, manifest)
    if code_revision is not None and manifest.code_revision != code_revision:
        raise IntentManifestError("frozen code revision does not match the running code")


def load_intent_manifest(path: Path) -> IntentManifest:
    """Read a sealed intent manifest from disk."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise IntentManifestError("intent manifest cannot be read") from error
    try:
        return IntentManifest.model_validate_json(payload)
    except ValueError as error:
        raise IntentManifestError("intent manifest is not a valid sealed intent") from error


def manifest_bytes(manifest: IntentManifest) -> bytes:
    """Return the canonical bytes of a sealed manifest."""

    return canonical_json_bytes(manifest.model_dump(mode="json"))
