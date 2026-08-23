"""Deterministic chart data/specification JSON without plotting dependencies."""

from __future__ import annotations

from collections.abc import Sequence

from .benchmark_models import ChartPoint, ChartSpec, MetricsReport


def metric_chart_spec(
    report: MetricsReport, *, metric_names: Sequence[str]
) -> ChartSpec:
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
