"""Uncached natural-generation stage with an A gate before every HTTP attempt."""

from __future__ import annotations

from pathlib import Path

import httpx

from .artifacts import ArtifactStore, sha256_json
from .benchmark import ArtifactAttemptLedger, RemoteAttemptBudget
from .contracts import ProblemRecord, SolutionTrace
from .corpus import (
    CorpusManifest,
    ProjectBundleManifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from .dataset_models import FrozenSelectionManifest
from .formal_lifecycle import (
    LifecycleError,
    PreRunIntent,
    assert_formal_runtime,
    verify_pre_run_intent,
)
from .hy3_client import Hy3AttemptContext, Hy3Client, Hy3Config, endpoint_identity


class FormalNaturalGenerator:
    """One create-only A-bound run session; no persisted receipt restores it.

    The caller must explicitly construct this adapter after paid authorization.
    Construction performs no HTTP request. Every attempt is durably reserved in
    the same benchmark ledger before transport, including retries and repairs.
    """

    def __init__(
        self,
        *,
        intent: PreRunIntent | None,
        selection: FrozenSelectionManifest,
        pending_corpus: CorpusManifest,
        bundle_manifest: ProjectBundleManifest,
        data_root: Path,
        repo_root: Path,
        artifacts: ArtifactStore,
        hy3_config: Hy3Config,
        judge_image_digest: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if hy3_config.max_attempts != 3:
            raise LifecycleError("formal generation requires three attempts per phase")
        capability = verify_pre_run_intent(intent, repo_root=repo_root)
        frozen = capability.intent
        assert_formal_runtime(
            capability,
            model=hy3_config.model,
            endpoint_identity=endpoint_identity(hy3_config.base_url),
            timeout_seconds=hy3_config.timeout_seconds,
            judge_image_digest=judge_image_digest,
        )
        if (selection.content_hash, pending_corpus.content_hash, bundle_manifest.content_hash) != (
            frozen.selection_manifest_hash,
            frozen.pending_corpus_hash,
            frozen.bundle_manifest_hash,
        ):
            raise LifecycleError("pre-run inputs disagree with A")
        lint_project_bundles(
            bundle_manifest.model_dump(mode="json"), root=data_root, selection=selection
        )
        lint_corpus_manifest(
            pending_corpus.model_dump(mode="json"),
            root=data_root,
            selection=selection,
            bundle_manifest=bundle_manifest,
        )
        self._capability, self._hy3_config, self._judge_digest = (
            capability,
            hy3_config,
            judge_image_digest,
        )
        self._artifacts, self._transport = artifacts, transport
        self._base = Path("benchmarks") / frozen.benchmark_id
        self._records = {entry.problem_id: entry.record_hash for entry in selection.entries}
        self._specs = {spec.sample_id: spec for spec in frozen.planned_samples}
        # The run marker uses O_EXCL through ArtifactStore: partial runs cannot resume
        # or start a new ledger under the same intent.
        artifacts.write_json(self._base / "pre-run-intent.json", frozen.model_dump(mode="json"))
        self.ledger = ArtifactAttemptLedger(artifacts, benchmark_id=frozen.benchmark_id)
        self.budget = RemoteAttemptBudget(
            limit=frozen.remote_attempt_budget,
            benchmark_id=frozen.benchmark_id,
            event_sink=self.ledger.record,
        )
        self._started: set[str] = set()

    def generate(self, sample_id: str, problem: ProblemRecord) -> SolutionTrace:
        intent = self._capability.intent
        if (
            sample_id not in intent.natural_sample_ids
            or sample_id in self._started
            or problem.problem_id != self._specs[sample_id].problem_id
            or sha256_json(problem.model_dump(mode="json")) != self._records.get(problem.problem_id)
        ):
            raise LifecycleError("natural sample or selected problem does not match pre-run A")
        self._started.add(sample_id)

        def observe(context: Hy3AttemptContext) -> None:
            assert_formal_runtime(
                self._capability,
                model=self._hy3_config.model,
                endpoint_identity=endpoint_identity(self._hy3_config.base_url),
                timeout_seconds=self._hy3_config.timeout_seconds,
                judge_image_digest=self._judge_digest,
            )
            self.budget.reserve(context, sample_id=sample_id)

        client = Hy3Client(
            self._hy3_config,
            cache=None,
            transport=self._transport,
            parameters={p.name: p.value for p in intent.model_parameters},
            attempt_observer=observe,
        )
        try:
            trace = client.generate(problem, trace_id=sample_id)
            self._artifacts.write_json(
                self._base / "natural" / sample_id / "trace.json", trace.model_dump(mode="json")
            )
            return trace
        except Exception:
            self._artifacts.write_json(
                self._base / "natural" / sample_id / "failure.json",
                {
                    "kind": "formal_natural_failure",
                    "intent_hash": intent.intent_hash,
                    "benchmark_id": intent.benchmark_id,
                    "sample_id": sample_id,
                    "formal_eligibility": False,
                    "remote_attempts_used": self.budget.used,
                },
            )
            raise
        finally:
            client.close()
