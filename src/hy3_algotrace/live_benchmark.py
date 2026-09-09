"""Real, uncached non-formal benchmark execution through existing components."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol, Self

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

from .artifacts import ArtifactStore, sha256_json
from .benchmark import BudgetExceededError
from .benchmark_models import BenchmarkConfig, HumanConfirmedLabel, MetricObservation, SampleKind
from .catalog import ProblemCatalog
from .contracts import JudgeEvidence, JudgeStatus, ProblemRecord, SolutionTrace
from .dataset_models import read_trusted_file
from .docker_judge import DockerCliBackend, DockerCommandFactory, DockerJudge
from .evaluator import EvidenceFusion, InfrastructureEvidenceError, ReviewOrchestrator
from .hy3_client import Hy3AttemptContext, Hy3Client, Hy3Config, endpoint_identity
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
    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence: ...


class LiveExecutionError(RuntimeError):
    """Safe execution failure that must not become a benchmark observation."""


def catalog_hash(catalog: ProblemCatalog) -> str:
    entries = []
    for summary in catalog.list_problems():
        bundle = catalog.get_bundle(summary.problem_id)
        entries.append(
            {
                "problem_id": summary.problem_id,
                "problem": bundle.record.content_hash,
                "oracle": sha256_json(bundle.oracle.model_dump(mode="json")),
                "reference": sha256_json(bundle.reference_cpp),
                "gold_trace": sha256_json(bundle.gold_trace.model_dump(mode="json")),
            }
        )
    return sha256_json(entries)


def validate_live_inputs(
    config: BenchmarkConfig,
    catalog: ProblemCatalog,
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
    if [(p.name, p.value) for p in config.model_parameters] != [("reasoning_effort", "high")]:
        raise ValueError("live Hy3 client only supports reasoning_effort=high")
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
        catalog: ProblemCatalog,
        inputs: LiveInputs,
        artifacts: ArtifactStore,
        hy3_config: Hy3Config,
        judge: JudgeRunner,
        image_reference: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        validate_live_inputs(config, catalog, inputs)
        if config.model != hy3_config.model or config.endpoint_identity != endpoint_identity(
            hy3_config.base_url
        ):
            raise ValueError("frozen model or endpoint does not match runtime")
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

    def __call__(
        self,
        sample_id: str,
        observer: Callable[[Hy3AttemptContext], None],
    ) -> MetricObservation:
        sample, spec = self._samples[sample_id], self._specs[sample_id]
        bundle = self._catalog.get_bundle(spec.problem_id)
        root = Path("benchmarks") / self._config.benchmark_id / "live-evidence" / sample_id
        phase = "generation"
        client = Hy3Client(
            self._hy3, cache=None, transport=self._transport, attempt_observer=observer
        )
        failed = False
        try:
            trace = client.generate(bundle.record) if sample.trace is None else sample.trace
            self._artifacts.write_json(root / "trace.json", trace.model_dump(mode="json"))
            phase = "judge"
            judge = self._judge.judge(bundle.record, trace.code)
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
        except BudgetExceededError:
            raise
        except Exception:
            self._artifacts.write_json(
                root / "failure.json",
                {
                    "schema_version": "1.2",
                    "kind": "nonformal_live_failure",
                    "sample_id": sample_id,
                    "phase": phase,
                    "formal_eligibility": False,
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
) -> LiveExecutor:
    image = os.environ.get("HY3_JUDGE_IMAGE", "")
    executor = LiveExecutor(
        config=config,
        catalog=ProblemCatalog.from_directory(catalog_root),
        inputs=load_live_inputs(inputs_path),
        artifacts=artifacts,
        hy3_config=Hy3Config.from_env(),
        image_reference=image,
        judge=DockerJudge(
            backend=DockerCliBackend(command_factory=DockerCommandFactory(image=image))
        ),
    )
    probe_docker(image)
    return executor
