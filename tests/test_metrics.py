from __future__ import annotations

import pytest
from pydantic import ValidationError

from hy3_algotrace.benchmark_models import MetricObservation, SampleKind
from hy3_algotrace.contracts import ErrorTaxonomy, RatingBand, Topic
from hy3_algotrace.metrics import compute_metrics


def observation(
    sample_id: str,
    *,
    sample_kind: SampleKind,
    topic: Topic,
    rating_band: RatingBand,
    gold_final_correct: bool,
    gold_process_valid: bool,
    predicted_final_correct: bool,
    predicted_process_valid: bool,
    gold_first_error_step: int | None = None,
    predicted_first_error_step: int | None = None,
    gold_taxonomy: ErrorTaxonomy | None = None,
    predicted_taxonomy: ErrorTaxonomy | None = None,
    flagged: bool = False,
    agreement: bool = True,
    arbitration: bool = False,
) -> MetricObservation:
    return MetricObservation(
        sample_id=sample_id,
        problem_id=f"problem-{sample_id}",
        sample_kind=sample_kind,
        topic=topic,
        rating_band=rating_band,
        gold_final_correct=gold_final_correct,
        gold_process_valid=gold_process_valid,
        gold_first_error_step=gold_first_error_step,
        gold_taxonomy=gold_taxonomy,
        predicted_final_correct=predicted_final_correct,
        predicted_process_valid=predicted_process_valid,
        predicted_first_error_step=predicted_first_error_step,
        predicted_taxonomy=predicted_taxonomy,
        needs_human_review=flagged,
        primary_review_agreement=agreement,
        arbitration_used=arbitration,
    )


def literal_rows() -> tuple[MetricObservation, ...]:
    return (
        observation(
            "n1",
            sample_kind=SampleKind.NATURAL,
            topic=Topic.GREEDY,
            rating_band=RatingBand.FOUNDATION,
            gold_final_correct=True,
            gold_process_valid=True,
            predicted_final_correct=True,
            predicted_process_valid=True,
        ),
        observation(
            "n2",
            sample_kind=SampleKind.NATURAL,
            topic=Topic.GREEDY,
            rating_band=RatingBand.FOUNDATION,
            gold_final_correct=False,
            gold_process_valid=False,
            gold_first_error_step=2,
            gold_taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
            predicted_final_correct=True,
            predicted_process_valid=False,
            predicted_first_error_step=3,
            predicted_taxonomy=ErrorTaxonomy.BOUNDARY_ERROR,
            flagged=True,
            agreement=False,
            arbitration=True,
        ),
        observation(
            "n3",
            sample_kind=SampleKind.NATURAL,
            topic=Topic.GRAPH,
            rating_band=RatingBand.ADVANCED,
            gold_final_correct=False,
            gold_process_valid=False,
            gold_first_error_step=4,
            gold_taxonomy=ErrorTaxonomy.BOUNDARY_ERROR,
            predicted_final_correct=False,
            predicted_process_valid=True,
        ),
        observation(
            "g1",
            sample_kind=SampleKind.GOLD,
            topic=Topic.GREEDY,
            rating_band=RatingBand.FOUNDATION,
            gold_final_correct=True,
            gold_process_valid=True,
            predicted_final_correct=True,
            predicted_process_valid=False,
            predicted_first_error_step=1,
            predicted_taxonomy=ErrorTaxonomy.HALLUCINATION,
            flagged=True,
        ),
        observation(
            "p1",
            sample_kind=SampleKind.PARADOX,
            topic=Topic.GRAPH,
            rating_band=RatingBand.ADVANCED,
            gold_final_correct=True,
            gold_process_valid=False,
            gold_first_error_step=2,
            gold_taxonomy=ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
            predicted_final_correct=True,
            predicted_process_valid=False,
            predicted_first_error_step=2,
            predicted_taxonomy=ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
            agreement=False,
            arbitration=True,
        ),
        observation(
            "c1",
            sample_kind=SampleKind.CONTROLLED_WRONG,
            topic=Topic.GRAPH,
            rating_band=RatingBand.ADVANCED,
            gold_final_correct=False,
            gold_process_valid=False,
            gold_first_error_step=1,
            gold_taxonomy=ErrorTaxonomy.IMPLEMENTATION_ERROR,
            predicted_final_correct=False,
            predicted_process_valid=False,
            predicted_first_error_step=1,
            predicted_taxonomy=ErrorTaxonomy.IMPLEMENTATION_ERROR,
        ),
    )


def as_map(metrics):  # type: ignore[no-untyped-def]
    return {metric.name: metric for metric in metrics}


