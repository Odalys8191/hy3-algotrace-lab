"""Create-only, conservative carryover for failed non-formal live runs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .artifacts import ArtifactRef, ArtifactStore, sha256_json
from .benchmark_models import BenchmarkConfig
from .formal_lifecycle import CodeIdentity
from .prompts import (
    ADVERSARIAL_REVIEW_PROMPT_VERSION,
    ARBITER_PROMPT_VERSION,
    GENERATOR_PROMPT_VERSION,
    LOGIC_REVIEW_PROMPT_VERSION,
)

_IDENTITY = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"
_HASH = r"^[0-9a-f]{64}$"


def _amount(value: str) -> Decimal:
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("RMB values must be finite nonnegative decimals") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError("RMB values must be finite nonnegative decimals")
    return amount


def _amount_text(value: Decimal) -> str:
    return format(value, "f")


def _cost_text(value: Decimal) -> str:
    return format(value, ".6f")


class NonformalRunCarryover(BaseModel):
    """Binds a successor identity to immutable failed-run evidence and shared caps."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["nonformal_run_carryover"] = "nonformal_run_carryover"
    formal: Literal[False] = False
    predecessor_benchmark_id: str = Field(pattern=_IDENTITY)
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_failure_hash: str = Field(pattern=_HASH)
    predecessor_ledger_index_hash: str = Field(pattern=_HASH)
    predecessor_event_hashes: tuple[str, ...]
    consumed_attempts: int = Field(ge=0, le=220, strict=True)
    remote_attempt_limit: int = Field(ge=1, le=220, strict=True)
    spend_limit_rmb: str
    charged_upper_bound_rmb: str
    cost_evidence: Literal[
        "conservative_full_cap_unknown_usage",
        "provider_usage_complete",
    ]
    unknown_usage_attempts: tuple[int, ...] = ()

    @field_validator("predecessor_event_hashes")
    @classmethod
    def valid_event_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        invalid = any(
            len(item) != 64 or any(char not in "0123456789abcdef" for char in item)
            for item in value
        )
        if invalid:
            raise ValueError("predecessor event hashes must be lowercase SHA-256 digests")
        return value

    @field_validator("spend_limit_rmb", "charged_upper_bound_rmb")
    @classmethod
    def valid_amount(cls, value: str) -> str:
        _amount(value)
        return value

    @model_validator(mode="after")
    def valid_carryover(self) -> Self:
        if self.predecessor_benchmark_id == self.successor_benchmark_id:
            raise ValueError("successor identity must differ from predecessor")
        if self.consumed_attempts > self.remote_attempt_limit:
            raise ValueError("consumed attempts exceed the shared attempt limit")
        if len(self.predecessor_event_hashes) != self.consumed_attempts:
            raise ValueError("predecessor event hashes must account for every consumed attempt")
        expected_unknown = tuple(sorted(set(self.unknown_usage_attempts)))
        if self.unknown_usage_attempts != expected_unknown or any(
            sequence < 1 or sequence > self.consumed_attempts for sequence in expected_unknown
        ):
            raise ValueError("unknown usage attempts must be ordered consumed attempt sequences")
        limit = _amount(self.spend_limit_rmb)
        charged = _amount(self.charged_upper_bound_rmb)
        if limit <= 0 or charged > limit:
            raise ValueError("charged upper bound must not exceed the positive spend limit")
        if self.cost_evidence == "conservative_full_cap_unknown_usage":
            if not self.unknown_usage_attempts or charged != limit:
                raise ValueError("unknown usage must conservatively consume the full spend cap")
        elif self.unknown_usage_attempts:
            raise ValueError("complete provider usage cannot retain unknown attempts")
        return self

    @property
    def remaining_attempts(self) -> int:
        return self.remote_attempt_limit - self.consumed_attempts

    @property
    def remaining_upper_bound_rmb(self) -> str:
        return _amount_text(_amount(self.spend_limit_rmb) - _amount(self.charged_upper_bound_rmb))


class ContinuationPreflight(BaseModel):
    """Safe offline result; it carries no prompts, responses, or problem content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["nonformal_continuation_preflight"] = "nonformal_continuation_preflight"
    formal_eligibility: Literal[False] = False
    predecessor_benchmark_id: str = Field(pattern=_IDENTITY)
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_evidence_valid: Literal[True] = True
    consumed_attempts: int = Field(ge=0, le=220, strict=True)
    remaining_attempts: int = Field(ge=0, le=220, strict=True)
    remote_attempt_limit: int = Field(ge=1, le=220, strict=True)
    spend_limit_rmb: str
    charged_upper_bound_rmb: str
    remaining_upper_bound_rmb: str
    ready_for_remote_run: bool = Field(strict=True)
    block_reason: (
        Literal[
            "attempt_cap_exhausted",
            "spend_cap_exhausted_by_conservative_carryover",
        ]
        | None
    )
    successor_config_hash: str | None = Field(default=None, pattern=_HASH)
    source_identity_hash: str | None = Field(default=None, pattern=_HASH)
    source_tree_hash: str | None = Field(default=None, pattern=_HASH)


class NonformalResourceAuthorization(BaseModel):
    """A bounded additive resource tranche; it does not rewrite historical cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["nonformal_resource_authorization"] = "nonformal_resource_authorization"
    formal: Literal[False] = False
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    provider: Literal["TokenHub"]
    model: Literal["hy3"]
    free_token_limit: int = Field(gt=0, le=5_000_000, strict=True)
    additional_spend_limit_rmb: str
    evidence: Literal["user_attested_console_remaining_quota"]
    billing_priority: Literal["free_quota_first"]
    data_scope: Literal["public_codeforces_and_project_authored_trace_code"]

    @field_validator("additional_spend_limit_rmb")
    @classmethod
    def valid_additional_amount(cls, value: str) -> str:
        if _amount(value) <= 0:
            raise ValueError("additional RMB spend limit must be positive")
        return value


