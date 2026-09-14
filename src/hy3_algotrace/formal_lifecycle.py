"""Internal two-stage formal freeze; persisted JSON never conveys execution capability.

Stage A names the 105 existing samples and reserves 60 natural identities. Stage B
can exist only after those natural outputs and their same-run requests exist.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self, SupportsIndex

from pydantic import Field, model_validator

from . import prompts
from .artifacts import sha256_bytes, sha256_json
from .benchmark_models import (
    BenchmarkConfig,
    BenchmarkModel,
    BenchmarkParameter,
    BenchmarkSampleSpec,
    LedgerEvent,
    LedgerIndex,
    SampleKind,
)
from .contracts import ProblemRecord
from .corpus import (
    CorpusManifest,
    CorpusSampleKind,
    CorpusStatus,
    ProjectBundleManifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from .dataset_models import FrozenSelectionManifest, read_trusted_file

if TYPE_CHECKING:
    from .formal_qualification import NaturalMaterializationManifest

FORMAL_ENDPOINT = "https://tokenhub.tencentmaas.com/v1"
_HASH = r"^[0-9a-f]{64}$"
_SOURCE_DIRS = ("src", "scripts", "tests", "docker")
_SOURCE_FILES = ("pyproject.toml", "uv.lock", "Dockerfile", "compose.yaml", "docker-compose.yml")


class LifecycleError(ValueError):
    """A frozen stage or its runtime source bytes do not match."""


class SourceFileIdentity(BenchmarkModel):
    path: str
    byte_length: int = Field(ge=0)
    sha256: str = Field(pattern=_HASH)


def source_tree_inventory(repo_root: Path) -> tuple[SourceFileIdentity, ...]:
    """Hash executable inputs, including untracked/ignored source, without secrets.

    Only explicit code roots and build inputs are traversed. Venvs, caches, git
    metadata, data artifacts and all dotenv/key files are outside the inventory.
    Symlinks are rejected instead of following code out of the frozen tree.
    """
    paths: list[Path] = []
    for name in _SOURCE_DIRS:
        directory = repo_root / name
        if directory.is_symlink():
            raise LifecycleError("source roots must not be symlinks")
        if directory.exists():
            for path in directory.rglob("*"):
                relative = path.relative_to(repo_root)
                if any(
                    part in {"__pycache__", ".venv", ".git", ".pytest_cache", ".mypy_cache"}
                    for part in relative.parts
                ):
                    continue
                if path.name.startswith(".env") or path.suffix in {".pyc", ".pem", ".key"}:
                    continue
                if path.is_symlink():
                    raise LifecycleError("source identity refuses symlinked code")
                if path.is_file():
                    paths.append(path)
    paths.extend(repo_root / name for name in _SOURCE_FILES if (repo_root / name).exists())
    if not paths:
        raise LifecycleError("source identity has no executable inputs")
    result = []
    for path in sorted(paths):
        if path.is_symlink():
            raise LifecycleError("source identity refuses symlinked build inputs")
        snapshot = read_trusted_file(path, logical_id="code-identity", max_bytes=64 * 1024 * 1024)
        result.append(
            SourceFileIdentity(
                path=path.relative_to(repo_root).as_posix(),
                byte_length=snapshot.byte_length,
                sha256=snapshot.sha256,
            )
        )
    return tuple(result)


class CodeIdentity(BenchmarkModel):
    kind: Literal["source-tree-sha256-and-head-v1"] = "source-tree-sha256-and-head-v1"
    head_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    worktree_clean: bool = Field(strict=True)
    files: tuple[SourceFileIdentity, ...] = Field(min_length=1)
    tree_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def valid_inventory(self) -> Self:
        paths = tuple(item.path for item in self.files)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("source inventory must be ordered and unique")
        if self.tree_hash != sha256_json([item.model_dump(mode="json") for item in self.files]):
            raise ValueError("source tree content hash mismatch")
        return self


def current_code_identity(repo_root: Path) -> CodeIdentity:
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")

    def git(*args: str) -> str:
        try:
            return subprocess.run(
                ["git", *args], cwd=repo_root, env=env, check=True, capture_output=True, text=True
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise LifecycleError("cannot verify Git source identity") from error

    files = source_tree_inventory(repo_root)
    return CodeIdentity(
        head_revision=git("rev-parse", "HEAD"),
        worktree_clean=not git("status", "--porcelain"),
        files=files,
        tree_hash=sha256_json([item.model_dump(mode="json") for item in files]),
    )


def prompt_identity() -> dict[str, dict[str, str]]:
    return {
        role: {"version": version, "sha256": sha256_bytes(prompt.encode())}
        for role, version, prompt in (
            ("generator", prompts.GENERATOR_PROMPT_VERSION, prompts.GENERATOR_SYSTEM_PROMPT),
            (
                "logic_review",
                prompts.LOGIC_REVIEW_PROMPT_VERSION,
                prompts.LOGIC_REVIEW_SYSTEM_PROMPT,
            ),
            (
                "adversarial_review",
                prompts.ADVERSARIAL_REVIEW_PROMPT_VERSION,
                prompts.ADVERSARIAL_REVIEW_SYSTEM_PROMPT,
            ),
            ("arbiter", prompts.ARBITER_PROMPT_VERSION, prompts.ARBITER_SYSTEM_PROMPT),
            ("schema_repair", "schema-repair-in-source-v1", prompts.SCHEMA_REPAIR_PROMPT),
        )
    }


class PreRunIntent(BenchmarkModel):
    schema_version: Literal["formal-lifecycle-v1"] = "formal-lifecycle-v1"
    kind: Literal["formal_pre_run_intent"] = "formal_pre_run_intent"
    recorded_at: datetime
    formal: Literal[True] = True
    benchmark_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    selection_manifest_hash: str = Field(pattern=_HASH)
    bundle_manifest_hash: str = Field(pattern=_HASH)
    pending_corpus_hash: str = Field(pattern=_HASH)
    controlled_samples_hash: str = Field(pattern=_HASH)
    planned_samples: tuple[BenchmarkSampleSpec, ...] = Field(min_length=165, max_length=165)
    natural_sample_ids: tuple[str, ...] = Field(min_length=60, max_length=60)
    model: Literal["hy3"] = "hy3"
    endpoint_identity: Literal["https://tokenhub.tencentmaas.com/v1"] = (
        "https://tokenhub.tencentmaas.com/v1"
    )
    timeout_seconds: float = Field(default=600.0, ge=600.0, le=600.0, strict=True)
    remote_attempt_budget: Literal[500] = 500
    prompt_identity: dict[str, dict[str, str]]
    model_parameters: tuple[BenchmarkParameter, ...]
    code_identity: CodeIdentity
    judge_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    metric_version: Literal["task6-metrics-v1"] = "task6-metrics-v1"
    chart_version: Literal["task6-chart-v1"] = "task6-chart-v1"
    seed: int = Field(default=20260911, strict=True)
    bootstrap_replicates: int = Field(default=10000, gt=0, strict=True)
    intent_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.recorded_at.tzinfo is None:
            raise ValueError("pre-run recorded_at must be timezone-aware")
        payload = self.model_dump(mode="json")
        digest = payload.pop("intent_hash")
        if digest != sha256_json(payload):
            raise ValueError("pre-run intent hash mismatch")
        payload.pop("benchmark_id")
        if not self.benchmark_id.endswith("-" + sha256_json(payload)[:12]):
            raise ValueError("pre-run benchmark ID does not derive from intent")
        ids = tuple(spec.sample_id for spec in self.planned_samples)
        if len(set(ids)) != 165 or self.natural_sample_ids != tuple(
            spec.sample_id
            for spec in self.planned_samples
            if spec.sample_kind is SampleKind.NATURAL
        ):
            raise ValueError("pre-run planned sample identities are inconsistent")
        expected = {
            SampleKind.GOLD: 30,
            SampleKind.CONTROLLED_WRONG: 60,
            SampleKind.PARADOX: 15,
            SampleKind.NATURAL: 60,
        }
        if any(
            sum(spec.sample_kind is kind for spec in self.planned_samples) != count
            for kind, count in expected.items()
        ):
            raise ValueError("pre-run planned sample counts are incomplete")
        if len({parameter.name for parameter in self.model_parameters}) != len(
            self.model_parameters
        ):
            raise ValueError("pre-run parameters must be unique")
        return self


def _controlled_hash(corpus: CorpusManifest) -> str:
    return sha256_json(
        [
            sample.model_dump(mode="json")
            for sample in corpus.samples
            if sample.kind is not CorpusSampleKind.NATURAL
        ]
    )


def freeze_pre_run_intent(
    *,
    selection: FrozenSelectionManifest,
    pending_corpus: CorpusManifest,
    bundle_manifest: ProjectBundleManifest,
    data_root: Path,
    repo_root: Path,
    recorded_at: datetime,
    slug: str,
    judge_image_digest: str,
    timeout_seconds: float = 600,
    remote_attempt_budget: int = 500,
    seed: int = 20260911,
    bootstrap_replicates: int = 10000,
    natural_sample_ids: tuple[str, ...] | None = None,
) -> PreRunIntent:
    """Lint real pending bytes, then freeze A without creating natural artifacts."""
    try:
        lint_project_bundles(
            bundle_manifest.model_dump(mode="json"), root=data_root, selection=selection
        )
        lint_corpus_manifest(
            pending_corpus.model_dump(mode="json"),
            root=data_root,
            selection=selection,
            bundle_manifest=bundle_manifest,
        )
    except (RuntimeError, ValueError) as error:
        raise LifecycleError("pre-run input bytes or manifests are invalid") from error
    if pending_corpus.status is not CorpusStatus.PENDING_CREDENTIALS:
        raise LifecycleError("pre-run A requires the pending 105-sample corpus")
    natural = pending_corpus.natural_run_config
    if (natural.model_name, natural.endpoint_url, natural.prompt_version, natural.prompt_hash) != (
        "hy3",
        FORMAL_ENDPOINT,
        prompts.GENERATOR_PROMPT_VERSION,
        sha256_bytes(prompts.GENERATOR_SYSTEM_PROMPT.encode()),
    ):
        raise LifecycleError("pre-run natural runtime identity is not the approved GA profile")
    by_id = {entry.problem_id: entry for entry in selection.entries}
    specs = [
        BenchmarkSampleSpec(
            sample_id=sample.sample_id,
            problem_id=sample.problem_id,
            sample_kind=SampleKind(sample.kind.value),
            topic=by_id[sample.problem_id].topic,
            rating_band=by_id[sample.problem_id].rating_band,
        )
        for sample in pending_corpus.samples
    ]
    reservations = natural_sample_ids or tuple(
        f"{entry.problem_id}-natural-{index}" for entry in selection.entries for index in (1, 2)
    )
    if len(reservations) != 60:
        raise LifecycleError("pre-run requires exactly 60 natural reservations")
    for index, sample_id in enumerate(reservations):
        entry = selection.entries[index // 2]
        specs.append(
            BenchmarkSampleSpec(
                sample_id=sample_id,
                problem_id=entry.problem_id,
                sample_kind=SampleKind.NATURAL,
                topic=entry.topic,
                rating_band=entry.rating_band,
            )
        )
    # Match CorpusManifest canonical order; controlled and natural IDs never alias.
    specs.sort(
        key=lambda spec: (
            list(CorpusSampleKind).index(CorpusSampleKind(spec.sample_kind.value)),
            spec.problem_id,
            spec.sample_id,
        )
    )
    payload: dict[str, Any] = dict(
        schema_version="formal-lifecycle-v1",
        kind="formal_pre_run_intent",
        recorded_at=recorded_at.isoformat(),
        formal=True,
        selection_manifest_hash=selection.content_hash,
        bundle_manifest_hash=bundle_manifest.content_hash,
        pending_corpus_hash=pending_corpus.content_hash,
        controlled_samples_hash=_controlled_hash(pending_corpus),
        planned_samples=[spec.model_dump(mode="json") for spec in specs],
        natural_sample_ids=[
            spec.sample_id for spec in specs if spec.sample_kind is SampleKind.NATURAL
        ],
        model="hy3",
        endpoint_identity=FORMAL_ENDPOINT,
        timeout_seconds=float(timeout_seconds),
        remote_attempt_budget=remote_attempt_budget,
        prompt_identity=prompt_identity(),
        model_parameters=[
            BenchmarkParameter(name=p.name, value=p.value).model_dump(mode="json")
            for p in natural.model_parameters
        ],
        code_identity=current_code_identity(repo_root).model_dump(mode="json"),
        judge_image_digest=judge_image_digest,
        metric_version="task6-metrics-v1",
        chart_version="task6-chart-v1",
        seed=seed,
        bootstrap_replicates=bootstrap_replicates,
    )
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", slug):
        raise LifecycleError("pre-run slug must be a safe identifier")
    # Normalize datetimes through JSON convention before deriving identity.
    payload["recorded_at"] = recorded_at.isoformat().replace("+00:00", "Z")
    payload["benchmark_id"] = f"{slug}-{sha256_json(payload)[:12]}"
    return PreRunIntent.model_validate(payload | {"intent_hash": sha256_json(payload)})


_CAPABILITY_SEAL = object()


class VerifiedPreRunIntent:
    """Ephemeral local verification result, deliberately noncopyable/nonserializable."""

    __slots__ = ("intent", "repo_root", "_seal")

    def __init__(self, intent: PreRunIntent, repo_root: Path, *, _seal: object) -> None:
        if _seal is not _CAPABILITY_SEAL:
            raise TypeError("pre-run capability must be minted by verification")
        self.intent, self.repo_root, self._seal = intent, repo_root, _seal

    def __reduce_ex__(self, protocol: SupportsIndex) -> Any:
        raise TypeError("pre-run verification capability cannot be serialized or copied")


def verify_pre_run_intent(intent: PreRunIntent | None, *, repo_root: Path) -> VerifiedPreRunIntent:
    if not isinstance(intent, PreRunIntent):
        raise LifecycleError("verified pre-run A is required")
    intent = PreRunIntent.model_validate_json(intent.model_dump_json())
    current = current_code_identity(repo_root)
    if (intent.code_identity.head_revision, intent.code_identity.tree_hash) != (
        current.head_revision,
        current.tree_hash,
    ):
        raise LifecycleError("pre-run source code identity changed")
    if intent.prompt_identity != prompt_identity():
        raise LifecycleError("pre-run prompt identity changed")
    return VerifiedPreRunIntent(intent, repo_root, _seal=_CAPABILITY_SEAL)


def assert_formal_runtime(
    capability: VerifiedPreRunIntent,
    *,
    model: str,
    endpoint_identity: str,
    timeout_seconds: float,
    judge_image_digest: str,
) -> None:
    if not isinstance(capability, VerifiedPreRunIntent) or capability._seal is not _CAPABILITY_SEAL:
        raise LifecycleError("verified pre-run capability is required; receipts cannot restore it")
    intent = verify_pre_run_intent(capability.intent, repo_root=capability.repo_root).intent
    for name, value in dict(
        model=model,
        endpoint_identity=endpoint_identity,
        timeout_seconds=timeout_seconds,
        judge_image_digest=judge_image_digest,
    ).items():
        if getattr(intent, name) != value:
            raise LifecycleError(f"formal runtime {name} disagrees with pre-run A")


def assert_config_matches_pre_run(config: BenchmarkConfig, intent: PreRunIntent) -> None:
    pairs = dict(
        benchmark_id=intent.benchmark_id,
        selection_hash=intent.selection_manifest_hash,
        ordered_sample_ids=tuple(spec.sample_id for spec in intent.planned_samples),
        sample_specs=intent.planned_samples,
        generation_sample_ids=intent.natural_sample_ids,
        audit_sample_ids=tuple(spec.sample_id for spec in intent.planned_samples),
        model=intent.model,
        endpoint_identity=intent.endpoint_identity,
        timeout_seconds=intent.timeout_seconds,
        remote_attempt_budget=intent.remote_attempt_budget,
        model_parameters=intent.model_parameters,
        code_revision=intent.code_identity.head_revision,
        judge_image_digest=intent.judge_image_digest,
        seed=intent.seed,
        bootstrap_replicates=intent.bootstrap_replicates,
        metric_version=intent.metric_version,
        chart_version=intent.chart_version,
    )
    pairs.update(
        {
            f"{role}_prompt_version": detail["version"]
            for role, detail in intent.prompt_identity.items()
            if role != "schema_repair"
        }
    )
    if not config.formal or any(getattr(config, name) != value for name, value in pairs.items()):
        raise LifecycleError("formal config disagrees with pre-run A")


class MaterializedCorpusFreeze(BenchmarkModel):
    schema_version: Literal["formal-lifecycle-v1"] = "formal-lifecycle-v1"
    kind: Literal["formal_materialized_corpus_freeze"] = "formal_materialized_corpus_freeze"
    benchmark_id: str
    intent_hash: str = Field(pattern=_HASH)
    corpus_hash: str = Field(pattern=_HASH)
    natural_materialization_hash: str = Field(pattern=_HASH)
    generation_ledger_hash: str = Field(pattern=_HASH)
    config_hash: str = Field(pattern=_HASH)
    content_hash: str = Field(pattern=_HASH)

    @model_validator(mode="after")
    def valid_hash(self) -> Self:
        payload = self.model_dump(mode="json")
        digest = payload.pop("content_hash")
        if digest != sha256_json(payload):
            raise ValueError("materialized B content hash mismatch")
        return self


def freeze_materialized_corpus(
    *,
    intent: PreRunIntent,
    corpus: CorpusManifest,
    materialization: NaturalMaterializationManifest,
    config: BenchmarkConfig,
    events: tuple[LedgerEvent, ...],
    ledger: LedgerIndex,
    selected_records: Mapping[str, ProblemRecord],
    data_root: Path,
) -> MaterializedCorpusFreeze:
    """Bind actual 60 outputs and complete manifest to A; never accepts cache-only output."""
    from .formal_qualification import _validate_natural_materialization

    intent = PreRunIntent.model_validate_json(intent.model_dump_json())
    assert_config_matches_pre_run(config, intent)
    if (
        materialization.intent_hash != intent.intent_hash
        or materialization.benchmark_id != intent.benchmark_id
    ):
        raise LifecycleError("materialized B natural provenance does not bind pre-run A")
    if (
        corpus.status is not CorpusStatus.COMPLETE
        or len(corpus.samples) != 165
        or corpus.selection_manifest_hash != intent.selection_manifest_hash
        or _controlled_hash(corpus) != intent.controlled_samples_hash
        or config.corpus_hash != corpus.content_hash
        or tuple(sample.sample_id for sample in corpus.samples) != config.ordered_sample_ids
    ):
        raise LifecycleError("materialized B corpus does not match pre-run A")
    if (
        ledger.benchmark_id != intent.benchmark_id
        or len(events) != len(ledger.event_hashes)
        or any(event.benchmark_id != intent.benchmark_id for event in events)
        or tuple(sha256_json(event.model_dump(mode="json")) for event in events)
        != ledger.event_hashes
        or tuple(event.sequence for event in events) != tuple(range(1, len(events) + 1))
        or len(events) > intent.remote_attempt_budget
    ):
        raise LifecycleError("materialized B ledger contains cross-run or invalid events")
    _validate_natural_materialization(
        manifest=materialization,
        corpus=corpus,
        selected_records=selected_records,
        config=config,
        events=events,
        event_hashes=ledger.event_hashes,
        data_root=data_root,
    )
    generation_events = [
        sha256_json(event.model_dump(mode="json"))
        for event in events
        if event.operation == config.generator_prompt_version
    ]
    if len(generation_events) < 60:
        raise LifecycleError("materialized B requires actual generation events, not cached outputs")
    payload = dict(
        schema_version="formal-lifecycle-v1",
        kind="formal_materialized_corpus_freeze",
        benchmark_id=intent.benchmark_id,
        intent_hash=intent.intent_hash,
        corpus_hash=corpus.content_hash,
        natural_materialization_hash=materialization.content_hash,
        generation_ledger_hash=sha256_json(generation_events),
        config_hash=sha256_json(config.model_dump(mode="json")),
    )
    return MaterializedCorpusFreeze.model_validate(payload | {"content_hash": sha256_json(payload)})


def verify_materialized_corpus(freeze: MaterializedCorpusFreeze | None, **inputs: Any) -> None:
    if not isinstance(freeze, MaterializedCorpusFreeze):
        raise LifecycleError("materialized B is required for formal qualification")
    if freeze != freeze_materialized_corpus(**inputs):
        raise LifecycleError("materialized B disagrees with actual corpus, A or request evidence")
