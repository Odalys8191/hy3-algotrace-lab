"""HTTP-only Streamlit client for the four public Task-5 routes."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from .api_models import (
    ProblemDetailResponse,
    ProblemListResponse,
    RunAcceptedResponse,
    RunCreateRequest,
    RunMode,
    RunReadResponse,
)
from .benchmark_models import UiJudgeTest, UiRunView, UiTimelineStep
from .contracts import RunStatus, SolutionTrace


class AuditTraceInputError(ValueError):
    """Safe user-facing error for pasted structured trace input."""


RUN_MODE_LABELS: Mapping[str, RunMode] = MappingProxyType(
    {
        "Hy3 生成并审计": RunMode.SOLVE_AND_AUDIT,
        "粘贴结构化解答审计": RunMode.AUDIT,
    }
)


def build_run_request(
    *,
    mode: RunMode,
    problem_id: str,
    structured_trace_json: str | None = None,
) -> RunCreateRequest:
    """Build either supported request mode without bypassing strict DTO parsing."""

    if mode is RunMode.SOLVE_AND_AUDIT:
        return RunCreateRequest(mode=mode, problem_id=problem_id)
    if structured_trace_json is None or not structured_trace_json.strip():
        raise AuditTraceInputError("Paste a valid SolutionTrace JSON document.")
    try:
        payload = json.loads(structured_trace_json)
        trace = SolutionTrace.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as error:
        raise AuditTraceInputError(
            "Paste a valid SolutionTrace JSON document."
        ) from error
    if trace.problem_id != problem_id:
        raise AuditTraceInputError("SolutionTrace must match the selected problem.")
    return RunCreateRequest(mode=mode, problem_id=problem_id, trace=trace)


def should_offer_refresh(response: RunReadResponse) -> bool:
    return response.status in {RunStatus.QUEUED, RunStatus.RUNNING}


class AlgoTraceApiClient:
    """Small strict DTO client; it has no filesystem or service-layer access."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout_seconds)

    def list_problems(self) -> ProblemListResponse:
        response = self._client.get(f"{self._base_url}/api/v1/problems")
        response.raise_for_status()
        return ProblemListResponse.model_validate(response.json())

    def get_problem(self, problem_id: str) -> ProblemDetailResponse:
        response = self._client.get(
            f"{self._base_url}/api/v1/problems/{quote(problem_id, safe='')}"
        )
        response.raise_for_status()
        return ProblemDetailResponse.model_validate(response.json())

    def create_run(self, request: RunCreateRequest) -> RunAcceptedResponse:
        response = self._client.post(
            f"{self._base_url}/api/v1/runs",
            json=request.model_dump(mode="json"),
        )
        response.raise_for_status()
        return RunAcceptedResponse.model_validate(response.json())

    def get_run(self, run_id: str) -> RunReadResponse:
        response = self._client.get(
            f"{self._base_url}/api/v1/runs/{quote(run_id, safe='')}"
        )
        response.raise_for_status()
        return RunReadResponse.model_validate(response.json())

    def poll_run(self, run_id: str, *, max_polls: int) -> RunReadResponse:
        if max_polls < 1:
            raise ValueError("max_polls must be positive")
        result: RunReadResponse | None = None
        for _ in range(max_polls):
            result = self.get_run(run_id)
            if result.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
                return result
        assert result is not None
        return result


def build_run_view(response: RunReadResponse) -> UiRunView:
    """Project a strict API response into deterministic UI display data."""

    if response.report is None:
        failure = response.failure or response.degraded_failure
        return UiRunView(
            run_id=response.run_id,
            status=response.status,
            timeline=(),
            judge_tests=(),
            failure_message=failure.message if failure is not None else None,
        )
    trace = response.report.trace
    audit = response.report.audit
    return UiRunView(
        run_id=response.run_id,
        status=response.status,
        timeline=tuple(
            UiTimelineStep(
                step_id=step.step_id,
                step_number=step.step_number,
                stage=step.stage,
                claim=step.claim,
                rationale=step.rationale,
                status=step.status,
            )
            for step in sorted(trace.steps, key=lambda item: item.step_number)
        ),
        code=trace.code,
        judge_verdict=audit.judge.verdict,
        judge_tests=tuple(
            UiJudgeTest(
                test_number=test.test_number,
                status=test.status,
                time_ms=test.time_ms,
                memory_kb=test.memory_kb,
            )
            for test in audit.judge.tests
        ),
        first_error_step_id=audit.first_material_error_step_id,
        taxonomy=audit.final_error_taxonomy,
        process_score=audit.process_score,
        needs_human_review=audit.needs_human_review,
    )


def main() -> None:  # pragma: no cover - Streamlit runtime owns the event loop
    import streamlit as st

    st.title("Hy3 AlgoTrace Lab")
    base_url = st.sidebar.text_input("API base URL", "http://127.0.0.1:8000")
    client = AlgoTraceApiClient(base_url)
    try:
        listing = client.list_problems()
    except httpx.HTTPError as error:
        st.error(f"API unavailable: {error}")
        return
    by_label = {
        f"{problem.title} · {problem.rating}": problem.problem_id
        for problem in listing.problems
    }
    selected_label = st.selectbox("Built-in problem", tuple(by_label))
    selected_id = by_label[selected_label]
    detail = client.get_problem(selected_id)
    st.subheader(detail.title)
    st.write(detail.statement_en)
    mode_label = st.radio("Run mode", tuple(RUN_MODE_LABELS), horizontal=True)
    mode = RUN_MODE_LABELS[mode_label]
    structured_trace_json = None
    if mode is RunMode.AUDIT:
        structured_trace_json = st.text_area(
            "SolutionTrace JSON",
            height=280,
            placeholder='{"schema_version":"1.2", ...}',
        )
    if st.button("Launch audit"):
        try:
            request = build_run_request(
                mode=mode,
                problem_id=selected_id,
                structured_trace_json=structured_trace_json,
            )
        except AuditTraceInputError as error:
            st.error(str(error))
        else:
            accepted = client.create_run(request)
            st.session_state["run_id"] = accepted.run_id
    run_id = st.session_state.get("run_id")
    if run_id is None:
        return
    response = client.poll_run(run_id, max_polls=1)
    view = build_run_view(response)
    st.write(f"Status: {view.status.value}")
    if should_offer_refresh(response) and st.button("Refresh run status"):
        st.rerun()
    if view.failure_message is not None:
        st.error(view.failure_message)
    for step in view.timeline:
        with st.expander(f"{step.step_number}. {step.stage.value} · {step.status.value}"):
            st.write(step.claim)
            st.write(step.rationale)
    if view.code is not None:
        st.code(view.code, language="cpp")
    if view.judge_verdict is not None:
        st.write(f"Judge verdict: {view.judge_verdict.value}")
        st.dataframe([item.model_dump(mode="json") for item in view.judge_tests])
        st.write(f"First material error: {view.first_error_step_id or 'none'}")
        st.write(f"Taxonomy: {view.taxonomy.value if view.taxonomy else 'none'}")
        st.write(f"Process score: {view.process_score}")
        st.write(f"Needs human review: {view.needs_human_review}")


if __name__ == "__main__":  # pragma: no cover
    main()
