"""Literal-denominator benchmark metrics and stratified recomputation."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .benchmark_models import (
    HumanConfirmedLabel,
    MetricBreakdown,
    MetricObservation,
    MetricResult,
    MetricsReport,
    SampleKind,
)
from .contracts import ErrorTaxonomy, RatingBand, Topic


def _ratio(
    name: str,
    rows: Sequence[MetricObservation],
    success: Callable[[MetricObservation], bool],
) -> MetricResult:
    included = tuple(row.sample_id for row in rows)
    numerator = float(sum(success(row) for row in rows))
    denominator = len(rows)
    return MetricResult(
        name=name,
        numerator=numerator,
        denominator=denominator,
        value=None if denominator == 0 else numerator / denominator,
        not_evaluable=denominator == 0,
        included_sample_ids=included,
    )


def _taxonomy_macro_f1(rows: Sequence[MetricObservation], *, formal: bool) -> MetricResult:
    included = tuple(row for row in rows if row.gold_taxonomy is not None)
    if not included and not formal:
        return MetricResult(
            name="taxonomy_macro_f1",
            numerator=0.0,
            denominator=0,
            value=None,
            not_evaluable=True,
            included_sample_ids=(),
        )
    class_scores: list[float] = []
    for taxonomy in ErrorTaxonomy:
        support = sum(row.gold_taxonomy is taxonomy for row in included)
        if formal and support == 0:
            raise ValueError(f"formal taxonomy support is missing for {taxonomy.value}")
        true_positive = sum(
            row.gold_taxonomy is taxonomy and row.predicted_taxonomy is taxonomy for row in included
        )
        false_positive = sum(
            row.gold_taxonomy is not taxonomy and row.predicted_taxonomy is taxonomy
            for row in included
        )
        false_negative = sum(
            row.gold_taxonomy is taxonomy and row.predicted_taxonomy is not taxonomy
            for row in included
        )
        f1_denominator = 2 * true_positive + false_positive + false_negative
        class_scores.append(0.0 if f1_denominator == 0 else 2 * true_positive / f1_denominator)
    denominator = len(tuple(ErrorTaxonomy))
    numerator = float(sum(class_scores))
    return MetricResult(
        name="taxonomy_macro_f1",
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator,
        not_evaluable=False,
        included_sample_ids=tuple(row.sample_id for row in included),
    )


def _metric_set(
    rows: Sequence[MetricObservation],
    *,
    human_labels: Sequence[HumanConfirmedLabel] = (),
    formal: bool = False,
) -> tuple[MetricResult, ...]:
    natural_final = tuple(
        row
        for row in rows
        if row.sample_kind is SampleKind.NATURAL and row.gold_final_correct is not None
    )
    natural_process = tuple(
        row
        for row in rows
        if row.sample_kind is SampleKind.NATURAL and row.gold_process_valid is not None
    )
    process_labeled = tuple(row for row in rows if row.gold_process_valid is not None)
    invalid = tuple(row for row in rows if row.gold_process_valid is False)
    localized = tuple(row for row in invalid if row.gold_first_error_step is not None)
    paradox = tuple(
        row for row in rows if row.gold_final_correct is True and row.gold_process_valid is False
    )
    standard_gold = tuple(
        row
        for row in rows
        if row.sample_kind is SampleKind.GOLD
        and row.gold_final_correct is True
        and row.gold_process_valid is True
    )
    audited = tuple(rows)
    human_by_sample = {label.sample_id: label for label in human_labels}
    flagged_confirmed = tuple(
        row for row in rows if row.needs_human_review and row.sample_id in human_by_sample
    )
    reviewed = tuple(row for row in rows if row.primary_review_agreement is not None)
    return (
        _ratio(
            "natural_final_accuracy",
            natural_final,
            lambda row: row.gold_final_correct is True,
        ),
        _ratio(
            "natural_process_valid_rate",
            natural_process,
            lambda row: row.gold_process_valid is True,
        ),
        _ratio(
            "natural_final_correctness_evaluator_agreement",
            natural_final,
            lambda row: row.predicted_final_correct is row.gold_final_correct,
        ),
        _ratio(
            "process_validity_evaluator_agreement",
            process_labeled,
            lambda row: row.predicted_process_valid is row.gold_process_valid,
        ),
        _ratio(
            "invalid_process_detection",
            invalid,
            lambda row: not row.predicted_process_valid,
        ),
        _ratio(
            "exact_localization",
            localized,
            lambda row: (
                not row.predicted_process_valid
                and row.predicted_first_error_step == row.gold_first_error_step
            ),
        ),
        _ratio(
            "within_one_localization",
            localized,
            lambda row: (
                not row.predicted_process_valid
                and row.predicted_first_error_step is not None
                and row.gold_first_error_step is not None
                and abs(row.predicted_first_error_step - row.gold_first_error_step) <= 1
            ),
        ),
        _ratio(
            "paradox_recall",
            paradox,
            lambda row: row.predicted_final_correct and not row.predicted_process_valid,
        ),
        _ratio(
            "standard_gold_false_positive_rate",
            standard_gold,
            lambda row: not row.predicted_process_valid,
        ),
        _ratio(
            "human_review_flag_rate",
            audited,
            lambda row: row.needs_human_review,
        ),
        _ratio(
            "flagged_final_correct_process_issue_rate",
            flagged_confirmed,
            lambda row: (
                human_by_sample[row.sample_id].final_correct
                and not human_by_sample[row.sample_id].process_valid
            ),
        ),
        _ratio(
            "flagged_false_positive_rate",
            flagged_confirmed,
            lambda row: human_by_sample[row.sample_id].process_valid,
        ),
        _ratio(
            "primary_review_agreement_rate",
            reviewed,
            lambda row: row.primary_review_agreement is True,
        ),
        _ratio(
            "arbitration_rate",
            reviewed,
            lambda row: row.arbitration_used,
        ),
        _taxonomy_macro_f1(rows, formal=formal),
    )


def compute_metrics(
    rows: Sequence[MetricObservation],
    *,
    human_labels: Sequence[HumanConfirmedLabel] = (),
    formal: bool = False,
) -> MetricsReport:
    """Compute overall and stratified metrics directly from included rows."""

    stable_rows = tuple(rows)
    stable_human_labels = tuple(human_labels)
    known_ids = {row.sample_id for row in stable_rows}
    label_ids = tuple(label.sample_id for label in stable_human_labels)
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("human-confirmed sample IDs must be unique")
    if not set(label_ids) <= known_ids:
        raise ValueError("human-confirmed label references an unknown sample")
    overall = _metric_set(
        stable_rows,
        human_labels=stable_human_labels,
        formal=formal,
    )
    by_topic = tuple(
        MetricBreakdown(
            key=topic.value,
            metrics=_metric_set(
                tuple(row for row in stable_rows if row.topic is topic),
                human_labels=stable_human_labels,
            ),
        )
        for topic in Topic
        if any(row.topic is topic for row in stable_rows)
    )
    by_rating = tuple(
        MetricBreakdown(
            key=rating.value,
            metrics=_metric_set(
                tuple(row for row in stable_rows if row.rating_band is rating),
                human_labels=stable_human_labels,
            ),
        )
        for rating in RatingBand
        if any(row.rating_band is rating for row in stable_rows)
    )
    return MetricsReport(
        overall=overall,
        by_topic=by_topic,
        by_rating_band=by_rating,
    )