def test_metrics_use_frozen_literal_denominators_and_included_ids() -> None:
    report = compute_metrics(literal_rows())
    metrics = as_map(report.overall)
    expected = {
        "natural_final_accuracy": (2.0, 3, 2 / 3, ("n1", "n2", "n3")),
        "process_correctness": (4.0, 6, 4 / 6, ("n1", "n2", "n3", "g1", "p1", "c1")),
        "invalid_process_detection": (3.0, 4, 3 / 4, ("n2", "n3", "p1", "c1")),
        "exact_localization": (2.0, 4, 2 / 4, ("n2", "n3", "p1", "c1")),
        "within_one_localization": (3.0, 4, 3 / 4, ("n2", "n3", "p1", "c1")),
        "paradox_recall": (1.0, 1, 1.0, ("p1",)),
        "standard_gold_false_positive_rate": (1.0, 1, 1.0, ("g1",)),
        "human_review_flag_rate": (2.0, 6, 2 / 6, ("n1", "n2", "n3", "g1", "p1", "c1")),
        "flagged_final_incorrect_proportion": (1.0, 2, 0.5, ("n2", "g1")),
        "flagged_process_invalid_proportion": (1.0, 2, 0.5, ("n2", "g1")),
        "primary_review_agreement_rate": (4.0, 6, 4 / 6, ("n1", "n2", "n3", "g1", "p1", "c1")),
        "arbitration_rate": (2.0, 6, 2 / 6, ("n1", "n2", "n3", "g1", "p1", "c1")),
    }
    for name, literal in expected.items():
        metric = metrics[name]
        assert (
            metric.numerator,
            metric.denominator,
            metric.value,
            metric.included_sample_ids,
        ) == literal
        assert metric.not_evaluable is False


def test_breakdowns_recompute_rows_instead_of_averaging_percentages() -> None:
    report = compute_metrics(literal_rows())
    topics = {item.key: as_map(item.metrics) for item in report.by_topic}
    ratings = {item.key: as_map(item.metrics) for item in report.by_rating_band}

    assert topics["greedy"]["natural_final_accuracy"].value == 0.5
    assert topics["greedy"]["natural_final_accuracy"].denominator == 2
    assert topics["graph"]["natural_final_accuracy"].value == 1.0
    assert topics["graph"]["natural_final_accuracy"].denominator == 1
    assert ratings["1200-1500"]["process_correctness"].value == 2 / 3
    assert ratings["1200-1500"]["process_correctness"].denominator == 3
    assert ratings["2000-2400"]["process_correctness"].value == 2 / 3
    assert ratings["2000-2400"]["process_correctness"].denominator == 3


def test_zero_denominator_is_explicitly_not_evaluable() -> None:
    report = compute_metrics(
        (
            observation(
                "g-only",
                sample_kind=SampleKind.GOLD,
                topic=Topic.GREEDY,
                rating_band=RatingBand.FOUNDATION,
                gold_final_correct=True,
                gold_process_valid=True,
                predicted_final_correct=True,
                predicted_process_valid=True,
            ),
        )
    )
    natural = as_map(report.overall)["natural_final_accuracy"]
    assert (natural.numerator, natural.denominator, natural.value) == (0.0, 0, None)
    assert natural.not_evaluable is True
    assert natural.included_sample_ids == ()


def test_taxonomy_macro_f1_uses_frozen_nine_classes_and_formal_support() -> None:
    rows = tuple(
        observation(
            f"tax-{index}",
            sample_kind=SampleKind.CONTROLLED_WRONG,
            topic=Topic.GREEDY,
            rating_band=RatingBand.FOUNDATION,
            gold_final_correct=False,
            gold_process_valid=False,
            gold_first_error_step=1,
            gold_taxonomy=taxonomy,
            predicted_final_correct=False,
            predicted_process_valid=False,
            predicted_first_error_step=1,
            predicted_taxonomy=taxonomy,
        )
        for index, taxonomy in enumerate(ErrorTaxonomy, start=1)
    )
    metric = as_map(compute_metrics(rows, formal=True).overall)["taxonomy_macro_f1"]

    assert metric.numerator == 9.0
    assert metric.denominator == 9
    assert metric.value == 1.0
    assert metric.included_sample_ids == tuple(f"tax-{index}" for index in range(1, 10))

    with pytest.raises(ValueError, match="formal taxonomy support"):
        compute_metrics(rows[:-1], formal=True)


def test_metric_observation_is_strict_frozen_and_rejects_invalid_labels() -> None:
    row = literal_rows()[0]
    with pytest.raises(ValidationError):
        MetricObservation.model_validate({**row.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError):
        row.predicted_process_valid = False
    with pytest.raises(ValidationError, match="gold invalid process"):
        MetricObservation.model_validate(
            {
                **row.model_dump(),
                "gold_process_valid": False,
                "gold_first_error_step": None,
                "gold_taxonomy": None,
            }
        )
