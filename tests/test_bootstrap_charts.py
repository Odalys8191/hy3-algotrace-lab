from __future__ import annotations

from test_metrics import literal_rows

from hy3_algotrace.bootstrap import (
    bootstrap_metric,
    find_stable_breakpoint,
    natural_final_outcomes,
)
from hy3_algotrace.charts import (
    metric_chart_spec,
    stratified_metric_chart_spec,
    taxonomy_distribution_chart_spec,
)
from hy3_algotrace.contracts import RatingBand
from hy3_algotrace.metrics import compute_metrics


def test_iid_bootstrap_uses_frozen_seed_and_linear_percentiles() -> None:
    rows = literal_rows()

    first = bootstrap_metric(
        rows,
        metric_name="natural_final_accuracy",
        seed=7,
        replicates=8,
    )
    second = bootstrap_metric(
        rows,
        metric_name="natural_final_accuracy",
        seed=7,
        replicates=8,
    )

    assert first == second
    assert first.available is True
    assert first.lower == 1 / 3
    assert first.upper == 113 / 120
    assert first.requested_replicates == 8
    assert first.valid_replicates == 8
    assert first.included_sample_ids == ("n1", "n2", "n3")


def test_bootstrap_is_honestly_unavailable_for_zero_denominator() -> None:
    rows = tuple(row for row in literal_rows() if row.sample_kind.value != "natural")

    interval = bootstrap_metric(
        rows,
        metric_name="natural_final_accuracy",
        seed=19,
        replicates=10,
    )

    assert interval.available is False
    assert interval.lower is None
    assert interval.upper is None
    assert interval.valid_replicates == 0
    assert interval.included_sample_ids == ()


def test_stable_breakpoint_requires_twenty_points_and_positive_drop_interval() -> None:
    stable = find_stable_breakpoint(
        {
            RatingBand.FOUNDATION: (True, True),
            RatingBand.INTERMEDIATE: (False, False),
            RatingBand.ADVANCED: (False, True),
        },
        seed=3,
        replicates=20,
    )
    none = find_stable_breakpoint(
        {
            RatingBand.FOUNDATION: (True, False),
            RatingBand.INTERMEDIATE: (False, True),
            RatingBand.ADVANCED: (False, True),
        },
        seed=3,
        replicates=20,
    )

    assert stable.stable is True
    assert stable.not_evaluable is False
    assert stable.lower_band is RatingBand.FOUNDATION
    assert stable.upper_band is RatingBand.INTERMEDIATE
    assert stable.decline == 1.0
    assert stable.drop_ci_lower == 1.0
    assert stable.drop_ci_upper == 1.0
    assert none.stable is False
    assert none.not_evaluable is False
    assert none.lower_band is None
    assert none.upper_band is None


def test_breakpoint_is_not_evaluable_when_an_adjacent_band_is_missing() -> None:
    result = find_stable_breakpoint(
        {RatingBand.FOUNDATION: (True,), RatingBand.ADVANCED: (False,)},
        seed=1,
        replicates=5,
    )

    assert result.stable is False
    assert result.not_evaluable is True


def test_breakpoint_inputs_use_generator_outcomes_not_evaluator_agreement() -> None:
    foundation = literal_rows()[0].model_copy(
        update={"gold_final_correct": False, "predicted_final_correct": False}
    )
    intermediate = literal_rows()[1].model_copy(
        update={
            "rating_band": RatingBand.INTERMEDIATE,
            "gold_final_correct": True,
            "predicted_final_correct": False,
        }
    )

    outcomes = natural_final_outcomes((foundation, intermediate))

    assert outcomes[RatingBand.FOUNDATION] == (False,)
    assert outcomes[RatingBand.INTERMEDIATE] == (True,)


def test_chart_spec_is_deterministic_literal_json_data() -> None:
    report = compute_metrics(literal_rows())

    spec = metric_chart_spec(
        report,
        metric_names=(
            "natural_final_accuracy",
            "process_validity_evaluator_agreement",
        ),
    )

    assert spec.model_dump(mode="json") == {
        "schema_version": "1.2",
        "chart_version": "task6-chart-v1",
        "chart_id": "overall-metrics",
        "title": "Overall benchmark metrics",
        "mark": "bar",
        "x_field": "metric",
        "y_field": "value",
        "points": [
            {
                "schema_version": "1.2",
                "metric": "natural_final_accuracy",
                "stratum": "overall",
                "value": 1 / 3,
                "numerator": 1.0,
                "denominator": 3,
            },
            {
                "schema_version": "1.2",
                "metric": "process_validity_evaluator_agreement",
                "stratum": "overall",
                "value": 4 / 6,
                "numerator": 4.0,
                "denominator": 6,
            },
        ],
    }


def test_topic_and_rating_chart_specs_are_deterministic_literal_data() -> None:
    report = compute_metrics(literal_rows())

    topic = stratified_metric_chart_spec(
        report, dimension="topic", metric_names=("natural_final_accuracy",)
    )
    rating = stratified_metric_chart_spec(
        report, dimension="rating_band", metric_names=("natural_final_accuracy",)
    )

    assert topic.model_dump(mode="json") == {
        "schema_version": "1.2",
        "chart_version": "task6-chart-v1",
        "chart_id": "topic-metrics",
        "title": "Benchmark metrics by topic",
        "mark": "bar",
        "x_field": "stratum",
        "y_field": "value",
        "points": [
            {
                "schema_version": "1.2",
                "metric": "natural_final_accuracy",
                "stratum": "greedy",
                "value": 0.5,
                "numerator": 1.0,
                "denominator": 2,
            },
            {
                "schema_version": "1.2",
                "metric": "natural_final_accuracy",
                "stratum": "graph",
                "value": 0.0,
                "numerator": 0.0,
                "denominator": 1,
            },
        ],
    }
    assert rating.model_dump(mode="json") == {
        "schema_version": "1.2",
        "chart_version": "task6-chart-v1",
        "chart_id": "rating-band-metrics",
        "title": "Benchmark metrics by rating band",
        "mark": "bar",
        "x_field": "stratum",
        "y_field": "value",
        "points": [
            {
                "schema_version": "1.2",
                "metric": "natural_final_accuracy",
                "stratum": "1200-1500",
                "value": 0.5,
                "numerator": 1.0,
                "denominator": 2,
            },
            {
                "schema_version": "1.2",
                "metric": "natural_final_accuracy",
                "stratum": "2000-2400",
                "value": 0.0,
                "numerator": 0.0,
                "denominator": 1,
            },
        ],
    }


def test_taxonomy_chart_includes_frozen_nine_classes_in_enum_order() -> None:
    spec = taxonomy_distribution_chart_spec(literal_rows())

    assert spec.model_dump(mode="json") == {
        "schema_version": "1.2",
        "chart_version": "task6-chart-v1",
        "chart_id": "taxonomy-distribution",
        "title": "Predicted error taxonomy distribution",
        "mark": "bar",
        "x_field": "stratum",
        "y_field": "value",
        "points": [
            {
                "schema_version": "1.2",
                "metric": "predicted_error_taxonomy",
                "stratum": name,
                "value": count / 4,
                "numerator": float(count),
                "denominator": 4,
            }
            for name, count in (
                ("problem_misread", 0),
                ("constraint_omission", 0),
                ("algorithm_logic", 0),
                ("proof_gap_circularity", 1),
                ("complexity_error", 0),
                ("boundary_error", 1),
                ("implementation_error", 1),
                ("hallucination", 1),
                ("format_schema", 0),
            )
        ],
    }