class AuthorizedContinuationPreflight(BaseModel):
    """Identity-bound offline gate for a new, separately capped resource tranche."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["authorized_nonformal_continuation_preflight"] = (
        "authorized_nonformal_continuation_preflight"
    )
    formal_eligibility: Literal[False] = False
    predecessor_benchmark_id: str = Field(pattern=_IDENTITY)
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_evidence_valid: Literal[True] = True
    consumed_attempts: int = Field(ge=0, le=220, strict=True)
    remaining_attempts: int = Field(ge=0, le=220, strict=True)
    remote_attempt_limit: int = Field(ge=1, le=220, strict=True)
    historical_spend_limit_rmb: str
    historical_charged_upper_bound_rmb: str
    free_token_limit: int = Field(gt=0, le=5_000_000, strict=True)
    additional_spend_limit_rmb: str
    provider: Literal["TokenHub"]
    model: Literal["hy3"]
    ready_for_remote_run: bool = Field(strict=True)
    block_reason: Literal["attempt_cap_exhausted"] | None
    successor_config_hash: str | None = Field(default=None, pattern=_HASH)
    source_identity_hash: str | None = Field(default=None, pattern=_HASH)
    source_tree_hash: str | None = Field(default=None, pattern=_HASH)
    carryover_hash: str | None = Field(default=None, pattern=_HASH)
    authorization_hash: str | None = Field(default=None, pattern=_HASH)


class AuthorizedPackageHashes(BaseModel):
    """Hashes every immutable document that authorized the failed parent run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_identity_hash: str = Field(pattern=_HASH)
    config_hash: str = Field(pattern=_HASH)
    carryover_hash: str = Field(pattern=_HASH)
    authorization_hash: str = Field(pattern=_HASH)
    preflight_hash: str = Field(pattern=_HASH)


class AttemptSettlementEvidence(BaseModel):
    """Hash-only pointer to one allowlisted attempt settlement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1, le=220, strict=True)
    path: str = Field(min_length=1, max_length=512)
    content_hash: str = Field(pattern=_HASH)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
            raise ValueError("settlement evidence path must be normalized and relative")
        return value


class NonformalRunChainCarryover(BaseModel):
    """Binds an ancestor authorization package and a later failed run without reset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["nonformal_run_chain_carryover"] = "nonformal_run_chain_carryover"
    formal: Literal[False] = False
    ancestor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_benchmark_id: str = Field(pattern=_IDENTITY)
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    parent_package_hashes: AuthorizedPackageHashes
    parent_consumed_attempts: int = Field(ge=0, le=220, strict=True)
    predecessor_failure_hash: str = Field(pattern=_HASH)
    predecessor_ledger_index_hash: str = Field(pattern=_HASH)
    predecessor_event_hashes: tuple[str, ...]
    settlements: tuple[AttemptSettlementEvidence, ...]
    consumed_attempts: int = Field(ge=1, le=220, strict=True)
    remote_attempt_limit: int = Field(ge=1, le=220, strict=True)
    historical_spend_limit_rmb: str
    historical_charged_upper_bound_rmb: str
    historical_unknown_usage_attempts: tuple[int, ...]
    resource_token_limit: int = Field(gt=0, le=5_000_000, strict=True)
    resource_charged_upper_bound_tokens: int = Field(ge=0, strict=True)
    resource_spend_limit_rmb: str
    resource_charged_upper_bound_rmb: str
    resource_usage_evidence: Literal["provider_usage_complete"] = "provider_usage_complete"
    explicit_remote_reapproval_required: Literal[True] = True

    @field_validator("predecessor_event_hashes")
    @classmethod
    def valid_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        invalid = any(
            len(item) != 64 or any(char not in "0123456789abcdef" for char in item)
            for item in value
        )
        if invalid:
            raise ValueError("predecessor event hashes must be lowercase SHA-256 digests")
        return value

    @field_validator(
        "historical_spend_limit_rmb",
        "historical_charged_upper_bound_rmb",
        "resource_spend_limit_rmb",
        "resource_charged_upper_bound_rmb",
    )
    @classmethod
    def valid_chain_amount(cls, value: str) -> str:
        _amount(value)
        return value

    @model_validator(mode="after")
    def valid_chain(self) -> Self:
        identities = {
            self.ancestor_benchmark_id,
            self.predecessor_benchmark_id,
            self.successor_benchmark_id,
        }
        if len(identities) != 3:
            raise ValueError("chain benchmark identities must be distinct")
        if not self.parent_consumed_attempts < self.consumed_attempts:
            raise ValueError("chain must add attempts after its parent")
        if self.consumed_attempts > self.remote_attempt_limit:
            raise ValueError("consumed attempts exceed the shared attempt limit")
        latest_sequences = tuple(
            range(self.parent_consumed_attempts + 1, self.consumed_attempts + 1)
        )
        if len(self.predecessor_event_hashes) != len(latest_sequences):
            raise ValueError("latest event hashes must account for each added attempt")
        if tuple(item.sequence for item in self.settlements) != latest_sequences:
            raise ValueError("settlements must cover each added attempt in order")
        expected_unknown = tuple(sorted(set(self.historical_unknown_usage_attempts)))
        if self.historical_unknown_usage_attempts != expected_unknown or any(
            sequence < 1 or sequence > self.parent_consumed_attempts
            for sequence in expected_unknown
        ):
            raise ValueError("historical unknown usage sequences are invalid")
        historical_limit = _amount(self.historical_spend_limit_rmb)
        historical_charged = _amount(self.historical_charged_upper_bound_rmb)
        resource_limit = _amount(self.resource_spend_limit_rmb)
        resource_charged = _amount(self.resource_charged_upper_bound_rmb)
        if historical_limit <= 0 or historical_charged != historical_limit:
            raise ValueError("unknown historical usage must retain its full spend cap")
        if resource_limit <= 0 or resource_charged > resource_limit:
            raise ValueError("resource RMB charge must remain within its cap")
        if self.resource_charged_upper_bound_tokens > self.resource_token_limit:
            raise ValueError("resource token charge must remain within its cap")
        return self

    @property
    def remaining_attempts(self) -> int:
        return self.remote_attempt_limit - self.consumed_attempts

    @property
    def remaining_upper_bound_tokens(self) -> int:
        return self.resource_token_limit - self.resource_charged_upper_bound_tokens

    @property
    def remaining_upper_bound_rmb(self) -> str:
        return _cost_text(
            _amount(self.resource_spend_limit_rmb) - _amount(self.resource_charged_upper_bound_rmb)
        )


