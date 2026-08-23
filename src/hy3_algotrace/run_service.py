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
    PublicRunReport,
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
from .artifacts import ArtifactRef, ArtifactStore, ArtifactStoreError, sha256_json
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
    re.compile(r"(?i)\b(?:api[_-]?key|authorization)\s*[:=]\s*[^\s,;\"']+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
)
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9._-])/(?:[^/\s]+/)+[^\s,;\"']*")
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
_SAFE_FAILURE_MESSAGES: Mapping[RunFailureCode, str] = {
    RunFailureCode.GENERATION_FAILED: "solution generation failed",
    RunFailureCode.JUDGE_INFRASTRUCTURE: "judge infrastructure failed",
    RunFailureCode.REVIEW_FAILED: "review or arbitration failed",
    RunFailureCode.ARTIFACT_FAILURE: "immutable artifact persistence failed",
    RunFailureCode.ABANDONED_ON_RESTART: "active run was abandoned on restart",
    RunFailureCode.EXECUTOR_FAILURE: "background executor rejected the run",
    RunFailureCode.INTERNAL_FAILURE: "run orchestration failed",
}


class ProblemNotFoundError(KeyError):
    """The requested identifier is not a formal catalog entry."""


class RunNotFoundError(KeyError):
    """The requested run has no immutable index artifact."""


class InvalidRunHistoryError(RuntimeError):
    """An immutable transition chain is missing, malformed, or disconnected."""


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
            first = self._make_transition(
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
            first_ref = self._write_transition(first)
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
            self._executor.submit(lambda: self._execute(run_id, request, bundle))
        except Exception:
            self._append_failure(run_id, request, RunFailureCode.EXECUTOR_FAILURE)
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
        self._validate_component(run_id)
        index_path = Path("run-index") / f"{run_id}.json"
        try:
            index_payload = self._artifacts.read_json(index_path)
        except ArtifactStoreError as error:
            raise RunNotFoundError(f"unknown run ID: {run_id}") from error
        if not isinstance(index_payload, Mapping) or index_payload.get("run_id") != run_id:
            raise InvalidRunHistoryError("run index identity is invalid")
        request_payload = self._artifacts.read_json(Path("runs") / run_id / "request.json")
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
        self._validate_event_chain(tuple(item.transition.event for item in stored))
        return tuple(stored)

    def reconcile_abandoned_runs(self) -> tuple[str, ...]:
        reconciled: list[str] = []
        with self._lock:
            for index_path in self._artifacts.list_json("run-index"):
                payload = self._artifacts.read_json(index_path)
                if not isinstance(payload, Mapping) or not isinstance(payload.get("run_id"), str):
                    raise InvalidRunHistoryError("run index artifact is invalid")
                run_id = payload["run_id"]
                history = self.get_transition_history(run_id)
                latest = history[-1].transition
                if latest.event not in {RunTransitionEvent.QUEUED, RunTransitionEvent.RUNNING}:
                    continue
                request = RunCreateRequest.model_validate(
                    self._artifacts.read_json(Path("runs") / run_id / "request.json")
                )
                self._append_failure(
                    run_id,
                    request,
                    RunFailureCode.ABANDONED_ON_RESTART,
                )
                reconciled.append(run_id)
        return tuple(reconciled)

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
        try:
            self._append_event(run_id, request, RunTransitionEvent.RUNNING)
            phase = "generation"
            if request.mode is RunMode.SOLVE_AND_AUDIT:
                trace = self._generator.generate(bundle.record)
                if trace.problem_id != request.problem_id:
                    raise ValueError("generated trace identity mismatch")
            else:
                if request.trace is None:  # pragma: no cover - DTO invariant
                    raise ValueError("audit trace missing")
                trace = request.trace
            phase = "judge"
            judge_evidence = self._judge.judge(bundle.record, trace.code)
            if (
                judge_evidence.compile_status is JudgeStatus.INFRASTRUCTURE_ERROR
                or judge_evidence.verdict is JudgeStatus.INFRASTRUCTURE_ERROR
            ):
                raise InfrastructureEvidenceError("judge infrastructure unavailable")
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
            phase = "artifact"
            self._complete(run_id, request, bundle, trace, audit)
        except ArtifactStoreError:
            self._append_failure(run_id, request, RunFailureCode.ARTIFACT_FAILURE)
        except InfrastructureEvidenceError:
            self._append_failure(run_id, request, RunFailureCode.JUDGE_INFRASTRUCTURE)
        except Exception:
            code = {
                "generation": RunFailureCode.GENERATION_FAILED,
                "judge": RunFailureCode.JUDGE_INFRASTRUCTURE,
                "review": RunFailureCode.REVIEW_FAILED,
                "artifact": RunFailureCode.ARTIFACT_FAILURE,
            }.get(phase, RunFailureCode.INTERNAL_FAILURE)
            self._append_failure(run_id, request, code)

    def _complete(
        self,
        run_id: str,
        request: RunCreateRequest,
        bundle: ProblemBundle,
        trace: SolutionTrace,
        audit: AuditReport,
    ) -> None:
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
            trace=cast(
                dict[str, Any],
                self._sanitize_public(trace.model_dump(mode="json"), protected),
            ),
            audit=cast(
                dict[str, Any],
                self._sanitize_public(audit.model_dump(mode="json"), protected),
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
        )

    def _append_failure(
        self,
        run_id: str,
        request: RunCreateRequest,
        code: RunFailureCode,
    ) -> None:
        self._append_event(
            run_id,
            request,
            RunTransitionEvent.FAILED,
            failure=RunFailure(code=code, message=_SAFE_FAILURE_MESSAGES[code]),
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
    ) -> None:
        with self._lock:
            history = self.get_transition_history(run_id)
            latest = history[-1]
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
            self._write_transition(transition)

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
        path = (
            Path("runs")
            / transition.run_id
            / "transitions"
            / f"{transition.sequence:06d}-{transition.event.value}.json"
        )
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
        allowed = {
            RunTransitionEvent.QUEUED: {
                RunTransitionEvent.RUNNING,
                RunTransitionEvent.FAILED,
            },
            RunTransitionEvent.RUNNING: {
                RunTransitionEvent.COMPLETED,
                RunTransitionEvent.FAILED,
            },
        }
        for previous, current in zip(events[1:], events[2:]):
            if current not in allowed.get(previous, set()):
                raise InvalidRunHistoryError("run transition event order is invalid")

    @staticmethod
    def _protected_literals(bundle: ProblemBundle) -> tuple[str, ...]:
        values: list[str] = [bundle.reference_cpp]

        def collect(value: Any) -> None:
            if isinstance(value, str) and value:
                values.append(value)
            elif isinstance(value, Mapping):
                for item in value.values():
                    collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)

        for test in (*bundle.record.hidden_tests, *bundle.record.generated_tests):
            collect(test.test_id)
            collect(test.input_data)
            collect(test.expected_output)
        collect(
            bundle.oracle.model_dump(
                mode="json",
                exclude={"schema_version", "problem_id"},
            )
        )
        return tuple(sorted(set(values), key=len, reverse=True))

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
            for literal in protected:
                result = result.replace(literal, "[REDACTED]")
            return _ABSOLUTE_PATH.sub("[REDACTED_PATH]", result)
        return value
