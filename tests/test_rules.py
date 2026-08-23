from __future__ import annotations

from hy3_algotrace.contracts import (
    ErrorTaxonomy,
    ReasoningStage,
    ReasoningStep,
    SolutionTrace,
)
from hy3_algotrace.rules import RuleEngine, RuleSignal


def trace(
    *,
    steps: tuple[ReasoningStep, ...] | None = None,
    correctness_argument: str = "The comparison returns the maximum.",
    time_complexity: str = "O(1)",
    edge_cases: tuple[str, ...] = ("Equal values.",),
    code: str = "int main() { return 0; }",
) -> SolutionTrace:
    return SolutionTrace(
        trace_id="trace-1",
        problem_id="problem-1",
        steps=steps
        or (
            ReasoningStep(
                step_id="understand",
                step_number=1,
                stage=ReasoningStage.PROBLEM_UNDERSTANDING,
                claim="Read two values.",
                rationale="The statement supplies them.",
            ),
            ReasoningStep(
                step_id="implement",
                step_number=2,
                stage=ReasoningStage.IMPLEMENTATION,
                claim="Print their maximum.",
                rationale="std::max performs the comparison.",
                depends_on=("understand",),
            ),
        ),
        problem_understanding="Read two values.",
        algorithm="Compare the values.",
        correctness_argument=correctness_argument,
        time_complexity=time_complexity,
        space_complexity="O(1)",
        edge_cases=edge_cases,
        code=code,
    )


def test_rule_signals_cover_exact_error_taxonomy() -> None:
    engine = RuleEngine()

    findings = {
        engine.classify_signal(signal, step_id="understand", evidence="literal evidence").taxonomy
        for signal in RuleSignal
    }

    assert findings == set(ErrorTaxonomy)
    assert len(RuleSignal) == 9


def test_malformed_trace_is_a_format_schema_finding() -> None:
    findings = RuleEngine().evaluate({"trace_id": "missing-required-fields"})

    assert len(findings) == 1
    assert findings[0].taxonomy is ErrorTaxonomy.FORMAT_SCHEMA
    assert findings[0].step_id is None


def test_dependency_on_a_later_step_is_a_deterministic_logic_error() -> None:
    first = ReasoningStep(
        step_id="algorithm",
        step_number=1,
        stage=ReasoningStage.ALGORITHM_DESIGN,
        claim="Use the implementation result.",
        rationale="The later step supplies it.",
        depends_on=("implement",),
    )
    second = ReasoningStep(
        step_id="implement",
        step_number=2,
        stage=ReasoningStage.IMPLEMENTATION,
        claim="Implement the algorithm.",
        rationale="The code follows the design.",
    )

    findings = RuleEngine().evaluate(trace(steps=(first, second)))

    assert [(finding.step_id, finding.taxonomy) for finding in findings] == [
        ("algorithm", ErrorTaxonomy.ALGORITHM_LOGIC)
    ]


def test_explanation_and_complexity_consistency_signals_are_reported() -> None:
    findings = RuleEngine().evaluate(
        trace(
            correctness_argument=" ",
            time_complexity="O(1)",
            edge_cases=("Large positive inputs.",),
            code="int main(){ for(int i=0;i<n;i++) total += a[i] / divisor; }",
        )
    )

    assert {finding.taxonomy for finding in findings} == {
        ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
        ErrorTaxonomy.COMPLEXITY_ERROR,
    }
    assert all(finding.material for finding in findings)


def test_constant_division_does_not_invent_a_zero_divisor_boundary_error() -> None:
    findings = RuleEngine().evaluate(
        trace(
            edge_cases=("Odd inputs round down.",),
            code="int main(){ int n; cin >> n; cout << n / 2; }",
        )
    )

    assert ErrorTaxonomy.BOUNDARY_ERROR not in {
        finding.taxonomy for finding in findings
    }