class PendingChainedAuthorization(BaseModel):
    """Resource carryover record that deliberately grants no new remote start."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["pending_chained_resource_authorization"] = (
        "pending_chained_resource_authorization"
    )
    formal: Literal[False] = False
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    provider: Literal["TokenHub"] = "TokenHub"
    model: Literal["hy3"] = "hy3"
    resource_token_limit: int = Field(gt=0, le=5_000_000, strict=True)
    resource_charged_upper_bound_tokens: int = Field(ge=0, strict=True)
    resource_spend_limit_rmb: str
    resource_charged_upper_bound_rmb: str
    evidence: Literal["verified_failed_parent_carryover"] = "verified_failed_parent_carryover"
    approval_state: Literal["pending_explicit_remote_reapproval"] = (
        "pending_explicit_remote_reapproval"
    )
    data_scope: Literal["public_codeforces_and_project_authored_trace_code"] = (
        "public_codeforces_and_project_authored_trace_code"
    )


class ChainedContinuationPreflight(BaseModel):
    """Offline-only gate for a chain-bound successor awaiting explicit approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    kind: Literal["chained_nonformal_continuation_preflight"] = (
        "chained_nonformal_continuation_preflight"
    )
    formal_eligibility: Literal[False] = False
    ancestor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_benchmark_id: str = Field(pattern=_IDENTITY)
    successor_benchmark_id: str = Field(pattern=_IDENTITY)
    predecessor_evidence_valid: Literal[True] = True
    consumed_attempts: int = Field(ge=1, le=220, strict=True)
    remaining_attempts: int = Field(ge=0, le=220, strict=True)
    remote_attempt_limit: int = Field(ge=1, le=220, strict=True)
    historical_spend_limit_rmb: str
    historical_charged_upper_bound_rmb: str
    resource_token_limit: int = Field(gt=0, le=5_000_000, strict=True)
    resource_charged_upper_bound_tokens: int = Field(ge=0, strict=True)
    remaining_upper_bound_tokens: int = Field(ge=0, strict=True)
    resource_spend_limit_rmb: str
    resource_charged_upper_bound_rmb: str
    remaining_upper_bound_rmb: str
    ready_for_remote_run: Literal[False] = False
    block_reason: Literal["explicit_remote_reapproval_required"] = (
        "explicit_remote_reapproval_required"
    )
    successor_config_hash: str | None = Field(default=None, pattern=_HASH)
    source_identity_hash: str | None = Field(default=None, pattern=_HASH)
    source_tree_hash: str | None = Field(default=None, pattern=_HASH)
    carryover_hash: str | None = Field(default=None, pattern=_HASH)
    authorization_hash: str | None = Field(default=None, pattern=_HASH)


def derive_conservative_carryover(
    *,
    predecessor_artifacts: ArtifactStore,
    predecessor_benchmark_id: str,
    successor_benchmark_id: str,
    remote_attempt_limit: int,
    spend_limit_rmb: str,
) -> NonformalRunCarryover:
    """Derive a full-cap charge when old attempts have no trustworthy usage evidence."""

    root = Path("benchmarks") / predecessor_benchmark_id
    failure = predecessor_artifacts.read_json(root / "failure.json")
    index = predecessor_artifacts.read_json(root / "ledger-index.json")
    if (
        not isinstance(failure, dict)
        or failure.get("status") != "execution_failed"
        or failure.get("formal_eligibility") is not False
        or not isinstance(index, dict)
        or index.get("benchmark_id") != predecessor_benchmark_id
    ):
        raise ValueError("predecessor is not a failed non-formal benchmark")
    paths = index.get("event_paths")
    hashes = index.get("event_hashes")
    if (
        not isinstance(paths, list)
        or not isinstance(hashes, list)
        or len(paths) != len(hashes)
        or any(not isinstance(item, str) for item in hashes)
    ):
        raise ValueError("predecessor ledger index is incomplete")
    consumed = len(paths)
    manifest = NonformalRunCarryover(
        predecessor_benchmark_id=predecessor_benchmark_id,
        successor_benchmark_id=successor_benchmark_id,
        predecessor_failure_hash=sha256_json(failure),
        predecessor_ledger_index_hash=sha256_json(index),
        predecessor_event_hashes=tuple(hashes),
        consumed_attempts=consumed,
        remote_attempt_limit=remote_attempt_limit,
        spend_limit_rmb=spend_limit_rmb,
        charged_upper_bound_rmb=spend_limit_rmb,
        cost_evidence="conservative_full_cap_unknown_usage",
        unknown_usage_attempts=tuple(range(1, consumed + 1)),
    )
    assess_continuation(manifest, predecessor_artifacts=predecessor_artifacts)
    return manifest


def build_successor_config(
    predecessor: BenchmarkConfig,
    *,
    successor_benchmark_id: str,
    source_identity: CodeIdentity,
) -> BenchmarkConfig:
    """Create a new identity while preserving the predecessor's frozen sample plan."""

    if predecessor.formal:
        raise ValueError("non-formal continuation cannot derive from a formal config")
    code_revision = source_identity.head_revision
    if not source_identity.worktree_clean:
        code_revision = f"{code_revision}+dirty-{source_identity.tree_hash}"
    payload = predecessor.model_dump(mode="python")
    payload.update(
        benchmark_id=successor_benchmark_id,
        generator_prompt_version=GENERATOR_PROMPT_VERSION,
        logic_review_prompt_version=LOGIC_REVIEW_PROMPT_VERSION,
        adversarial_review_prompt_version=ADVERSARIAL_REVIEW_PROMPT_VERSION,
        arbiter_prompt_version=ARBITER_PROMPT_VERSION,
        code_revision=code_revision,
    )
    return BenchmarkConfig.model_validate(payload)


