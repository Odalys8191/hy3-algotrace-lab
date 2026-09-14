"""Real, uncached non-formal benchmark execution through existing components."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from .artifacts import ArtifactStore, ArtifactStoreError, sha256_json
from .benchmark import BudgetExceededError
from .benchmark_models import BenchmarkConfig, HumanConfirmedLabel, MetricObservation, SampleKind
from .catalog import ProblemCatalog, ProblemSummary, problem_content_hash
from .contracts import (
    CheckerSemantics,
    JudgeEvidence,
    JudgeStatus,
    OutputComparison,
    ProblemOracle,
    ProblemRecord,
    SolutionTrace,
)
from .dataset_models import read_trusted_file
from .docker_judge import DockerCliBackend, DockerCommandFactory, DockerJudge
from .evaluator import EvidenceFusion, InfrastructureEvidenceError, ReviewOrchestrator
from .hy3_client import (
    Hy3AttemptContext,
    Hy3AttemptOutcome,
    Hy3Client,
    Hy3Config,
    Hy3ResponseError,
    Hy3SpendLimitError,
    Hy3TokenLimitError,
    RmbCostGuard,
    TokenQuotaGuard,
    endpoint_identity,
)
from .prompts import (
    ADVERSARIAL_REVIEW_PROMPT_VERSION,
    ARBITER_PROMPT_VERSION,
    GENERATOR_PROMPT_VERSION,
    LOGIC_REVIEW_PROMPT_VERSION,
)
from .rules import RuleEngine


class LiveSampleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sample_id: str
    trace: SolutionTrace | None = None
    gold_label: HumanConfirmedLabel | None = None


class LiveInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["nonformal_live_inputs"] = "nonformal_live_inputs"
    formal: Literal[False] = False
    samples: tuple[LiveSampleInput, ...]

    @model_validator(mode="after")
    def unique_samples(self) -> Self:
        ids = [sample.sample_id for sample in self.samples]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("live inputs require unique nonempty sample IDs")
        return self

    @property
    def content_hash(self) -> str:
        return sha256_json(self.model_dump(mode="json"))


class JudgeRunner(Protocol):
    def judge(
        self,
        problem: ProblemRecord,
        cpp_source: str,
        output_comparison: OutputComparison = OutputComparison.EXACT,
    ) -> JudgeEvidence: ...


def _safe_exception_category(error: Exception) -> str:
    if isinstance(error, InfrastructureEvidenceError):
        return "infrastructure_evidence_error"
    if isinstance(error, ArtifactStoreError):
        return "artifact_error"
    if isinstance(error, ValidationError):
        return "validation_error"
    if isinstance(error, (OSError, subprocess.SubprocessError)):
        return "local_transport_error"
    return "unexpected_error"


class LiveExecutionError(RuntimeError):
    """Safe execution failure that must not become a benchmark observation."""


@dataclass(frozen=True, slots=True)
class NonformalProblemBundle:
    """Hash-checked private bundle without formal tag-derived topic qualification."""

    record: ProblemRecord
    oracle: ProblemOracle
    reference_cpp: str
    gold_trace: SolutionTrace
    output_comparison: OutputComparison = OutputComparison.EXACT


class NonformalProblemCatalog:
    """Strict live-only loader preserving the already reviewed primary topic."""

    _REQUIRED = frozenset({"problem.json", "oracle.json", "gold_trace.json", "reference.cpp"})
    _OPTIONAL = frozenset({"checker.json"})

    def __init__(self, bundles: tuple[NonformalProblemBundle, ...]) -> None:
        by_id = {bundle.record.problem_id: bundle for bundle in bundles}
        if not by_id or len(by_id) != len(bundles):
            raise ValueError("nonformal catalog needs unique nonempty problem IDs")
        self._by_id = dict(sorted(by_id.items()))

    @classmethod
    def from_directory(cls, root: Path) -> NonformalProblemCatalog:
        if not root.is_dir() or root.is_symlink():
            raise ValueError("invalid nonformal catalog root")
        bundles: list[NonformalProblemBundle] = []
        for entry in sorted(root.iterdir(), key=lambda path: path.name):
            if entry.is_symlink():
                raise ValueError("nonformal catalog symlinks are forbidden")
            if entry.is_file():
                if entry.name != "manifest.json":
                    raise ValueError("unknown nonformal catalog root file")
                continue
            if not entry.is_dir():
                raise ValueError("unknown nonformal catalog entry")
            members = {path.name for path in entry.iterdir()}
            if members - cls._REQUIRED - cls._OPTIONAL or not cls._REQUIRED <= members:
                raise ValueError("invalid nonformal bundle members")
            if any(path.is_symlink() or not path.is_file() for path in entry.iterdir()):
                raise ValueError("nonformal bundle members must be regular files")
            record = ProblemRecord.model_validate_json((entry / "problem.json").read_bytes())
            oracle = ProblemOracle.model_validate_json((entry / "oracle.json").read_bytes())
            trace = SolutionTrace.model_validate_json((entry / "gold_trace.json").read_bytes())
            reference = (entry / "reference.cpp").read_text(encoding="utf-8")
            if (
                record.problem_id != entry.name
                or record.content_hash != problem_content_hash(record)
                or oracle.problem_id != record.problem_id
                or oracle.reference_solution_hash != sha256_json(reference)
                or trace.problem_id != record.problem_id
            ):
                raise ValueError("nonformal bundle identity or content hash mismatch")
            comparison = OutputComparison.EXACT
            if "checker.json" in members:
                checker = CheckerSemantics.model_validate_json(
                    (entry / "checker.json").read_bytes()
                )
                if checker.problem_id != record.problem_id:
                    raise ValueError("nonformal checker identity mismatch")
                comparison = checker.output_comparison
            bundles.append(NonformalProblemBundle(record, oracle, reference, trace, comparison))
        return cls(tuple(bundles))

    def list_problems(self) -> tuple[ProblemSummary, ...]:
        return tuple(
            ProblemSummary(
                problem_id=bundle.record.problem_id,
                title=bundle.record.title,
                topic=bundle.record.topic,
                rating=bundle.record.rating,
            )
            for bundle in self._by_id.values()
        )

    def get_bundle(self, problem_id: str) -> NonformalProblemBundle:
        try:
            return self._by_id[problem_id]
        except KeyError as error:
            raise KeyError(f"unknown nonformal problem ID: {problem_id}") from error


def catalog_hash(catalog: ProblemCatalog | NonformalProblemCatalog) -> str:
    entries = []
    for summary in catalog.list_problems():
        bundle = catalog.get_bundle(summary.problem_id)
        entry: dict[str, Any] = {
            "problem_id": summary.problem_id,
            "problem": bundle.record.content_hash,
            "oracle": sha256_json(bundle.oracle.model_dump(mode="json")),
            "reference": sha256_json(bundle.reference_cpp),
            "gold_trace": sha256_json(bundle.gold_trace.model_dump(mode="json")),
        }
        # Only non-default comparison semantics participate so historical
        # exact-comparison catalog hashes stay byte-stable.
        if bundle.output_comparison is not OutputComparison.EXACT:
            entry["output_comparison"] = bundle.output_comparison.value
        entries.append(entry)
    return sha256_json(entries)


def validate_live_inputs(
    config: BenchmarkConfig,
    catalog: ProblemCatalog | NonformalProblemCatalog,
    inputs: LiveInputs,
) -> None:
    if config.formal or config.verified_data_evidence is not None:
        raise ValueError("live CLI adapter supports non-formal runs only")
    if config.selection_hash != catalog_hash(catalog) or config.corpus_hash != inputs.content_hash:
        raise ValueError("frozen catalog or live-input hash mismatch")
    if tuple(sample.sample_id for sample in inputs.samples) != config.ordered_sample_ids:
        raise ValueError("live inputs must follow exact frozen sample order")
    if config.audit_sample_ids != config.ordered_sample_ids:
        raise ValueError("live adapter requires auditing every sample")
    expected_prompts = (
        GENERATOR_PROMPT_VERSION,
        LOGIC_REVIEW_PROMPT_VERSION,
        ADVERSARIAL_REVIEW_PROMPT_VERSION,
        ARBITER_PROMPT_VERSION,
    )
    actual_prompts = (
        config.generator_prompt_version,
        config.logic_review_prompt_version,
        config.adversarial_review_prompt_version,
        config.arbiter_prompt_version,
    )
    if actual_prompts != expected_prompts:
        raise ValueError("frozen prompt versions do not match repository prompts")
    parameters = {p.name: p.value for p in config.model_parameters}
    if parameters.get("reasoning_effort") != "high" or set(parameters) not in (
        {"reasoning_effort"},
        {"max_tokens", "reasoning_effort"},
    ):
        raise ValueError("live Hy3 client requires reasoning_effort=high and optional max_tokens")
    max_tokens = parameters.get("max_tokens")
    if max_tokens is not None and (
        isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 1
    ):
        raise ValueError("live max_tokens must be a positive integer")
    for spec, sample in zip(config.sample_specs, inputs.samples, strict=True):
        bundle = catalog.get_bundle(spec.problem_id)
        if (bundle.record.topic, bundle.record.rating_band) != (spec.topic, spec.rating_band):
            raise ValueError("live catalog stratum does not match frozen sample")
        generates = sample.sample_id in config.generation_sample_ids
        if generates and (spec.sample_kind is not SampleKind.NATURAL or sample.trace is not None):
            raise ValueError("only natural samples without supplied traces can generate")
        if not generates and (sample.trace is None or sample.trace.problem_id != spec.problem_id):
            raise ValueError("audit-only sample needs an identity-matching trace")
        if spec.sample_kind is SampleKind.NATURAL and sample.gold_label is not None:
            raise ValueError("natural live outputs cannot have preassigned human labels")
        if sample.gold_label is not None and sample.gold_label.sample_id != spec.sample_id:
            raise ValueError("live input gold label identity mismatch")


def probe_docker(image_reference: str) -> None:
    """Require an already available pinned image before spending any model calls."""
    for argv in (
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        ["docker", "image", "inspect", image_reference],
    ):
        try:
            result = subprocess.run(argv, capture_output=True, check=False, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise LiveExecutionError("Docker or pinned Judge image unavailable") from None
        if result.returncode != 0:
            raise LiveExecutionError("Docker or pinned Judge image unavailable")


class LiveExecutor:
    """Sequential callback for BenchmarkRunner; never claims formal qualification."""

    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        catalog: ProblemCatalog | NonformalProblemCatalog,
        inputs: LiveInputs,
        artifacts: ArtifactStore,
        hy3_config: Hy3Config,
        judge: JudgeRunner,
        image_reference: str,
        transport: httpx.BaseTransport | None = None,
        cost_guard: RmbCostGuard | None = None,
        token_guard: TokenQuotaGuard | None = None,
    ) -> None:
        validate_live_inputs(config, catalog, inputs)
        if config.model != hy3_config.model or config.endpoint_identity != endpoint_identity(
            hy3_config.base_url
        ):
            raise ValueError("frozen model or endpoint does not match runtime")
        if (
            config.timeout_seconds is not None
            and config.timeout_seconds != hy3_config.timeout_seconds
        ):
            raise ValueError("frozen read timeout does not match runtime HY3_TIMEOUT_SECONDS")
        match = re.fullmatch(r"[^\s@]+@(sha256:[0-9a-f]{64})", image_reference)
        if match is None or match.group(1) != config.judge_image_digest:
            raise ValueError("frozen Judge digest does not match runtime")
        # A nonformal run still must not send credentials to an unencrypted remote service.
        if not config.endpoint_identity.startswith("https://"):
            raise ValueError("live model endpoint must use HTTPS")
        self._config = config
        self._catalog = catalog
        self._samples = {sample.sample_id: sample for sample in inputs.samples}
        self._specs = {spec.sample_id: spec for spec in config.sample_specs}
        self._artifacts = artifacts
        self._hy3 = hy3_config
        self._judge = judge
        self._transport = transport
        self._parameters = {
            parameter.name: parameter.value for parameter in config.model_parameters
        }
        self._cost_guard = cost_guard
        self._token_guard = token_guard

    def __call__(
        self,
        sample_id: str,
        observer: Callable[[Hy3AttemptContext], int | None],
    ) -> MetricObservation:
        sample, spec = self._samples[sample_id], self._specs[sample_id]
        bundle = self._catalog.get_bundle(spec.problem_id)
        root = Path("benchmarks") / self._config.benchmark_id / "live-evidence" / sample_id
        phase = "generation"
        local_sequence = 0

        def observe_attempt(context: Hy3AttemptContext) -> int:
            nonlocal local_sequence
            observed_sequence = observer(context)
            if (
                isinstance(observed_sequence, bool)
                or not isinstance(observed_sequence, int)
                or observed_sequence < 1
            ):
                local_sequence += 1
                sequence = local_sequence
            else:
                sequence = observed_sequence
                local_sequence = max(local_sequence, sequence)
            self._artifacts.write_json(
                root / "attempts" / f"{sequence:06d}" / "reservation.json",
                {
                    "schema_version": "1.0",
                    "kind": "nonformal_hy3_attempt_reservation",
                    "formal_eligibility": False,
                    "sample_id": sample_id,
                    "attempt_sequence": sequence,
                    "operation": context.operation,
                    "phase": context.phase,
                    "retry_number": context.retry_number,
                    "reviewer": context.reviewer,
                    "reservation_upper_bound_rmb": context.reservation_upper_bound_rmb,
                    "charged_upper_bound_rmb": context.charged_upper_bound_rmb,
                    "remaining_upper_bound_rmb": context.remaining_upper_bound_rmb,
                    "reservation_upper_bound_tokens": context.reservation_upper_bound_tokens,
                    "charged_upper_bound_tokens": context.charged_upper_bound_tokens,
                    "remaining_upper_bound_tokens": context.remaining_upper_bound_tokens,
                },
            )
            return sequence

        def observe_outcome(outcome: Hy3AttemptOutcome) -> None:
            sequence = outcome.sequence
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
                raise ValueError("attempt outcome is missing its reserved sequence")
            usage = (
                {
                    "prompt_tokens": outcome.usage.prompt_tokens,
                    "completion_tokens": outcome.usage.completion_tokens,
                    "total_tokens": outcome.usage.total_tokens,
                }
                if outcome.usage is not None
                else None
            )
            self._artifacts.write_json(
                root / "attempts" / f"{sequence:06d}" / "settlement.json",
                {
                    "schema_version": "1.0",
                    "kind": "nonformal_hy3_attempt_settlement",
                    "formal_eligibility": False,
                    "sample_id": sample_id,
                    "attempt_sequence": sequence,
                    "category": outcome.category,
                    "http_status": outcome.http_status,
                    "finish_reason": outcome.finish_reason,
                    "usage": usage,
                    "usage_status": outcome.usage_status,
                    "charged_attempt_upper_bound_rmb": (outcome.charged_attempt_upper_bound_rmb),
                    "charged_upper_bound_rmb": outcome.charged_upper_bound_rmb,
                    "remaining_upper_bound_rmb": outcome.remaining_upper_bound_rmb,
                    "charged_attempt_upper_bound_tokens": (
                        outcome.charged_attempt_upper_bound_tokens
                    ),
                    "charged_upper_bound_tokens": outcome.charged_upper_bound_tokens,
                    "remaining_upper_bound_tokens": outcome.remaining_upper_bound_tokens,
                    "validation_issues": [
                        {"path": issue.path, "code": issue.code}
                        for issue in outcome.validation_issues
                    ],
                },
            )

        client = Hy3Client(
            self._hy3,
            cache=None,
            transport=self._transport,
            attempt_observer=observe_attempt,
            attempt_outcome_observer=observe_outcome,
            parameters=self._parameters,
            cost_guard=self._cost_guard,
            token_guard=self._token_guard,
        )
        failed = False
        try:
            trace = client.generate(bundle.record) if sample.trace is None else sample.trace
            self._artifacts.write_json(root / "trace.json", trace.model_dump(mode="json"))
            phase = "judge"
            judge = self._judge.judge(
                bundle.record,
                trace.code,
                output_comparison=bundle.output_comparison,
            )
            # Keep raw execution evidence protected, including failed executions.
            self._artifacts.write_json(root / "judge.json", judge.model_dump(mode="json"))
            if judge.compile_status in {JudgeStatus.INFRASTRUCTURE_ERROR, JudgeStatus.NOT_RUN} or (
                judge.verdict in {JudgeStatus.INFRASTRUCTURE_ERROR, JudgeStatus.NOT_RUN}
            ):
                raise InfrastructureEvidenceError("Judge did not execute")
            phase = "review"
            findings = RuleEngine().evaluate(trace)
            reviews = ReviewOrchestrator(client).review(bundle.record, bundle.oracle, trace)
            audit = EvidenceFusion().fuse(
                run_id=f"{self._config.benchmark_id}-{sample_id}",
                problem=bundle.record,
                trace=trace,
                judge=judge,
                rule_findings=findings,
                reviews=reviews,
            )
            phase = "persist"
            self._artifacts.write_json(
                root / "result.json",
                {
                    "schema_version": "1.2",
                    "kind": "nonformal_live_sample_evidence",
                    "formal_eligibility": False,
                    "sample_id": sample_id,
                    "trace": trace.model_dump(mode="json"),
                    "judge": judge.model_dump(mode="json"),
                    "audit": audit.model_dump(mode="json"),
                    "primary_review_agreement": not reviews.material_disagreement,
                    "arbitration_used": reviews.arbiter is not None,
                },
            )
            label = sample.gold_label
            step_numbers = {step.step_id: step.step_number for step in trace.steps}
            return MetricObservation(
                sample_id=sample_id,
                problem_id=spec.problem_id,
                sample_kind=spec.sample_kind,
                topic=spec.topic,
                rating_band=spec.rating_band,
                gold_final_correct=label.final_correct if label else None,
                gold_process_valid=label.process_valid if label else None,
                gold_first_error_step=label.first_error_step if label else None,
                gold_taxonomy=label.taxonomy if label else None,
                predicted_final_correct=audit.final_correct,
                predicted_process_valid=audit.process_valid,
                predicted_first_error_step=step_numbers.get(audit.first_material_error_step_id)
                if audit.first_material_error_step_id
                else None,
                predicted_taxonomy=audit.final_error_taxonomy,
                needs_human_review=audit.needs_human_review,
                primary_review_agreement=not reviews.material_disagreement,
                arbitration_used=reviews.arbiter is not None,
            )
        except (Hy3SpendLimitError, Hy3TokenLimitError) as error:
            resource = "RMB spend cap" if isinstance(error, Hy3SpendLimitError) else "token quota"
            raise BudgetExceededError(f"remote {resource} exhausted") from error
        except BudgetExceededError:
            raise
        except Hy3ResponseError as error:
            diagnostic = error.diagnostic
            self._artifacts.write_json(
                root / "failure.json",
                {
                    "schema_version": "1.2",
                    "kind": "nonformal_live_failure",
                    "sample_id": sample_id,
                    "phase": phase,
                    "formal_eligibility": False,
                    "error_category": (
                        diagnostic.category if diagnostic is not None else "response_error"
                    ),
                    "reviewer": diagnostic.reviewer if diagnostic is not None else None,
                    "validation_issues": [
                        {"path": issue.path, "code": issue.code}
                        for issue in (
                            diagnostic.validation_issues if diagnostic is not None else ()
                        )
                    ],
                    "http_status": diagnostic.http_status if diagnostic is not None else None,
                    "finish_reason": (diagnostic.finish_reason if diagnostic is not None else None),
                },
            )
            failed = True
        except Exception as error:
            self._artifacts.write_json(
                root / "failure.json",
                {
                    "schema_version": "1.2",
                    "kind": "nonformal_live_failure",
                    "sample_id": sample_id,
                    "phase": phase,
                    "formal_eligibility": False,
                    "error_category": _safe_exception_category(error),
                },
            )
            failed = True
        finally:
            client.close()
        if failed:
            raise LiveExecutionError(f"live sample failed during {phase}") from None
        raise AssertionError("unreachable")  # pragma: no cover


def load_live_inputs(path: Path) -> LiveInputs:
    snapshot = read_trusted_file(path, logical_id="live-inputs", max_bytes=64 * 1024**2)
    return LiveInputs.model_validate_json(snapshot.contents)


def build_live_executor(
    *,
    config: BenchmarkConfig,
    catalog_root: Path,
    inputs_path: Path,
    artifacts: ArtifactStore,
    cost_guard: RmbCostGuard | None = None,
    token_guard: TokenQuotaGuard | None = None,
) -> LiveExecutor:
    image = os.environ.get("HY3_JUDGE_IMAGE", "")
    parameters = {parameter.name: parameter.value for parameter in config.model_parameters}
    max_tokens = parameters.get("max_tokens")
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int):
            raise ValueError("frozen max_tokens must be an integer")
        if cost_guard is None:
            spend_cap = os.environ.get("HY3_SPEND_CAP_RMB", "")
            if not spend_cap:
                raise ValueError("HY3_SPEND_CAP_RMB is required with frozen max_tokens")
            cost_guard = RmbCostGuard(limit_rmb=spend_cap, max_output_tokens=max_tokens)
    elif cost_guard is not None or token_guard is not None:
        raise ValueError("resource guards require frozen max_tokens")
    executor = LiveExecutor(
        config=config,
        catalog=NonformalProblemCatalog.from_directory(catalog_root),
        inputs=load_live_inputs(inputs_path),
        artifacts=artifacts,
        hy3_config=Hy3Config.from_env(),
        image_reference=image,
        judge=DockerJudge(
            backend=DockerCliBackend(command_factory=DockerCommandFactory(image=image))
        ),
        cost_guard=cost_guard,
        token_guard=token_guard,
    )
    probe_docker(image)
    return executor
