"""Deterministic chart data/specification JSON without plotting dependencies."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from .benchmark_models import ChartPoint, ChartSpec, MetricObservation, MetricsReport
from .contracts import ErrorTaxonomy


def metric_chart_spec(report: MetricsReport, *, metric_names: Sequence[str]) -> ChartSpec:
    """Build an ordered overall-metric bar-chart specification."""

    metrics = {metric.name: metric for metric in report.overall}
    points = []
    for name in metric_names:
        try:
            metric = metrics[name]
        except KeyError as error:
            raise ValueError(f"unknown metric for chart: {name}") from error
        points.append(
            ChartPoint(
                metric=name,
                stratum="overall",
                value=metric.value,
                numerator=metric.numerator,
                denominator=metric.denominator,
            )
        )
    return ChartSpec(
        chart_id="overall-metrics",
        title="Overall benchmark metrics",
        mark="bar",
        x_field="metric",
        points=tuple(points),
    )


def stratified_metric_chart_spec(
    report: MetricsReport,
    *,
    dimension: Literal["topic", "rating_band"],
    metric_names: Sequence[str],
) -> ChartSpec:
    """Build ordered topic or rating-band metrics from exact strata."""

    breakdowns = report.by_topic if dimension == "topic" else report.by_rating_band
    points: list[ChartPoint] = []
    for breakdown in breakdowns:
        metrics = {metric.name: metric for metric in breakdown.metrics}
        for name in metric_names:
            try:
                metric = metrics[name]
            except KeyError as error:
                raise ValueError(f"unknown metric for chart: {name}") from error
            points.append(
                ChartPoint(
                    metric=name,
                    stratum=breakdown.key,
                    value=metric.value,
                    numerator=metric.numerator,
                    denominator=metric.denominator,
                )
            )
    label = "topic" if dimension == "topic" else "rating band"
    chart_id = "topic-metrics" if dimension == "topic" else "rating-band-metrics"
    return ChartSpec(
        chart_id=chart_id,
        title=f"Benchmark metrics by {label}",
        mark="bar",
        x_field="stratum",
        points=tuple(points),
    )


def taxonomy_distribution_chart_spec(
    rows: Sequence[MetricObservation],
) -> ChartSpec:
    """Publish all nine predicted taxonomy classes, including zero counts."""

    labeled = tuple(row for row in rows if row.predicted_taxonomy is not None)
    denominator = len(labeled)
    points = tuple(
        ChartPoint(
            metric="predicted_error_taxonomy",
            stratum=taxonomy.value,
            value=(
                None
                if denominator == 0
                else sum(row.predicted_taxonomy is taxonomy for row in labeled) / denominator
            ),
            numerator=float(sum(row.predicted_taxonomy is taxonomy for row in labeled)),
            denominator=denominator,
        )
        for taxonomy in ErrorTaxonomy
    )
    return ChartSpec(
        chart_id="taxonomy-distribution",
        title="Predicted error taxonomy distribution",
        mark="bar",
        x_field="stratum",
        points=points,
    )