def assess_continuation(
    manifest: NonformalRunCarryover,
    *,
    predecessor_artifacts: ArtifactStore,
) -> ContinuationPreflight:
    """Verify predecessor hashes and calculate remaining shared upper bounds."""

    root = Path("benchmarks") / manifest.predecessor_benchmark_id
    failure = predecessor_artifacts.read_json(root / "failure.json")
    if (
        not isinstance(failure, dict)
        or failure.get("status") != "execution_failed"
        or failure.get("formal_eligibility") is not False
        or sha256_json(failure) != manifest.predecessor_failure_hash
    ):
        raise ValueError("predecessor failure evidence does not match carryover")

    index = predecessor_artifacts.read_json(root / "ledger-index.json")
    if not isinstance(index, dict) or sha256_json(index) != manifest.predecessor_ledger_index_hash:
        raise ValueError("predecessor ledger index does not match carryover")
    event_paths = index.get("event_paths")
    event_hashes = index.get("event_hashes")
    if (
        index.get("benchmark_id") != manifest.predecessor_benchmark_id
        or not isinstance(event_paths, list)
        or not isinstance(event_hashes, list)
        or tuple(event_hashes) != manifest.predecessor_event_hashes
        or len(event_paths) != manifest.consumed_attempts
    ):
        raise ValueError("predecessor ledger index does not account for consumed attempts")

    for sequence, (event_path, expected_hash) in enumerate(
        zip(event_paths, event_hashes, strict=True),
        start=1,
    ):
        expected_path = root / "ledger" / f"{sequence:06d}.json"
        if event_path != str(expected_path):
            raise ValueError("predecessor event path does not match its sequence")
        event = predecessor_artifacts.read_json(expected_path)
        if (
            not isinstance(event, dict)
            or event.get("benchmark_id") != manifest.predecessor_benchmark_id
            or event.get("sequence") != sequence
            or sha256_json(event) != expected_hash
        ):
            raise ValueError("predecessor event hash or identity does not match carryover")

    remaining_cost = _amount(manifest.remaining_upper_bound_rmb)
    reason: (
        Literal[
            "attempt_cap_exhausted",
            "spend_cap_exhausted_by_conservative_carryover",
        ]
        | None
    )
    if manifest.remaining_attempts == 0:
        ready = False
        reason = "attempt_cap_exhausted"
    elif remaining_cost == 0:
        ready = False
        reason = "spend_cap_exhausted_by_conservative_carryover"
    else:
        ready = True
        reason = None
    return ContinuationPreflight(
        predecessor_benchmark_id=manifest.predecessor_benchmark_id,
        successor_benchmark_id=manifest.successor_benchmark_id,
        consumed_attempts=manifest.consumed_attempts,
        remaining_attempts=manifest.remaining_attempts,
        remote_attempt_limit=manifest.remote_attempt_limit,
        spend_limit_rmb=manifest.spend_limit_rmb,
        charged_upper_bound_rmb=manifest.charged_upper_bound_rmb,
        remaining_upper_bound_rmb=manifest.remaining_upper_bound_rmb,
        ready_for_remote_run=ready,
        block_reason=reason,
    )


def assess_authorized_continuation(
    manifest: NonformalRunCarryover,
    *,
    authorization: NonformalResourceAuthorization,
    predecessor_artifacts: ArtifactStore,
) -> AuthorizedContinuationPreflight:
    """Verify old evidence while keeping its cost separate from a new bounded tranche."""

    historical = assess_continuation(
        manifest,
        predecessor_artifacts=predecessor_artifacts,
    )
    if authorization.successor_benchmark_id != manifest.successor_benchmark_id:
        raise ValueError("resource authorization does not match successor identity")
    ready = historical.remaining_attempts > 0
    return AuthorizedContinuationPreflight(
        predecessor_benchmark_id=manifest.predecessor_benchmark_id,
        successor_benchmark_id=manifest.successor_benchmark_id,
        consumed_attempts=manifest.consumed_attempts,
        remaining_attempts=manifest.remaining_attempts,
        remote_attempt_limit=manifest.remote_attempt_limit,
        historical_spend_limit_rmb=manifest.spend_limit_rmb,
        historical_charged_upper_bound_rmb=manifest.charged_upper_bound_rmb,
        free_token_limit=authorization.free_token_limit,
        additional_spend_limit_rmb=authorization.additional_spend_limit_rmb,
        provider=authorization.provider,
        model=authorization.model,
        ready_for_remote_run=ready,
        block_reason=None if ready else "attempt_cap_exhausted",
    )


def write_continuation_bundle(
    artifacts: ArtifactStore,
    *,
    manifest: NonformalRunCarryover,
    predecessor_artifacts: ArtifactStore,
) -> tuple[ArtifactRef, ArtifactRef]:
    """Validate first, then create immutable carryover and preflight documents."""

    preflight = assess_continuation(manifest, predecessor_artifacts=predecessor_artifacts)
    root = Path("continuations") / manifest.successor_benchmark_id
    carryover_ref = artifacts.write_json(root / "carryover.json", manifest.model_dump(mode="json"))
    preflight_ref = artifacts.write_json(root / "preflight.json", preflight.model_dump(mode="json"))
    return carryover_ref, preflight_ref


