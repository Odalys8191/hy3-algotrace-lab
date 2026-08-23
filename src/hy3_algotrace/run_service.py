"""Immutable run orchestration for generation, judging, review, and evidence fusion."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

from pydantic import ValidationError

from .api_models import (
    InternalRunReport,
    ProblemSummaryResponse,
    PublicAuditReport,
    PublicJudgeReport,
    PublicJudgeTestResult,
    PublicRunReport,
    PublicSolutionTrace,
    RunAcceptedResponse,
    RunCreateRequest,
    RunFailure,
    RunFailureCode,
    RunMode,
    RunReadResponse,
    RunTransition,
    RunTransitionEvent,
    StoredRunTransition,
)
from .artifacts import (
    ArtifactExistsError,
    ArtifactRef,
    ArtifactStore,
    ArtifactStoreError,
    sha256_json,
)
from .catalog import ProblemBundle, ProblemSummary
from .contracts import (
    AuditReport,
    JudgeEvidence,
    JudgeStatus,
    ModelParameter,
    ProblemOracle,
    ProblemRecord,
    RunManifest,
    RunStatus,
    SolutionTrace,
)
from .evaluator import EvidenceFusion, InfrastructureEvidenceError, ReviewOutcome
from .executor import RunExecutor
from .rules import RuleEngine

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_CREDENTIAL_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+\-/]+=*"),
    re.compile(
        r"(?i)\b(?:(?:hy3[\s_-]+)?api[\s_-]*key|authorization)"
        r"\b(?:\s*(?::|=|\bis\b)\s*|\s+)"
        r"[A-Za-z0-9._~+\-/]+=*"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)
_POSIX_PATH_TOKEN = r"[^/\s,;)\]}'\"]+"
_PUBLIC_PATH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?P<quote>[\"'])/(?!/)[^\"'\r\n]*(?P=quote)"),
        '"[REDACTED]"',
    ),
    (
        re.compile(r"\(\s*/(?!/)[^)\r\n]*\s*\)"),
        "([REDACTED])",
    ),
    (
        re.compile(r"(\b[A-Za-z_][\w.-]*\s*=\s*)/(?!/)[^,;\r\n]*"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            rf"(?<![\w:/])/(?!/)(?:{_POSIX_PATH_TOKEN}/)+"
            rf"(?:{_POSIX_PATH_TOKEN})?"
        ),
        "[REDACTED]",
    ),
    (
        re.compile(
            rf"(?i)(\b(?:path|directory|dir|file|root|config)\s+)"
            rf"/(?!/){_POSIX_PATH_TOKEN}(?=\s|[,;:.)\]}}'\"]|$)"
        ),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            rf"(?<![\w:/])/(?!/){_POSIX_PATH_TOKEN}"
            r"(?=[,;:.)\]}'\"]|$)"
        ),
        "[REDACTED]",
    ),
)
_PROTECTED_KEY_PARTS = (
    "hidden",
    "generated",
    "expected_output",
    "oracle",
    "reference",
    "api_key",
    "authorization",
    "filesystem_path",
    "container_path",
    "workspace_path",
)
_EVENT_STATUS: Mapping[RunTransitionEvent, RunStatus] = {
    RunTransitionEvent.REQUEST: RunStatus.QUEUED,
    RunTransitionEvent.QUEUED: RunStatus.QUEUED,
    RunTransitionEvent.RUNNING: RunStatus.RUNNING,
    RunTransitionEvent.COMPLETED: RunStatus.COMPLETED,
    RunTransitionEvent.FAILED: RunStatus.FAILED,
}
_ALLOWED_NEXT: Mapping[RunTransitionEvent, frozenset[RunTransitionEvent]] = {
    RunTransitionEvent.REQUEST: frozenset({RunTransitionEvent.QUEUED}),
    RunTransitionEvent.QUEUED: frozenset({RunTransitionEvent.RUNNING, RunTransitionEvent.FAILED}),
    RunTransitionEvent.RUNNING: frozenset(
        {RunTransitionEvent.COMPLETED, RunTransitionEvent.FAILED}
    ),
}
_SAFE_FAILURE_MESSAGES: Mapping[RunFailureCode, str] = {
    RunFailureCode.GENERATION_FAILED: "solution generation failed",
    RunFailureCode.JUDGE_INFRASTRUCTURE: "judge infrastructure failed",
    RunFailureCode.REVIEW_FAILED: "review or arbitration failed",
    RunFailureCode.ARTIFACT_FAILURE: "immutable artifact persistence failed",
    RunFailureCode.ABANDONED_ON_RESTART: "active run was abandoned on restart",
    RunFailureCode.EXECUTOR_FAILURE: "background executor rejected the run",
    RunFailureCode.INTERNAL_FAILURE: "run orchestration failed",
}
_DEGRADED_WORKER_MESSAGE = "background worker failed before terminal state was persisted"


class ProblemNotFoundError(KeyError):
    """The requested identifier is not a formal catalog entry."""


class RunNotFoundError(KeyError):
    """The requested run has no immutable request artifact."""


class InvalidRunHistoryError(RuntimeError):
    """An immutable transition chain is missing, malformed, or disconnected."""


class TerminalRunError(RuntimeError):
    """A terminal immutable run cannot accept another transition."""


class TransitionConflictError(RuntimeError):
    """The requested transition is invalid for the latest persisted state."""


class RunFailurePersistenceError(RuntimeError):
    """A terminal failure could not be durably recorded."""


class Catalog(Protocol):
    def list_problems(self) -> tuple[ProblemSummary, ...]: ...

    def get_public_detail(self, problem_id: str) -> dict[str, Any]: ...

    def get_bundle(self, problem_id: str) -> ProblemBundle: ...


class Generator(Protocol):
    def generate(self, problem: ProblemRecord) -> SolutionTrace: ...


class JudgeRunner(Protocol):
    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence: ...


class ReviewRunner(Protocol):
    def review(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
    ) -> ReviewOutcome: ...


class RunService:
    """Coordinate one immutable run using only injected interfaces."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        artifacts: ArtifactStore,
        generator: Generator,
        judge: JudgeRunner,
        reviews: ReviewRunner,
        executor: RunExecutor,
        rules: RuleEngine | None = None,
        fusion: EvidenceFusion | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        model_name: str = "hy3",
        prompt_version: str = "task5-v1",
        model_parameters: Mapping[str, ModelParameter] | None = None,
        code_revision: str = "unknown",
        container_image_digest: str = f"sha256:{'0' * 64}",
    ) -> None:
        self._catalog = catalog
        self._artifacts = artifacts
        self._generator = generator
        self._judge = judge
        self._reviews = reviews
        self._executor = executor
        self._rules = rules or RuleEngine()
        self._fusion = fusion or EvidenceFusion()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._model_name = model_name
        self._prompt_version = prompt_version
        self._model_parameters = dict(model_parameters or {"reasoning_effort": "high"})
        self._code_revision = code_revision
        self._container_image_digest = container_image_digest
        self._lock = threading.RLock()

    def submit(self, request: RunCreateRequest) -> RunAcceptedResponse:
        bundle = self._get_formal_bundle(request.problem_id)
        run_id = self._new_run_id()
        created_at = self._aware_now()
        request_payload = cast(
            dict[str, Any],
            self._sanitize_credentials(request.model_dump(mode="json")),
        )
        request_path = Path("runs") / run_id / "request.json"
        with self._lock:
            request_ref = self._artifacts.write_json(request_path, request_payload)
            base_hashes = {"request": request_ref.content_hash}
            first_transition = self._make_transition(
                run_id=run_id,
                request=request,
                event=RunTransitionEvent.REQUEST,
                sequence=0,
                occurred_at=created_at,
                created_at=created_at,
                request_hash=request_ref.content_hash,
                previous_hash=None,
                artifact_hashes=base_hashes,
            )
            first_ref = self._write_transition(first_transition)
            queued = self._make_transition(
                run_id=run_id,
                request=request,
                event=RunTransitionEvent.QUEUED,
                sequence=1,
                occurred_at=self._aware_now(),
                created_at=created_at,
                request_hash=request_ref.content_hash,
                previous_hash=first_ref.content_hash,
                artifact_hashes={**base_hashes, "previous_transition": first_ref.content_hash},
            )
            self._write_transition(queued)
            self._artifacts.write_json(
                Path("run-index") / f"{run_id}.json",
                {"schema_version": "1.2", "run_id": run_id},
            )
        try:
            self._executor.submit(
                lambda: self._execute(run_id, request, bundle),
                task_id=run_id,
            )
        except RunFailurePersistenceError:
            raise
        except Exception:
            try:
                self._append_failure(run_id, request, RunFailureCode.EXECUTOR_FAILURE)
            except ArtifactStoreError as error:
                raise RunFailurePersistenceError(
                    "failed to persist executor failure transition"
                ) from error
        return RunAcceptedResponse(run_id=run_id)

    def get_run(self, run_id: str) -> RunReadResponse:
        history = self.get_transition_history(run_id)
        latest = history[-1].transition
        if latest.event is RunTransitionEvent.COMPLETED:
            if latest.public_report_path is None:  # pragma: no cover - model invariant
                raise InvalidRunHistoryError("completed run has no public report")
            expected_path = str(Path("runs") / run_id / "public-report.json")
            if latest.public_report_path != expected_path:
                raise InvalidRunHistoryError("public report path is not bound to its run")
            payload = self._artifacts.read_json(latest.public_report_path)
            if sha256_json(payload) != latest.manifest.artifact_hashes.get("public_report"):
                raise InvalidRunHistoryError("public report hash does not match its manifest")
            return RunReadResponse(
                run_id=run_id,
                status=RunStatus.COMPLETED,
                report=PublicRunReport.model_validate(payload),
            )
        if latest.event is RunTransitionEvent.FAILED:
            return RunReadResponse(
                run_id=run_id,
                status=RunStatus.FAILED,
                failure=latest.failure,
            )
        if (
            latest.event is RunTransitionEvent.RUNNING
            and self._executor.failure_for(run_id) is not None
        ):
            return RunReadResponse(
                run_id=run_id,
                status=RunStatus.RUNNING,
                degraded_failure=RunFailure(
                    code=RunFailureCode.INTERNAL_FAILURE,
                    message=_DEGRADED_WORKER_MESSAGE,
                ),
            )
        return RunReadResponse(run_id=run_id, status=_EVENT_STATUS[latest.event])

    def get_internal_report(self, run_id: str) -> InternalRunReport:
        latest = self.get_transition_history(run_id)[-1].transition
        if latest.event is not RunTransitionEvent.COMPLETED or latest.internal_report_path is None:
            raise RunNotFoundError(f"run has no completed internal report: {run_id}")
        expected_path = str(Path("runs") / run_id / "internal-report.json")
        if latest.internal_report_path != expected_path:
            raise InvalidRunHistoryError("internal report path is not bound to its run")
        payload = self._artifacts.read_json(latest.internal_report_path)
        if sha256_json(payload) != latest.manifest.artifact_hashes.get("internal_report"):
            raise InvalidRunHistoryError("internal report hash does not match its manifest")
        return InternalRunReport.model_validate(payload)

    def get_transition_history(self, run_id: str) -> tuple[StoredRunTransition, ...]:
        history = self._load_transition_history(run_id, allow_partial=False)
        return history

    def _load_transition_history(
        self, run_id: str, *, allow_partial: bool
    ) -> tuple[StoredRunTransition, ...]:
        self._validate_component(run_id)
        try:
            request_payload = self._artifacts.read_json(Path("runs") / run_id / "request.json")
        except ArtifactStoreError as error:
            raise RunNotFoundError(f"unknown run ID: {run_id}") from error
        request_hash = sha256_json(request_payload)
        paths = self._artifacts.list_json(Path("runs") / run_id / "transitions")
        stored: list[StoredRunTransition] = []
        previous_hash: str | None = None
        created_at: datetime | None = None
        for expected_sequence, path in enumerate(paths):
            payload = self._artifacts.read_json(path)
            try:
                transition = RunTransition.model_validate(payload)
            except (ValidationError, ValueError, TypeError) as error:
                raise InvalidRunHistoryError("run transition is invalid") from error
            content_hash = sha256_json(payload)
            manifest = transition.manifest
            created_at = manifest.created_at if created_at is None else created_at
            if (
                transition.run_id != run_id
                or transition.sequence != expected_sequence
                or transition.previous_transition_hash != previous_hash
                or transition.request_artifact_hash != request_hash
                or manifest.run_id != run_id
                or manifest.status is not _EVENT_STATUS[transition.event]
                or manifest.created_at != created_at
                or manifest.artifact_hash != request_hash
                or manifest.input_hash != request_hash
                or manifest.artifact_hashes.get("request") != request_hash
            ):
                raise InvalidRunHistoryError("run transition hash chain is disconnected")
            stored.append(StoredRunTransition(transition=transition, content_hash=content_hash))
            previous_hash = content_hash
        events = tuple(item.transition.event for item in stored)
        if allow_partial and events in {(), (RunTransitionEvent.REQUEST,)}:
            return tuple(stored)
        self._validate_event_chain(events)
        return tuple(stored)

    def reconcile_abandoned_runs(self) -> tuple[str, ...]:
        reconciled: list[str] = []
        with self._lock:
            for run_path in self._artifacts.list_directories("runs"):
                run_id = run_path.name
                try:
                    self._validate_component(run_id)
                    request = RunCreateRequest.model_validate(
                        self._artifacts.read_json(run_path / "request.json")
                    )
                except (ArtifactStoreError, ValidationError, TypeError, ValueError) as error:
                    raise InvalidRunHistoryError(
                        f"run {run_id!r} has an invalid request artifact"
                    ) from error
                history = self._load_transition_history(run_id, allow_partial=True)
                history = self._recover_partial_queue(run_id, request, history)
                latest = history[-1].transition
                if latest.event not in {RunTransitionEvent.QUEUED, RunTransitionEvent.RUNNING}:
                    continue
                try:
                    stored = self._append_failure(
                        run_id,
                        request,
                        RunFailureCode.ABANDONED_ON_RESTART,
                    )
                except TerminalRunError:
                    continue
                except ArtifactStoreError as error:
                    raise RunFailurePersistenceError(
                        "failed to persist restart failure transition"
                    ) from error
                if stored is not None:
                    reconciled.append(run_id)
        return tuple(reconciled)

    def _recover_partial_queue(
        self,
        run_id: str,
        request: RunCreateRequest,
        history: tuple[StoredRunTransition, ...],
    ) -> tuple[StoredRunTransition, ...]:
        request_payload = self._artifacts.read_json(Path("runs") / run_id / "request.json")
        request_hash = sha256_json(request_payload)
        if not history:
            created_at = self._aware_now()
            first_transition = self._make_transition(
                run_id=run_id,
                request=request,
                event=RunTransitionEvent.REQUEST,
                sequence=0,
                occurred_at=created_at,
                created_at=created_at,
                request_hash=request_hash,
                previous_hash=None,
                artifact_hashes={"request": request_hash},
            )
            try:
                self._write_transition(first_transition)
            except ArtifactExistsError:
                pass
            history = self._load_transition_history(run_id, allow_partial=True)
        if len(history) == 1:
            first_stored = history[0]
            queued = self._make_transition(
                run_id=run_id,
                request=request,
                event=RunTransitionEvent.QUEUED,
                sequence=1,
                occurred_at=self._aware_now(),
                created_at=first_stored.transition.manifest.created_at,
                request_hash=request_hash,
                previous_hash=first_stored.content_hash,
                artifact_hashes={
                    "request": request_hash,
                    "previous_transition": first_stored.content_hash,
                },
            )
            try:
                self._write_transition(queued)
            except ArtifactExistsError:
                pass
            history = self._load_transition_history(run_id, allow_partial=False)
        return history

    def list_public_problems(self) -> tuple[ProblemSummaryResponse, ...]:
        responses: list[ProblemSummaryResponse] = []
        for item in self._catalog.list_problems():
            self._get_formal_bundle(item.problem_id)
            responses.append(
                ProblemSummaryResponse(
                    problem_id=item.problem_id,
                    title=item.title,
                    topic=item.topic.value,
                    rating=item.rating,
                )
            )
        return tuple(responses)

    def get_public_problem(self, problem_id: str) -> dict[str, Any]:
        bundle = self._get_formal_bundle(problem_id)
        detail = self._catalog.get_public_detail(problem_id)
        protected = self._protected_literals(bundle)
        sanitized = self._sanitize_public(detail, protected)
        if not isinstance(sanitized, dict):  # pragma: no cover - catalog contract
            raise TypeError("public problem detail must be a mapping")
        return sanitized

    def _execute(
        self,
        run_id: str,
        request: RunCreateRequest,
        bundle: ProblemBundle,
    ) -> None:
        phase = "start"
        running_claim: StoredRunTransition | None = None
        try:
            running_claim = self._append_event(run_id, request, RunTransitionEvent.RUNNING)
            if running_claim is None:
                return
            phase = "generation"
            if request.mode is RunMode.SOLVE_AND_AUDIT:
                trace = self._generator.generate(bundle.record)
                if trace.problem_id != request.problem_id:
                    raise ValueError("generated trace identity mismatch")
            else:
                if request.trace is None:  # pragma: no cover - DTO invariant
                    raise ValueError("audit trace missing")
                trace = request.trace
            if not self._claim_is_current(run_id, running_claim.content_hash):
                return
            phase = "judge"
            judge_evidence = self._judge.judge(bundle.record, trace.code)
            if (
                judge_evidence.compile_status is JudgeStatus.INFRASTRUCTURE_ERROR
                or judge_evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
            ):
                raise InfrastructureEvidenceError("judge infrastructure unavailable")
            if not self._claim_is_current(run_id, running_claim.content_hash):
                return
            phase = "review"
            findings = self._rules.evaluate(trace)
            reviews = self._reviews.review(bundle.record, bundle.oracle, trace)
            audit = self._fusion.fuse(
                run_id=run_id,
                problem=bundle.record,
                trace=trace,
                judge=judge_evidence,
                rule_findings=findings,
                reviews=reviews,
            )
            if not self._claim_is_current(run_id, running_claim.content_hash):
                return
            phase = "artifact"
            self._complete(
                run_id,
                request,
                bundle,
                trace,
                audit,
                running_claim_hash=running_claim.content_hash,
            )
        except (TerminalRunError, TransitionConflictError):
            return
        except ArtifactStoreError:
            self._append_owned_failure(
                run_id,
                request,
                RunFailureCode.ARTIFACT_FAILURE,
                running_claim,
            )
        except InfrastructureEvidenceError:
            self._append_owned_failure(
                run_id,
                request,
                RunFailureCode.JUDGE_INFRASTRUCTURE,
                running_claim,
            )
        except Exception:
            code = {
                "generation": RunFailureCode.GENERATION_FAILED,
                "judge": RunFailureCode.JUDGE_INFRASTRUCTURE,
                "review": RunFailureCode.REVIEW_FAILED,
                "artifact": RunFailureCode.ARTIFACT_FAILURE,
            }.get(phase, RunFailureCode.INTERNAL_FAILURE)
            self._append_owned_failure(run_id, request, code, running_claim)

    def _complete(
        self,
        run_id: str,
        request: RunCreateRequest,
        bundle: ProblemBundle,
        trace: SolutionTrace,
        audit: AuditReport,
        *,
        running_claim_hash: str,
    ) -> None:
        if not self._claim_is_current(run_id, running_claim_hash):
            return
        internal_payload = InternalRunReport(
            run_id=run_id,
            problem_id=request.problem_id,
            mode=request.mode,
            trace=trace,
            audit_report=audit,
        ).model_dump(mode="json")
        internal_payload = cast(dict[str, Any], self._sanitize_credentials(internal_payload))
        internal_path = Path("runs") / run_id / "internal-report.json"
        internal_ref = self._artifacts.write_json(internal_path, internal_payload)
        protected = self._protected_literals(bundle)
        public = PublicRunReport(
            run_id=run_id,
            problem_id=request.problem_id,
            mode=request.mode,
            trace=PublicSolutionTrace.model_validate(
                self._sanitize_public(trace.model_dump(mode="json"), protected)
            ),
            audit=PublicAuditReport(
                run_id=audit.run_id,
                problem_id=audit.problem_id,
                trace_id=audit.trace_id,
                judge=PublicJudgeReport(
                    compile_status=audit.judge_evidence.compile_status,
                    verdict=audit.judge_evidence.verdict,
                    tests=tuple(
                        PublicJudgeTestResult(
                            test_number=number,
                            status=item.status,
                            time_ms=item.time_ms,
                            memory_kb=item.memory_kb,
                        )
                        for number, item in enumerate(audit.judge_evidence.tests, start=1)
                    ),
                ),
                final_correct=audit.final_correct,
                process_score=audit.process_score,
                process_valid=audit.process_valid,
                final_error_taxonomy=audit.final_error_taxonomy,
                first_material_error_step_id=audit.first_material_error_step_id,
                needs_human_review=audit.needs_human_review,
            ),
        )
        public_path = Path("runs") / run_id / "public-report.json"
        public_ref = self._artifacts.write_json(public_path, public.model_dump(mode="json"))
        self._append_event(
            run_id,
            request,
            RunTransitionEvent.COMPLETED,
            internal_report_path=str(internal_path),
            public_report_path=str(public_path),
            new_artifact_hashes={
                "internal_report": internal_ref.content_hash,
                "public_report": public_ref.content_hash,
            },
            expected_previous_hash=running_claim_hash,
        )

    def _append_owned_failure(
        self,
        run_id: str,
        request: RunCreateRequest,
        code: RunFailureCode,
        running_claim: StoredRunTransition | None,
    ) -> None:
        expected_hash = None if running_claim is None else running_claim.content_hash
        if expected_hash is not None and not self._claim_is_current(run_id, expected_hash):
            return
        try:
            self._append_failure(
                run_id,
                request,
                code,
                expected_previous_hash=expected_hash,
            )
        except (TerminalRunError, TransitionConflictError):
            return
        except ArtifactStoreError as error:
            raise RunFailurePersistenceError(
                "failed to persist terminal failure transition"
            ) from error

    def _append_failure(
        self,
        run_id: str,
        request: RunCreateRequest,
        code: RunFailureCode,
        *,
        expected_previous_hash: str | None = None,
    ) -> StoredRunTransition | None:
        return self._append_event(
            run_id,
            request,
            RunTransitionEvent.FAILED,
            failure=RunFailure(code=code, message=_SAFE_FAILURE_MESSAGES[code]),
            expected_previous_hash=expected_previous_hash,
        )

    def _append_event(
        self,
        run_id: str,
        request: RunCreateRequest,
        event: RunTransitionEvent,
        *,
        internal_report_path: str | None = None,
        public_report_path: str | None = None,
        new_artifact_hashes: Mapping[str, str] | None = None,
        failure: RunFailure | None = None,
        expected_previous_hash: str | None = None,
    ) -> StoredRunTransition | None:
        with self._lock:
            history = self.get_transition_history(run_id)
            latest = history[-1]
            latest_event = latest.transition.event
            if latest_event in {
                RunTransitionEvent.COMPLETED,
                RunTransitionEvent.FAILED,
            }:
                raise TerminalRunError(f"run is already terminal: {run_id}")
            if expected_previous_hash is not None and latest.content_hash != expected_previous_hash:
                return None
            if event not in _ALLOWED_NEXT.get(latest_event, frozenset()):
                raise TransitionConflictError(
                    f"cannot append {event.value} after {latest_event.value}"
                )
            artifact_hashes = dict(latest.transition.manifest.artifact_hashes)
            artifact_hashes["previous_transition"] = latest.content_hash
            artifact_hashes.update(new_artifact_hashes or {})
            transition = self._make_transition(
                run_id=run_id,
                request=request,
                event=event,
                sequence=len(history),
                occurred_at=self._aware_now(),
                created_at=history[0].transition.manifest.created_at,
                request_hash=latest.transition.request_artifact_hash,
                previous_hash=latest.content_hash,
                artifact_hashes=artifact_hashes,
                internal_report_path=internal_report_path,
                public_report_path=public_report_path,
                failure=failure,
            )
            try:
                ref = self._write_transition(transition)
            except ArtifactExistsError:
                competing_history = self.get_transition_history(run_id)
                if competing_history[-1].transition.sequence >= transition.sequence:
                    return None
                raise
            return StoredRunTransition(
                transition=transition,
                content_hash=ref.content_hash,
            )

    def _claim_is_current(self, run_id: str, claim_hash: str) -> bool:
        latest = self.get_transition_history(run_id)[-1]
        return (
            latest.transition.event is RunTransitionEvent.RUNNING
            and latest.content_hash == claim_hash
        )

    def _make_transition(
        self,
        *,
        run_id: str,
        request: RunCreateRequest,
        event: RunTransitionEvent,
        sequence: int,
        occurred_at: datetime,
        created_at: datetime,
        request_hash: str,
        previous_hash: str | None,
        artifact_hashes: Mapping[str, str],
        internal_report_path: str | None = None,
        public_report_path: str | None = None,
        failure: RunFailure | None = None,
    ) -> RunTransition:
        config_payload = {
            "model_name": self._model_name,
            "prompt_version": self._prompt_version,
            "model_parameters": self._model_parameters,
            "code_revision": self._code_revision,
            "container_image_digest": self._container_image_digest,
        }
        manifest = RunManifest(
            run_id=run_id,
            status=_EVENT_STATUS[event],
            created_at=created_at,
            updated_at=occurred_at,
            config_hash=sha256_json(config_payload),
            problem_ids=(request.problem_id,),
            artifact_hash=request_hash,
            artifact_hashes=artifact_hashes,
            model_name=self._model_name,
            prompt_version=self._prompt_version,
            model_parameters=self._model_parameters,
            input_hash=request_hash,
            code_revision=self._code_revision,
            container_image_digest=self._container_image_digest,
        )
        return RunTransition(
            run_id=run_id,
            sequence=sequence,
            event=event,
            occurred_at=occurred_at,
            previous_transition_hash=previous_hash,
            request_artifact_hash=request_hash,
            manifest=manifest,
            internal_report_path=internal_report_path,
            public_report_path=public_report_path,
            failure=failure,
        )

    def _write_transition(self, transition: RunTransition) -> ArtifactRef:
        path = Path("runs") / transition.run_id / "transitions" / f"{transition.sequence:06d}.json"
        return self._artifacts.write_json(path, transition.model_dump(mode="json"))

    def _get_formal_bundle(self, problem_id: str) -> ProblemBundle:
        try:
            bundle = self._catalog.get_bundle(problem_id)
        except KeyError as error:
            raise ProblemNotFoundError(f"unknown formal problem ID: {problem_id}") from error
        if not isinstance(bundle, ProblemBundle) or bundle.formal_selection_eligible is not True:
            raise ProblemNotFoundError(f"problem is not a formal catalog entry: {problem_id}")
        return bundle

    def _new_run_id(self) -> str:
        run_id = self._id_factory()
        self._validate_component(run_id)
        return run_id

    @staticmethod
    def _validate_component(value: str) -> None:
        if not _SAFE_COMPONENT.fullmatch(value):
            raise ValueError("run ID must be a safe opaque identifier")

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("run clock must return timezone-aware timestamps")
        return value

    @staticmethod
    def _validate_event_chain(events: tuple[RunTransitionEvent, ...]) -> None:
        if len(events) < 2 or events[:2] != (
            RunTransitionEvent.REQUEST,
            RunTransitionEvent.QUEUED,
        ):
            raise InvalidRunHistoryError("run transition chain must begin request -> queued")
        for previous, current in zip(events[1:], events[2:]):
            if current not in _ALLOWED_NEXT.get(previous, frozenset()):
                raise InvalidRunHistoryError("run transition event order is invalid")

    @staticmethod
    def _protected_literals(bundle: ProblemBundle) -> tuple[str, ...]:
        normalized: set[str] = set()

        def add(value: str) -> None:
            compact = " ".join(value.split()).casefold()
            if compact:
                normalized.add(compact)

        add(bundle.reference_cpp)
        for line in bundle.reference_cpp.splitlines():
            if len(line.strip()) >= 12 and not line.lstrip().startswith("#include"):
                add(line)
        for test in (*bundle.record.hidden_tests, *bundle.record.generated_tests):
            add(test.test_id)
            add(test.input_data)
            add(test.expected_output)

        oracle_values: list[str] = []

        def collect_oracle(value: Any) -> None:
            if isinstance(value, str):
                oracle_values.append(" ".join(value.split()).casefold())
            elif isinstance(value, Mapping):
                for item in value.values():
                    collect_oracle(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect_oracle(item)

        collect_oracle(
            bundle.oracle.model_dump(mode="json", exclude={"schema_version", "problem_id"})
        )
        for value in oracle_values:
            words = value.split()
            if len(words) <= 1:
                if len(value) >= 16:
                    add(value)
                continue
            for width in range(2, len(words) + 1):
                for start in range(len(words) - width + 1):
                    add(" ".join(words[start : start + width]))
        return tuple(sorted(normalized, key=len, reverse=True))

    @classmethod
    def _sanitize_credentials(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: cls._sanitize_credentials(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._sanitize_credentials(item) for item in value]
        if isinstance(value, tuple):
            return [cls._sanitize_credentials(item) for item in value]
        if isinstance(value, str):
            result = value
            for pattern in _CREDENTIAL_PATTERNS:
                result = pattern.sub("[REDACTED]", result)
            return result
        return value

    @classmethod
    def _sanitize_public(cls, value: Any, protected: tuple[str, ...]) -> Any:
        if isinstance(value, Mapping):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized = key.casefold() if isinstance(key, str) else str(key).casefold()
                if any(part in normalized for part in _PROTECTED_KEY_PARTS):
                    continue
                sanitized[str(key)] = cls._sanitize_public(item, protected)
            return sanitized
        if isinstance(value, (list, tuple)):
            return [cls._sanitize_public(item, protected) for item in value]
        if isinstance(value, str):
            result = cast(str, cls._sanitize_credentials(value))
            for pattern, replacement in _PUBLIC_PATH_PATTERNS:
                result = pattern.sub(replacement, result)
            for literal in protected:
                words = literal.split()
                if not words:
                    continue
                expression = r"\s+".join(re.escape(word) for word in words)
                if words[0][0].isalnum():
                    expression = rf"(?<!\w){expression}"
                if words[-1][-1].isalnum():
                    expression = rf"{expression}(?!\w)"
                result = re.sub(expression, "[REDACTED]", result, flags=re.IGNORECASE)
            return result
        return value
