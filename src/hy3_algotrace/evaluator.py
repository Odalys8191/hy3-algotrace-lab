"""Independent reviewer orchestration and precedence-ordered evidence fusion."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from .contracts import (
    AuditReport,
    ErrorTaxonomy,
    JudgeEvidence,
    JudgeStatus,
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReviewerVerdict,
    SolutionTrace,
    StepReview,
    StepStatus,
)
from .rules import RuleFinding

DIMENSION_WEIGHTS: Mapping[ReasoningStage, int] = MappingProxyType(
    {
        ReasoningStage.PROBLEM_UNDERSTANDING: 20,
        ReasoningStage.ALGORITHM_DESIGN: 25,
        ReasoningStage.CORRECTNESS_ARGUMENT: 20,
        ReasoningStage.COMPLEXITY_ANALYSIS: 10,
        ReasoningStage.IMPLEMENTATION: 10,
        ReasoningStage.EDGE_CASES: 15,
    }
)


class InfrastructureEvidenceError(RuntimeError):
    """Execution evidence is unavailable and must not become a process taxonomy."""


def is_paradox(report: AuditReport) -> bool:
    """Return whether accepted code was produced by a materially invalid process."""

    return report.final_correct and not report.process_valid


class ReviewerClient(Protocol):
    def review(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        *,
        reviewer_id: str,
    ) -> ReviewerVerdict: ...

    def arbitrate(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        primary: tuple[ReviewerVerdict, ReviewerVerdict],
    ) -> ReviewerVerdict: ...


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    primary: tuple[ReviewerVerdict, ReviewerVerdict]
    arbiter: ReviewerVerdict | None = None
    material_disagreement: bool = False
    unresolved: bool = False


def _verdict_signature(
    verdict: ReviewerVerdict,
) -> tuple[
    bool,
    ErrorTaxonomy | None,
    str | None,
    tuple[tuple[str, StepStatus, ErrorTaxonomy | None], ...],
]:
    material_steps = tuple(
        sorted(
            (
                (review.step_id, review.status, review.taxonomy)
                for review in verdict.per_step_reviews
                if review.material
            ),
            key=lambda item: item[0],
        )
    )
    return (
        verdict.material_error,
        verdict.error_taxonomy,
        verdict.first_error_step_id,
        material_steps,
    )


class ReviewOrchestrator:
    """Run isolated reviewers and involve an arbiter only for material disagreement."""

    def __init__(self, client: ReviewerClient) -> None:
        self._client = client

    def review(
        self, problem: ProblemRecord, oracle: ProblemOracle, trace: SolutionTrace
    ) -> ReviewOutcome:
        logic = self._client.review(
            problem, oracle, trace, reviewer_id="logic-reviewer"
        )
        adversarial = self._client.review(
            problem, oracle, trace, reviewer_id="adversarial-reviewer"
        )
        primary = (logic, adversarial)
        disagreement = _verdict_signature(logic) != _verdict_signature(adversarial)
        if not disagreement:
            return ReviewOutcome(primary=primary)
        arbiter = self._client.arbitrate(problem, oracle, trace, primary)
        primary_signatures = {_verdict_signature(verdict) for verdict in primary}
        unresolved = _verdict_signature(arbiter) not in primary_signatures
        return ReviewOutcome(
            primary=primary,
            arbiter=arbiter,
            material_disagreement=True,
            unresolved=unresolved,
        )


@dataclass(frozen=True, slots=True)
class MaterialError:
    step_id: str
    taxonomy: ErrorTaxonomy


def _material_step_ids(
    evidence: Iterable[StepReview | RuleFinding | MaterialError],
) -> set[str]:
    step_ids: set[str] = set()
    for item in evidence:
        if isinstance(item, MaterialError):
            step_ids.add(item.step_id)
        elif isinstance(item, RuleFinding):
            if item.material and item.step_id is not None:
                step_ids.add(item.step_id)
        elif item.material and item.status in {StepStatus.UNSUPPORTED, StepStatus.INCORRECT}:
            step_ids.add(item.step_id)
    return step_ids


def localize_root_error(
    trace: SolutionTrace,
    evidence: Iterable[StepReview | RuleFinding | MaterialError],
) -> str | None:
    """Choose the earliest material candidate not downstream of another candidate."""

    candidates = _material_step_ids(evidence)
    steps = {step.step_id: step for step in trace.steps}
    candidates &= steps.keys()

    def has_candidate_ancestor(step_id: str, visited: set[str]) -> bool:
        for dependency in steps[step_id].depends_on:
            if dependency in candidates:
                return True
            if dependency not in visited:
                visited.add(dependency)
                if has_candidate_ancestor(dependency, visited):
                    return True
        return False

    roots = tuple(
        steps[step_id]
        for step_id in candidates
        if not has_candidate_ancestor(step_id, {step_id})
    )
    if not roots:
        return None
    return min(roots, key=lambda step: step.step_number).step_id


def score_process(trace: SolutionTrace, material_step_ids: Iterable[str]) -> float:
    """Deduct each affected reasoning dimension exactly once."""

    steps = {step.step_id: step for step in trace.steps}
    affected_stages = {
        steps[step_id].stage for step_id in set(material_step_ids) if step_id in steps
    }
    return float(100 - sum(DIMENSION_WEIGHTS[stage] for stage in affected_stages))


class EvidenceFusion:
    """Fuse execution, rules, reviewer consensus, then arbiter evidence in that order."""

    def fuse(
        self,
        *,
        run_id: str,
        problem: ProblemRecord,
        trace: SolutionTrace,
        judge: JudgeEvidence,
        rule_findings: Sequence[RuleFinding],
        reviews: ReviewOutcome,
    ) -> AuditReport:
        self._require_execution_evidence(judge)
        reviewer_verdicts = (
            reviews.primary
            if reviews.arbiter is None
            else (*reviews.primary, reviews.arbiter)
        )

        material_rules = tuple(finding for finding in rule_findings if finding.material)
        if material_rules:
            root = localize_root_error(trace, material_rules) or trace.steps[0].step_id
            taxonomy = next(
                (
                    finding.taxonomy
                    for finding in material_rules
                    if finding.step_id == root
                ),
                material_rules[0].taxonomy,
            )
            material_steps = tuple(
                finding.step_id for finding in material_rules if finding.step_id is not None
            ) or (root,)
            return self._report(
                run_id=run_id,
                problem=problem,
                trace=trace,
                judge=judge,
                reviewer_verdicts=reviewer_verdicts,
                taxonomy=taxonomy,
                root=root,
                material_steps=material_steps,
                needs_human_review=False,
            )

        selected = self._review_evidence(reviews)
        material_reviews = tuple(
            review
            for verdict in selected
            for review in verdict.per_step_reviews
            if review.material
            and review.status in {StepStatus.UNSUPPORTED, StepStatus.INCORRECT}
        )
        if not material_reviews:
            return AuditReport(
                run_id=run_id,
                problem_id=problem.problem_id,
                trace_id=trace.trace_id,
                judge_evidence=judge,
                reviewer_verdicts=reviewer_verdicts,
                final_correct=judge.verdict is JudgeStatus.AC,
                process_score=100.0,
                process_valid=True,
                needs_human_review=(
                    reviews.unresolved or judge.verdict is not JudgeStatus.AC
                ),
            )
        root = localize_root_error(trace, material_reviews) or trace.steps[0].step_id
        taxonomy = next(
            review.taxonomy
            for review in material_reviews
            if review.step_id == root and review.taxonomy is not None
        )
        return self._report(
            run_id=run_id,
            problem=problem,
            trace=trace,
            judge=judge,
            reviewer_verdicts=reviewer_verdicts,
            taxonomy=taxonomy,
            root=root,
            material_steps=tuple(review.step_id for review in material_reviews),
            needs_human_review=reviews.unresolved,
        )

    @staticmethod
    def _review_evidence(reviews: ReviewOutcome) -> tuple[ReviewerVerdict, ...]:
        if reviews.material_disagreement:
            if reviews.arbiter is not None:
                return (reviews.arbiter,)
            return reviews.primary
        return (reviews.primary[0],)

    @staticmethod
    def _require_execution_evidence(judge: JudgeEvidence) -> None:
        unavailable = {JudgeStatus.NOT_RUN, JudgeStatus.INFRASTRUCTURE_ERROR}
        if judge.compile_status in unavailable or judge.verdict in unavailable:
            raise InfrastructureEvidenceError(
                "judge infrastructure did not produce authoritative execution evidence"
            )
        supported = {
            JudgeStatus.AC,
            JudgeStatus.WA,
            JudgeStatus.COMPILE_ERROR,
            JudgeStatus.RUNTIME_ERROR,
            JudgeStatus.TLE,
            JudgeStatus.MLE,
            JudgeStatus.OUTPUT_LIMIT,
        }
        if judge.verdict not in supported:
            raise InfrastructureEvidenceError("unsupported judge infrastructure verdict")

    @staticmethod
    def _report(
        *,
        run_id: str,
        problem: ProblemRecord,
        trace: SolutionTrace,
        judge: JudgeEvidence,
        reviewer_verdicts: tuple[ReviewerVerdict, ...],
        taxonomy: ErrorTaxonomy,
        root: str,
        material_steps: Iterable[str],
        needs_human_review: bool,
    ) -> AuditReport:
        return AuditReport(
            run_id=run_id,
            problem_id=problem.problem_id,
            trace_id=trace.trace_id,
            judge_evidence=judge,
            reviewer_verdicts=reviewer_verdicts,
            final_correct=judge.verdict is JudgeStatus.AC,
            process_score=score_process(trace, material_steps),
            process_valid=False,
            final_error_taxonomy=taxonomy,
            first_material_error_step_id=root,
            needs_human_review=needs_human_review,
        )