def write_successor_package(
    artifacts: ArtifactStore,
    *,
    manifest: NonformalRunCarryover,
    predecessor_artifacts: ArtifactStore,
    successor_config: BenchmarkConfig,
    source_identity: CodeIdentity,
) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    """Create an identity-bound successor package after every offline check succeeds."""

    preflight = assess_continuation(
        manifest,
        predecessor_artifacts=predecessor_artifacts,
    )
    expected_config = build_successor_config(
        successor_config,
        successor_benchmark_id=manifest.successor_benchmark_id,
        source_identity=source_identity,
    )
    if successor_config != expected_config:
        raise ValueError("successor config does not match source identity and current prompts")
    if successor_config.remote_attempt_budget != manifest.remote_attempt_limit:
        raise ValueError("successor config does not preserve the shared attempt limit")

    source_payload = source_identity.model_dump(mode="json")
    config_payload = successor_config.model_dump(mode="json")
    preflight = preflight.model_copy(
        update={
            "successor_config_hash": sha256_json(config_payload),
            "source_identity_hash": sha256_json(source_payload),
            "source_tree_hash": source_identity.tree_hash,
        }
    )
    source_ref = artifacts.write_json("source-identity.json", source_payload)
    config_ref = artifacts.write_json("config.json", config_payload)
    carryover_ref = artifacts.write_json("carryover.json", manifest.model_dump(mode="json"))
    preflight_ref = artifacts.write_json("preflight.json", preflight.model_dump(mode="json"))
    return source_ref, config_ref, carryover_ref, preflight_ref


def write_authorized_successor_package(
    artifacts: ArtifactStore,
    *,
    manifest: NonformalRunCarryover,
    authorization: NonformalResourceAuthorization,
    predecessor_artifacts: ArtifactStore,
    successor_config: BenchmarkConfig,
    source_identity: CodeIdentity,
) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    """Create an immutable successor whose additive token and RMB limits are explicit."""

    preflight = assess_authorized_continuation(
        manifest,
        authorization=authorization,
        predecessor_artifacts=predecessor_artifacts,
    )
    expected_config = build_successor_config(
        successor_config,
        successor_benchmark_id=manifest.successor_benchmark_id,
        source_identity=source_identity,
    )
    if successor_config != expected_config:
        raise ValueError("successor config does not match source identity and current prompts")
    if successor_config.remote_attempt_budget != manifest.remote_attempt_limit:
        raise ValueError("successor config does not preserve the shared attempt limit")
    if successor_config.model != authorization.model:
        raise ValueError("successor config does not match authorized model")

    source_payload = source_identity.model_dump(mode="json")
    config_payload = successor_config.model_dump(mode="json")
    carryover_payload = manifest.model_dump(mode="json")
    authorization_payload = authorization.model_dump(mode="json")
    preflight = preflight.model_copy(
        update={
            "successor_config_hash": sha256_json(config_payload),
            "source_identity_hash": sha256_json(source_payload),
            "source_tree_hash": source_identity.tree_hash,
            "carryover_hash": sha256_json(carryover_payload),
            "authorization_hash": sha256_json(authorization_payload),
        }
    )
    source_ref = artifacts.write_json("source-identity.json", source_payload)
    config_ref = artifacts.write_json("config.json", config_payload)
    carryover_ref = artifacts.write_json("carryover.json", carryover_payload)
    authorization_ref = artifacts.write_json("authorization.json", authorization_payload)
    preflight_ref = artifacts.write_json("preflight.json", preflight.model_dump(mode="json"))
    return source_ref, config_ref, carryover_ref, authorization_ref, preflight_ref


def verify_authorized_successor_package(
    *,
    package_root: Path,
    predecessor_artifacts: ArtifactStore,
    successor_config: BenchmarkConfig,
    current_source_identity: CodeIdentity,
) -> AuthorizedContinuationPreflight:
    """Recompute every package binding immediately before a live successor run."""

    package = ArtifactStore(package_root)
    source_payload = package.read_json("source-identity.json")
    config_payload = package.read_json("config.json")
    carryover_payload = package.read_json("carryover.json")
    authorization_payload = package.read_json("authorization.json")
    preflight_payload = package.read_json("preflight.json")
    try:
        frozen_source = CodeIdentity.model_validate(source_payload)
        frozen_config = BenchmarkConfig.model_validate(config_payload)
        manifest = NonformalRunCarryover.model_validate(carryover_payload)
        authorization = NonformalResourceAuthorization.model_validate(authorization_payload)
        frozen_preflight = AuthorizedContinuationPreflight.model_validate(preflight_payload)
    except ValueError:
        raise ValueError("authorized successor package schema is invalid") from None
    if frozen_config != successor_config:
        raise ValueError("runtime config does not match authorized successor package")
    if frozen_source != current_source_identity:
        raise ValueError("runtime source does not match authorized successor package")
    expected = assess_authorized_continuation(
        manifest,
        authorization=authorization,
        predecessor_artifacts=predecessor_artifacts,
    ).model_copy(
        update={
            "successor_config_hash": sha256_json(config_payload),
            "source_identity_hash": sha256_json(source_payload),
            "source_tree_hash": frozen_source.tree_hash,
            "carryover_hash": sha256_json(carryover_payload),
            "authorization_hash": sha256_json(authorization_payload),
        }
    )
    if frozen_preflight != expected:
        raise ValueError("authorized successor preflight does not match recomputed evidence")
    if not frozen_preflight.ready_for_remote_run:
        raise ValueError("authorized successor preflight is not ready for remote run")
    return frozen_preflight


_SETTLEMENT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "formal_eligibility",
        "sample_id",
        "attempt_sequence",
        "category",
        "http_status",
        "finish_reason",
        "usage_status",
        "usage",
        "charged_attempt_upper_bound_rmb",
        "charged_upper_bound_rmb",
        "remaining_upper_bound_rmb",
        "charged_attempt_upper_bound_tokens",
        "charged_upper_bound_tokens",
        "remaining_upper_bound_tokens",
        "validation_issues",
    }
)
_USAGE_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})


