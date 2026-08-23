"""Blind human-review export, separated decisions, and immutable replay."""

from __future__ import annotations

from pathlib import Path

from .artifacts import ArtifactRef, ArtifactStore
from .benchmark_models import (
    BlindReasoningStep,
    BlindReviewItem,
    HumanDecisionSet,
    HumanReviewCandidate,
    HumanReviewExport,
    HumanReviewMapping,
    HumanReviewMappingEntry,
    HumanReviewReplay,
    MetricObservation,
)


def build_blind_batch(
    *,
    batch_id: str,
    candidates: tuple[HumanReviewCandidate, ...],
    blind_ids: tuple[str, ...],
) -> tuple[HumanReviewExport, HumanReviewMapping]:
    """Construct allowlisted public items and their private mapping separately."""

    if not candidates or len(candidates) != len(blind_ids):
        raise ValueError("candidates and blind IDs must be nonempty and parallel")
    items: list[BlindReviewItem] = []
    entries: list[HumanReviewMappingEntry] = []
    for candidate, blind_id in zip(candidates, blind_ids, strict=True):
        trace = candidate.trace
        items.append(
            BlindReviewItem(
                blind_id=blind_id,
                statement=candidate.statement,
                public_examples=candidate.public_examples,
                steps=tuple(
                    BlindReasoningStep(
                        step_number=step.step_number,
                        claim=step.claim,
                        rationale=step.rationale,
                    )
                    for step in sorted(trace.steps, key=lambda item: item.step_number)
                ),
                problem_understanding=trace.problem_understanding,
                algorithm=trace.algorithm,
                correctness_argument=trace.correctness_argument,
                time_complexity=trace.time_complexity,
                space_complexity=trace.space_complexity,
                edge_cases=trace.edge_cases,
                code=trace.code,
            )
        )
        entries.append(
            HumanReviewMappingEntry(
                blind_id=blind_id,
                sample_id=candidate.sample_id,
                problem_id=candidate.problem_id,
                trace_id=candidate.trace_id,
            )
        )
    return (
        HumanReviewExport(batch_id=batch_id, items=tuple(items)),
        HumanReviewMapping(batch_id=batch_id, entries=tuple(entries)),
    )


def persist_blind_batch(
    artifacts: ArtifactStore,
    export: HumanReviewExport,
    mapping: HumanReviewMapping,
) -> tuple[ArtifactRef, ArtifactRef]:
    if export.batch_id != mapping.batch_id:
        raise ValueError("export and mapping batch identities must match")
    export_ids = tuple(item.blind_id for item in export.items)
    mapping_ids = tuple(item.blind_id for item in mapping.entries)
    if export_ids != mapping_ids:
        raise ValueError("export and mapping blind identities must match in order")
    root = Path("human-review") / export.batch_id
    export_ref = artifacts.write_json(root / "export.json", export.model_dump(mode="json"))
    mapping_ref = artifacts.write_json(
        root / "mapping.json", mapping.model_dump(mode="json")
    )
    return export_ref, mapping_ref


def persist_decisions(
    artifacts: ArtifactStore, decision_set: HumanDecisionSet
) -> ArtifactRef:
    return artifacts.write_json(
        Path("human-review")
        / decision_set.batch_id
        / "decisions"
        / f"{decision_set.decision_set_id}.json",
        decision_set.model_dump(mode="json"),
    )


def replay_decisions(
    artifacts: ArtifactStore,
    *,
    replay_id: str,
    observations: tuple[MetricObservation, ...],
    mapping: HumanReviewMapping,
    decision_set: HumanDecisionSet,
) -> HumanReviewReplay:
    """Apply decisions to a new replay artifact without changing source rows."""

    if mapping.batch_id != decision_set.batch_id:
        raise ValueError("mapping and decisions must belong to the same batch")
    sample_by_blind = {entry.blind_id: entry.sample_id for entry in mapping.entries}
    decisions_by_sample = {}
    for decision in decision_set.decisions:
        try:
            sample_id = sample_by_blind[decision.blind_id]
        except KeyError as error:
            raise ValueError("decision references an unknown blind identity") from error
        decisions_by_sample[sample_id] = decision
    known_samples = {row.sample_id for row in observations}
    if not set(decisions_by_sample) <= known_samples:
        raise ValueError("decision mapping references an unknown observation")
    replayed_rows: list[MetricObservation] = []
    for row in observations:
        selected = decisions_by_sample.get(row.sample_id)
        if selected is None:
            replayed_rows.append(row)
            continue
        replayed_rows.append(
            row.model_copy(
                update={
                    "predicted_process_valid": selected.process_valid,
                    "predicted_first_error_step": selected.first_error_step,
                    "predicted_taxonomy": selected.taxonomy,
                    "needs_human_review": False,
                }
            )
        )
    replayed = tuple(replayed_rows)
    replay = HumanReviewReplay(
        replay_id=replay_id,
        batch_id=mapping.batch_id,
        source_decision_set_id=decision_set.decision_set_id,
        observations=replayed,
    )
    artifacts.write_json(
        Path("human-review") / mapping.batch_id / "replays" / f"{replay_id}.json",
        replay.model_dump(mode="json"),
    )
    return replay
