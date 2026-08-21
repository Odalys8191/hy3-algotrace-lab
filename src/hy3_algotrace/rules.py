"""Deterministic, conservative consistency checks for solution traces."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from .contracts import ErrorTaxonomy, ReasoningStage, SolutionTrace


class RuleSignal(StrEnum):
    """Stable rule signals with a one-to-one process taxonomy mapping."""

    PROBLEM_MISREAD = "problem_misread"
    CONSTRAINT_OMISSION = "constraint_omission"
    ALGORITHM_LOGIC = "algorithm_logic"
    PROOF_GAP_CIRCULARITY = "proof_gap_circularity"
    COMPLEXITY_ERROR = "complexity_error"
    BOUNDARY_ERROR = "boundary_error"
    IMPLEMENTATION_ERROR = "implementation_error"
    HALLUCINATION = "hallucination"
    FORMAT_SCHEMA = "format_schema"


SIGNAL_TAXONOMY: Mapping[RuleSignal, ErrorTaxonomy] = {
    RuleSignal.PROBLEM_MISREAD: ErrorTaxonomy.PROBLEM_MISREAD,
    RuleSignal.CONSTRAINT_OMISSION: ErrorTaxonomy.CONSTRAINT_OMISSION,
    RuleSignal.ALGORITHM_LOGIC: ErrorTaxonomy.ALGORITHM_LOGIC,
    RuleSignal.PROOF_GAP_CIRCULARITY: ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
    RuleSignal.COMPLEXITY_ERROR: ErrorTaxonomy.COMPLEXITY_ERROR,
    RuleSignal.BOUNDARY_ERROR: ErrorTaxonomy.BOUNDARY_ERROR,
    RuleSignal.IMPLEMENTATION_ERROR: ErrorTaxonomy.IMPLEMENTATION_ERROR,
    RuleSignal.HALLUCINATION: ErrorTaxonomy.HALLUCINATION,
    RuleSignal.FORMAT_SCHEMA: ErrorTaxonomy.FORMAT_SCHEMA,
}


@dataclass(frozen=True, slots=True)
class RuleFinding:
    signal: RuleSignal
    taxonomy: ErrorTaxonomy
    step_id: str | None
    evidence: str
    material: bool = True


class RuleEngine:
    """Produce reproducible findings without interpreting model confidence."""

    def classify_signal(
        self,
        signal: RuleSignal,
        *,
        step_id: str | None,
        evidence: str,
        material: bool = True,
    ) -> RuleFinding:
        return RuleFinding(
            signal=signal,
            taxonomy=SIGNAL_TAXONOMY[signal],
            step_id=step_id,
            evidence=evidence,
            material=material,
        )

    def evaluate(self, value: SolutionTrace | Mapping[str, Any]) -> tuple[RuleFinding, ...]:
        try:
            trace = (
                value
                if isinstance(value, SolutionTrace)
                else SolutionTrace.model_validate(value)
            )
        except (ValidationError, ValueError, TypeError) as error:
            return (
                self.classify_signal(
                    RuleSignal.FORMAT_SCHEMA,
                    step_id=None,
                    evidence=f"SolutionTrace schema validation failed: {error}",
                ),
            )

        findings: list[RuleFinding] = []
        number_by_id = {step.step_id: step.step_number for step in trace.steps}
        for step in trace.steps:
            later_dependencies = tuple(
                dependency
                for dependency in step.depends_on
                if number_by_id[dependency] >= step.step_number
            )
            if later_dependencies:
                findings.append(
                    self.classify_signal(
                        RuleSignal.ALGORITHM_LOGIC,
                        step_id=step.step_id,
                        evidence=(
                            f"step {step.step_id} depends on non-earlier step(s): "
                            f"{', '.join(later_dependencies)}"
                        ),
                    )
                )

        required_explanations = (
            (
                trace.problem_understanding,
                RuleSignal.PROBLEM_MISREAD,
                ReasoningStage.PROBLEM_UNDERSTANDING,
                "problem understanding is blank",
            ),
            (
                trace.algorithm,
                RuleSignal.ALGORITHM_LOGIC,
                ReasoningStage.ALGORITHM_DESIGN,
                "algorithm explanation is blank",
            ),
            (
                trace.correctness_argument,
                RuleSignal.PROOF_GAP_CIRCULARITY,
                ReasoningStage.CORRECTNESS_ARGUMENT,
                "correctness argument is blank",
            ),
            (
                "".join(trace.edge_cases),
                RuleSignal.BOUNDARY_ERROR,
                ReasoningStage.EDGE_CASES,
                "edge-case explanation is blank",
            ),
            (
                trace.code,
                RuleSignal.IMPLEMENTATION_ERROR,
                ReasoningStage.IMPLEMENTATION,
                "implementation is blank",
            ),
        )
        for content, signal, stage, evidence in required_explanations:
            if not content.strip():
                findings.append(
                    self.classify_signal(
                        signal,
                        step_id=self._first_step_id(trace, stage),
                        evidence=evidence,
                    )
                )

        if not trace.time_complexity.strip() or not trace.space_complexity.strip():
            findings.append(
                self.classify_signal(
                    RuleSignal.COMPLEXITY_ERROR,
                    step_id=self._first_step_id(
                        trace, ReasoningStage.COMPLEXITY_ANALYSIS
                    ),
                    evidence="time or space complexity explanation is blank",
                )
            )

        normalized_time = re.sub(r"\s+", "", trace.time_complexity.lower())
        variable_bound_loop = re.search(
            r"\bfor\s*\([^;]*;[^;]*[<>]=?\s*[A-Za-z_]\w*",
            trace.code,
        ) or re.search(r"\bwhile\s*\([^)]*[A-Za-z_]\w*", trace.code)
        if normalized_time in {"o(1)", "theta(1)", "θ(1)"} and variable_bound_loop:
            findings.append(
                self.classify_signal(
                    RuleSignal.COMPLEXITY_ERROR,
                    step_id=self._first_step_id(trace, ReasoningStage.COMPLEXITY_ANALYSIS),
                    evidence="declared constant time conflicts with an explicit loop in code",
                )
            )

        edge_text = " ".join(trace.edge_cases).lower()
        division = re.search(r"(?<!/)/(?![/=*])", trace.code)
        if division and not any(term in edge_text for term in ("zero", "nonzero", "divisor")):
            findings.append(
                self.classify_signal(
                    RuleSignal.BOUNDARY_ERROR,
                    step_id=self._first_step_id(trace, ReasoningStage.EDGE_CASES),
                    evidence="division appears in code without a documented zero-divisor edge case",
                )
            )

        if re.search(r"\b(TODO|FIXME|unimplemented)\b", trace.code, re.IGNORECASE):
            findings.append(
                self.classify_signal(
                    RuleSignal.IMPLEMENTATION_ERROR,
                    step_id=self._first_step_id(trace, ReasoningStage.IMPLEMENTATION),
                    evidence="code contains an unfinished implementation marker",
                )
            )

        reasoning_text = " ".join(
            f"{step.claim} {step.rationale}" for step in trace.steps
        ).lower()
        if "according to hidden tests" in reasoning_text:
            findings.append(
                self.classify_signal(
                    RuleSignal.HALLUCINATION,
                    step_id=trace.steps[0].step_id,
                    evidence="reasoning claims access to hidden tests",
                )
            )
        return self._deduplicate(findings)

    @staticmethod
    def _first_step_id(trace: SolutionTrace, stage: ReasoningStage) -> str:
        matching = tuple(step for step in trace.steps if step.stage is stage)
        candidates = matching or trace.steps
        return min(candidates, key=lambda step: step.step_number).step_id

    @staticmethod
    def _deduplicate(findings: list[RuleFinding]) -> tuple[RuleFinding, ...]:
        unique: dict[tuple[ErrorTaxonomy, str | None], RuleFinding] = {}
        for finding in findings:
            unique.setdefault((finding.taxonomy, finding.step_id), finding)
        return tuple(unique.values())