def _load_verified_parent_package(
    *,
    parent_package_root: Path,
    ancestor_artifacts: ArtifactStore,
) -> tuple[
    NonformalRunCarryover,
    NonformalResourceAuthorization,
    AuthorizedPackageHashes,
]:
    package = ArtifactStore(parent_package_root)
    source_payload = package.read_json("source-identity.json")
    config_payload = package.read_json("config.json")
    carryover_payload = package.read_json("carryover.json")
    authorization_payload = package.read_json("authorization.json")
    preflight_payload = package.read_json("preflight.json")
    try:
        source = CodeIdentity.model_validate(source_payload)
        config = BenchmarkConfig.model_validate(config_payload)
        manifest = NonformalRunCarryover.model_validate(carryover_payload)
        authorization = NonformalResourceAuthorization.model_validate(authorization_payload)
    except ValueError:
        raise ValueError("parent authorized package schema is invalid") from None
    verify_authorized_successor_package(
        package_root=parent_package_root,
        predecessor_artifacts=ancestor_artifacts,
        successor_config=config,
        current_source_identity=source,
    )
    hashes = AuthorizedPackageHashes(
        source_identity_hash=sha256_json(source_payload),
        config_hash=sha256_json(config_payload),
        carryover_hash=sha256_json(carryover_payload),
        authorization_hash=sha256_json(authorization_payload),
        preflight_hash=sha256_json(preflight_payload),
    )
    return manifest, authorization, hashes


def _validate_latest_failure_and_index(
    *,
    latest_artifacts: ArtifactStore,
    benchmark_id: str,
    first_sequence: int,
) -> tuple[dict[str, object], dict[str, object], tuple[str, ...], tuple[str, ...]]:
    root = Path("benchmarks") / benchmark_id
    failure = latest_artifacts.read_json(root / "failure.json")
    index = latest_artifacts.read_json(root / "ledger-index.json")
    if (
        not isinstance(failure, dict)
        or failure.get("status") != "execution_failed"
        or failure.get("formal_eligibility") is not False
        or not isinstance(index, dict)
        or index.get("benchmark_id") != benchmark_id
    ):
        raise ValueError("latest predecessor is not a failed non-formal benchmark")
    event_paths = index.get("event_paths")
    event_hashes = index.get("event_hashes")
    if (
        not isinstance(event_paths, list)
        or not isinstance(event_hashes, list)
        or len(event_paths) == 0
        or len(event_paths) != len(event_hashes)
        or any(not isinstance(item, str) for item in (*event_paths, *event_hashes))
    ):
        raise ValueError("latest predecessor ledger index is incomplete")
    for sequence, (event_path, expected_hash) in enumerate(
        zip(event_paths, event_hashes, strict=True),
        start=first_sequence,
    ):
        expected_path = root / "ledger" / f"{sequence:06d}.json"
        if event_path != str(expected_path):
            raise ValueError("latest predecessor event path does not match its sequence")
        event = latest_artifacts.read_json(expected_path)
        if (
            not isinstance(event, dict)
            or event.get("benchmark_id") != benchmark_id
            or event.get("sequence") != sequence
            or sha256_json(event) != expected_hash
        ):
            raise ValueError("latest predecessor event hash or identity does not match")
    return failure, index, tuple(event_paths), tuple(event_hashes)


def _settlement_evidence(
    *,
    latest_artifacts: ArtifactStore,
    benchmark_id: str,
    sequences: tuple[int, ...],
    token_limit: int,
    spend_limit_rmb: str,
    expected: tuple[AttemptSettlementEvidence, ...] | None = None,
) -> tuple[tuple[AttemptSettlementEvidence, ...], int, str]:
    root = Path("benchmarks") / benchmark_id
    discovered: dict[int, tuple[str, dict[str, object]]] = {}
    search_root = latest_artifacts.root / root / "live-evidence"
    for absolute_path in sorted(search_root.glob("*/attempts/*/settlement.json")):
        relative_path = absolute_path.relative_to(latest_artifacts.root).as_posix()
        payload = latest_artifacts.read_json(relative_path)
        if not isinstance(payload, dict):
            raise ValueError("latest settlement is not a JSON object")
        sequence = payload.get("attempt_sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise ValueError("latest settlement sequence is invalid")
        if sequence in discovered:
            raise ValueError("latest settlement sequence is duplicated")
        discovered[sequence] = (relative_path, payload)
    if tuple(sorted(discovered)) != sequences:
        raise ValueError("latest settlements do not cover every added attempt")

    expected_by_sequence = {item.sequence: item for item in expected or ()}
    if expected is not None and tuple(sorted(expected_by_sequence)) != sequences:
        raise ValueError("frozen settlement evidence does not cover the latest run")
    evidence: list[AttemptSettlementEvidence] = []
    cumulative_tokens = 0
    cumulative_rmb = Decimal(0)
    spend_limit = _amount(spend_limit_rmb)
    for sequence in sequences:
        path, payload = discovered[sequence]
        expected_parts = (
            "benchmarks",
            benchmark_id,
            "live-evidence",
            str(payload.get("sample_id")),
            "attempts",
            f"{sequence:06d}",
            "settlement.json",
        )
        if Path(path).parts != expected_parts or set(payload) != _SETTLEMENT_KEYS:
            raise ValueError("latest settlement path or allowlist is invalid")
        if (
            payload.get("kind") != "nonformal_hy3_attempt_settlement"
            or payload.get("formal_eligibility") is not False
            or payload.get("attempt_sequence") != sequence
            or payload.get("usage_status") != "reported"
        ):
            raise ValueError("latest settlement metadata is invalid")
        usage = payload.get("usage")
        if not isinstance(usage, dict) or set(usage) != _USAGE_KEYS:
            raise ValueError("latest settlement usage is incomplete")
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        token_values = (prompt_tokens, completion_tokens, total_tokens)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in token_values
        ):
            raise ValueError("latest settlement usage values are invalid")
        assert isinstance(prompt_tokens, int)
        assert isinstance(completion_tokens, int)
        assert isinstance(total_tokens, int)
        attempt_tokens = max(total_tokens, prompt_tokens + completion_tokens)
        attempt_rmb = (Decimal(prompt_tokens) + Decimal(4) * Decimal(completion_tokens)) / Decimal(
            1_000_000
        )
        cumulative_tokens += attempt_tokens
        cumulative_rmb += attempt_rmb
        if (
            payload.get("charged_attempt_upper_bound_tokens") != attempt_tokens
            or payload.get("charged_upper_bound_tokens") != cumulative_tokens
            or payload.get("remaining_upper_bound_tokens") != token_limit - cumulative_tokens
            or _amount(str(payload.get("charged_attempt_upper_bound_rmb"))) != attempt_rmb
            or _amount(str(payload.get("charged_upper_bound_rmb"))) != cumulative_rmb
            or _amount(str(payload.get("remaining_upper_bound_rmb")))
            != spend_limit - cumulative_rmb
        ):
            raise ValueError("latest settlement resource accounting is invalid")
        current = AttemptSettlementEvidence(
            sequence=sequence,
            path=path,
            content_hash=sha256_json(payload),
        )
        if expected is not None and expected_by_sequence[sequence] != current:
            raise ValueError("latest settlement hash does not match carryover")
        evidence.append(current)
    return tuple(evidence), cumulative_tokens, _cost_text(cumulative_rmb)


