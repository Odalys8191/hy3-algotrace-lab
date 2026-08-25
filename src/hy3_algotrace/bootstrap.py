"""Deterministic IID bootstrap intervals and natural-accuracy breakpoint analysis.

The frozen estimator resamples rows independently. Multiple rows from one problem
may therefore be correlated; this is a documented limitation, not a cluster bootstrap.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

from .benchmark_models import (
    BreakpointResult,
    ConfidenceInterval,
    HumanConfirmedLabel,
    MetricObservation,
    SampleKind,
)
from .contracts import RatingBand
from .metrics import compute_metrics


def natural_final_outcomes(
    rows: Sequence[MetricObservation],
) -> Mapping[RatingBand, tuple[bool, ...]]:
    """Return actual independently established natural-run correctness outcomes."""

    return {
        band: tuple(
            row.gold_final_correct
            for row in rows
            if row.sample_kind is SampleKind.NATURAL
            and row.gold_final_correct is not None
            and row.rating_band is band
        )
        for band in RatingBand
    }


def _metric_value(
    rows: Sequence[MetricObservation],
    metric_name: str,
    human_labels: Sequence[HumanConfirmedLabel],
) -> float | None:
    row_ids = {row.sample_id for row in rows}
    sampled_labels = tuple(label for label in human_labels if label.sample_id in row_ids)
    for metric in compute_metrics(rows, human_labels=sampled_labels).overall:
        if metric.name == metric_name:
            return metric.value
    raise ValueError(f"unknown metric: {metric_name}")


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + fraction * (ordered[upper_index] - ordered[lower_index])


def bootstrap_metric(
    rows: Sequence[MetricObservation],
    *,
    metric_name: str,
    seed: int,
    replicates: int = 10_000,
    human_labels: Sequence[HumanConfirmedLabel] = (),
) -> ConfidenceInterval:
    """Bootstrap one metric from exactly the rows in its frozen denominator."""

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    stable_human_labels = tuple(human_labels)
    report = compute_metrics(rows, human_labels=stable_human_labels)
    try:
        metric = next(item for item in report.overall if item.name == metric_name)
    except StopIteration as error:
        raise ValueError(f"unknown metric: {metric_name}") from error
    if metric.not_evaluable:
        return ConfidenceInterval(
            metric_name=metric_name,
            lower=None,
            upper=None,
            available=False,
            seed=seed,
            requested_replicates=replicates,
            valid_replicates=0,
            included_sample_ids=metric.included_sample_ids,
        )
    included_ids = set(metric.included_sample_ids)
    included = tuple(row for row in rows if row.sample_id in included_ids)
    included_human_labels = tuple(
        label for label in stable_human_labels if label.sample_id in included_ids
    )
    if not included:
        return ConfidenceInterval(
            metric_name=metric_name,
            lower=None,
            upper=None,
            available=False,
            seed=seed,
            requested_replicates=replicates,
            valid_replicates=0,
            included_sample_ids=metric.included_sample_ids,
        )
    generator = random.Random(seed)
    values: list[float] = []
    for _ in range(replicates):
        sample = tuple(generator.choice(included) for _ in included)
        value = _metric_value(sample, metric_name, included_human_labels)
        if value is not None:
            values.append(value)
    if not values:
        return ConfidenceInterval(
            metric_name=metric_name,
            lower=None,
            upper=None,
            available=False,
            seed=seed,
            requested_replicates=replicates,
            valid_replicates=0,
            included_sample_ids=metric.included_sample_ids,
        )
    return ConfidenceInterval(
        metric_name=metric_name,
        lower=_percentile(values, 0.025),
        upper=_percentile(values, 0.975),
        available=True,
        seed=seed,
        requested_replicates=replicates,
        valid_replicates=len(values),
        included_sample_ids=metric.included_sample_ids,
    )


def find_stable_breakpoint(
    outcomes: Mapping[RatingBand, Sequence[bool]],
    *,
    seed: int,
    replicates: int = 10_000,
) -> BreakpointResult:
    """Return the first adjacent >=20-point decline with positive drop CI."""

    if replicates < 1:
        raise ValueError("bootstrap replicates must be positive")
    ordered_bands = tuple(RatingBand)
    if any(not outcomes.get(band) for band in ordered_bands):
        return BreakpointResult(
            stable=False,
            not_evaluable=True,
            seed=seed,
            replicates=replicates,
        )
    generator = random.Random(seed)
    for lower_band, upper_band in zip(ordered_bands, ordered_bands[1:]):
        lower = tuple(outcomes[lower_band])
        upper = tuple(outcomes[upper_band])
        decline = sum(lower) / len(lower) - sum(upper) / len(upper)
        drops = []
        for _ in range(replicates):
            lower_value = sum(generator.choice(lower) for _ in lower) / len(lower)
            upper_value = sum(generator.choice(upper) for _ in upper) / len(upper)
            drops.append(lower_value - upper_value)
        ci_lower = _percentile(drops, 0.025)
        ci_upper = _percentile(drops, 0.975)
        if decline >= 0.20 and ci_lower > 0:
            return BreakpointResult(
                stable=True,
                not_evaluable=False,
                lower_band=lower_band,
                upper_band=upper_band,
                decline=decline,
                drop_ci_lower=ci_lower,
                drop_ci_upper=ci_upper,
                seed=seed,
                replicates=replicates,
            )
    return BreakpointResult(
        stable=False,
        not_evaluable=False,
        seed=seed,
        replicates=replicates,
    )