def derive_chained_carryover(
    *,
    parent_package_root: Path,
    ancestor_artifacts: ArtifactStore,
    latest_artifacts: ArtifactStore,
    latest_benchmark_id: str,
    successor_benchmark_id: str,
) -> NonformalRunChainCarryover:
    """Derive a no-reset chain from the original failure and its failed successor."""

    parent, authorization, parent_hashes = _load_verified_parent_package(
        parent_package_root=parent_package_root,
        ancestor_artifacts=ancestor_artifacts,
    )
    if parent.successor_benchmark_id != latest_benchmark_id:
        raise ValueError("latest benchmark is not the authorized parent successor")
    first_sequence = parent.consumed_attempts + 1
    failure, index, event_paths, event_hashes = _validate_latest_failure_and_index(
        latest_artifacts=latest_artifacts,
        benchmark_id=latest_benchmark_id,
        first_sequence=first_sequence,
    )
    del event_paths
    sequences = tuple(range(first_sequence, first_sequence + len(event_hashes)))
    settlements, charged_tokens, charged_rmb = _settlement_evidence(
        latest_artifacts=latest_artifacts,
        benchmark_id=latest_benchmark_id,
        sequences=sequences,
        token_limit=authorization.free_token_limit,
        spend_limit_rmb=authorization.additional_spend_limit_rmb,
    )
    manifest = NonformalRunChainCarryover(
        ancestor_benchmark_id=parent.predecessor_benchmark_id,
        predecessor_benchmark_id=latest_benchmark_id,
        successor_benchmark_id=successor_benchmark_id,
        parent_package_hashes=parent_hashes,
        parent_consumed_attempts=parent.consumed_attempts,
        predecessor_failure_hash=sha256_json(failure),
        predecessor_ledger_index_hash=sha256_json(index),
        predecessor_event_hashes=event_hashes,
        settlements=settlements,
        consumed_attempts=sequences[-1],
        remote_attempt_limit=parent.remote_attempt_limit,
        historical_spend_limit_rmb=parent.spend_limit_rmb,
        historical_charged_upper_bound_rmb=parent.charged_upper_bound_rmb,
        historical_unknown_usage_attempts=parent.unknown_usage_attempts,
        resource_token_limit=authorization.free_token_limit,
        resource_charged_upper_bound_tokens=charged_tokens,
        resource_spend_limit_rmb=authorization.additional_spend_limit_rmb,
        resource_charged_upper_bound_rmb=charged_rmb,
    )
    assess_chained_continuation(
        manifest,
        parent_package_root=parent_package_root,
        ancestor_artifacts=ancestor_artifacts,
        latest_artifacts=latest_artifacts,
    )
    return manifest


def assess_chained_continuation(
    manifest: NonformalRunChainCarryover,
    *,
    parent_package_root: Path,
    ancestor_artifacts: ArtifactStore,
    latest_artifacts: ArtifactStore,
) -> ChainedContinuationPreflight:
    """Recompute both generations of immutable evidence and all resource charges."""

    parent, authorization, parent_hashes = _load_verified_parent_package(
        parent_package_root=parent_package_root,
        ancestor_artifacts=ancestor_artifacts,
    )
    if (
        parent_hashes != manifest.parent_package_hashes
        or parent.predecessor_benchmark_id != manifest.ancestor_benchmark_id
        or parent.successor_benchmark_id != manifest.predecessor_benchmark_id
        or parent.consumed_attempts != manifest.parent_consumed_attempts
        or parent.remote_attempt_limit != manifest.remote_attempt_limit
        or parent.spend_limit_rmb != manifest.historical_spend_limit_rmb
        or parent.charged_upper_bound_rmb != manifest.historical_charged_upper_bound_rmb
        or parent.unknown_usage_attempts != manifest.historical_unknown_usage_attempts
        or authorization.free_token_limit != manifest.resource_token_limit
        or authorization.additional_spend_limit_rmb != manifest.resource_spend_limit_rmb
    ):
        raise ValueError("parent authorized package does not match chained carryover")
    failure, index, _, event_hashes = _validate_latest_failure_and_index(
        latest_artifacts=latest_artifacts,
        benchmark_id=manifest.predecessor_benchmark_id,
        first_sequence=manifest.parent_consumed_attempts + 1,
    )
    if (
        sha256_json(failure) != manifest.predecessor_failure_hash
        or sha256_json(index) != manifest.predecessor_ledger_index_hash
        or event_hashes != manifest.predecessor_event_hashes
    ):
        raise ValueError("latest predecessor hashes do not match chained carryover")
    sequences = tuple(range(manifest.parent_consumed_attempts + 1, manifest.consumed_attempts + 1))
    _, charged_tokens, charged_rmb = _settlement_evidence(
        latest_artifacts=latest_artifacts,
        benchmark_id=manifest.predecessor_benchmark_id,
        sequences=sequences,
        token_limit=manifest.resource_token_limit,
        spend_limit_rmb=manifest.resource_spend_limit_rmb,
        expected=manifest.settlements,
    )
    if (
        charged_tokens != manifest.resource_charged_upper_bound_tokens
        or charged_rmb != manifest.resource_charged_upper_bound_rmb
    ):
        raise ValueError("latest settlement totals do not match chained carryover")
    return ChainedContinuationPreflight(
        ancestor_benchmark_id=manifest.ancestor_benchmark_id,
        predecessor_benchmark_id=manifest.predecessor_benchmark_id,
        successor_benchmark_id=manifest.successor_benchmark_id,
        consumed_attempts=manifest.consumed_attempts,
        remaining_attempts=manifest.remaining_attempts,
        remote_attempt_limit=manifest.remote_attempt_limit,
        historical_spend_limit_rmb=manifest.historical_spend_limit_rmb,
        historical_charged_upper_bound_rmb=manifest.historical_charged_upper_bound_rmb,
        resource_token_limit=manifest.resource_token_limit,
        resource_charged_upper_bound_tokens=manifest.resource_charged_upper_bound_tokens,
        remaining_upper_bound_tokens=manifest.remaining_upper_bound_tokens,
        resource_spend_limit_rmb=manifest.resource_spend_limit_rmb,
        resource_charged_upper_bound_rmb=manifest.resource_charged_upper_bound_rmb,
        remaining_upper_bound_rmb=manifest.remaining_upper_bound_rmb,
    )


def _pending_chained_authorization(
    manifest: NonformalRunChainCarryover,
) -> PendingChainedAuthorization:
    return PendingChainedAuthorization(
        successor_benchmark_id=manifest.successor_benchmark_id,
        resource_token_limit=manifest.resource_token_limit,
        resource_charged_upper_bound_tokens=manifest.resource_charged_upper_bound_tokens,
        resource_spend_limit_rmb=manifest.resource_spend_limit_rmb,
        resource_charged_upper_bound_rmb=manifest.resource_charged_upper_bound_rmb,
    )


def write_chained_successor_package(
    artifacts: ArtifactStore,
    *,
    manifest: NonformalRunChainCarryover,
    parent_package_root: Path,
    ancestor_artifacts: ArtifactStore,
    latest_artifacts: ArtifactStore,
    successor_config: BenchmarkConfig,
    source_identity: CodeIdentity,
) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef, ArtifactRef]:
    """Create a chain-bound package that remains blocked pending a new approval."""

    preflight = assess_chained_continuation(
        manifest,
        parent_package_root=parent_package_root,
        ancestor_artifacts=ancestor_artifacts,
        latest_artifacts=latest_artifacts,
    )
    expected_config = build_successor_config(
        successor_config,
        successor_benchmark_id=manifest.successor_benchmark_id,
        source_identity=source_identity,
    )
    if successor_config != expected_config:
        raise ValueError("chained successor config does not match current source and prompts")
    if successor_config.remote_attempt_budget != manifest.remote_attempt_limit:
        raise ValueError("chained successor config resets the shared attempt limit")
    source_payload = source_identity.model_dump(mode="json")
    config_payload = successor_config.model_dump(mode="json")
    carryover_payload = manifest.model_dump(mode="json")
    authorization_payload = _pending_chained_authorization(manifest).model_dump(mode="json")
    preflight = preflight.model_copy(
        update={
            "successor_config_hash": sha256_json(config_payload),
            "source_identity_hash": sha256_json(source_payload),
            "source_tree_hash": source_identity.tree_hash,
            "carryover_hash": sha256_json(carryover_payload),
            "authorization_hash": sha256_json(authorization_payload),
        }
    )
    source_ref = artifacts.write_json("source-identity.json", source_payload)
    config_ref = artifacts.write_json("config.json", config_payload)
    carryover_ref = artifacts.write_json("carryover.json", carryover_payload)
    authorization_ref = artifacts.write_json("authorization.json", authorization_payload)
    preflight_ref = artifacts.write_json("preflight.json", preflight.model_dump(mode="json"))
    return source_ref, config_ref, carryover_ref, authorization_ref, preflight_ref


def verify_chained_successor_package(
    *,
    package_root: Path,
    parent_package_root: Path,
    ancestor_artifacts: ArtifactStore,
    latest_artifacts: ArtifactStore,
    successor_config: BenchmarkConfig,
    current_source_identity: CodeIdentity,
) -> ChainedContinuationPreflight:
    """Verify an offline chained package without treating it as remote authorization."""

    package = ArtifactStore(package_root)
    source_payload = package.read_json("source-identity.json")
    config_payload = package.read_json("config.json")
    carryover_payload = package.read_json("carryover.json")
    authorization_payload = package.read_json("authorization.json")
    preflight_payload = package.read_json("preflight.json")
    try:
        frozen_source = CodeIdentity.model_validate(source_payload)
        frozen_config = BenchmarkConfig.model_validate(config_payload)
        manifest = NonformalRunChainCarryover.model_validate(carryover_payload)
        frozen_authorization = PendingChainedAuthorization.model_validate(authorization_payload)
        frozen_preflight = ChainedContinuationPreflight.model_validate(preflight_payload)
    except ValueError:
        raise ValueError("chained successor package schema is invalid") from None
    if frozen_config != successor_config or frozen_source != current_source_identity:
        raise ValueError("runtime source or config does not match chained successor package")
    expected_authorization = _pending_chained_authorization(manifest)
    if frozen_authorization != expected_authorization:
        raise ValueError("pending chained authorization does not match carryover")
    expected = assess_chained_continuation(
        manifest,
        parent_package_root=parent_package_root,
        ancestor_artifacts=ancestor_artifacts,
        latest_artifacts=latest_artifacts,
    ).model_copy(
        update={
            "successor_config_hash": sha256_json(config_payload),
            "source_identity_hash": sha256_json(source_payload),
            "source_tree_hash": frozen_source.tree_hash,
            "carryover_hash": sha256_json(carryover_payload),
            "authorization_hash": sha256_json(authorization_payload),
        }
    )
    if frozen_preflight != expected:
        raise ValueError("chained successor preflight does not match recomputed evidence")
    return frozen_preflight
