"""Blind human-review export, separated decisions, and immutable replay."""

from __future__ import annotations

import random
from pathlib import Path

from .artifacts import ArtifactRef, ArtifactStore
from .benchmark_models import (
    BlindReasoningStep,
    BlindReviewItem,
    HumanConfirmedLabel,
    HumanDecision,
    HumanDecisionChange,
    HumanDecisionField,
    HumanDecisionSet,
    HumanRereviewAgreement,
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
        ordered_steps = tuple(sorted(trace.steps, key=lambda item: item.step_number))
        blind_step_ids = {
            step.step_id: f"step-{index}" for index, step in enumerate(ordered_steps, start=1)
        }
        items.append(
            BlindReviewItem(
                blind_id=blind_id,
                statement=candidate.statement,
                public_examples=candidate.public_examples,
                steps=tuple(
                    BlindReasoningStep(
                        step_id=blind_step_ids[step.step_id],
                        step_number=step.step_number,
                        stage=step.stage,
                        claim=step.claim,
                        rationale=step.rationale,
                        depends_on=tuple(
                            blind_step_ids[dependency] for dependency in step.depends_on
                        ),
                    )
                    for step in ordered_steps
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
    mapping_ref = artifacts.write_json(root / "mapping.json", mapping.model_dump(mode="json"))
    return export_ref, mapping_ref


def persist_decisions(artifacts: ArtifactStore, decision_set: HumanDecisionSet) -> ArtifactRef:
    return artifacts.write_json(
        Path("human-review")
        / decision_set.batch_id
        / "decisions"
        / f"{decision_set.decision_set_id}.json",
        decision_set.model_dump(mode="json"),
    )


def select_delayed_rereview(blind_ids: tuple[str, ...], *, seed: int) -> tuple[str, ...]:
    """Select the frozen 20% delayed-rereview sample deterministically."""

    if not blind_ids or len(set(blind_ids)) != len(blind_ids):
        raise ValueError("blind IDs must be nonempty and unique")
    sample_size = (len(blind_ids) + 4) // 5
    return tuple(random.Random(seed).sample(blind_ids, sample_size))


def _changed_fields(
    initial: HumanDecision, delayed: HumanDecision
) -> tuple[HumanDecisionField, ...]:
    names: tuple[HumanDecisionField, ...] = (
        "final_correct",
        "process_valid",
        "first_error_step",
        "taxonomy",
    )
    return tuple(name for name in names if getattr(initial, name) != getattr(delayed, name))


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
    mapping_ids = tuple(entry.blind_id for entry in mapping.entries)
    initial_ids = tuple(item.blind_id for item in decision_set.initial_decisions)
    if set(initial_ids) != set(mapping_ids):
        raise ValueError("initial decisions must cover the complete blind batch")
    sample_by_blind = {entry.blind_id: entry.sample_id for entry in mapping.entries}
    delayed_by_blind = {item.blind_id: item for item in decision_set.delayed_decisions}
    decisions_by_sample = {}
    for initial in decision_set.initial_decisions:
        decision = delayed_by_blind.get(initial.blind_id, initial)
        try:
            sample_id = sample_by_blind[decision.blind_id]
        except KeyError as error:
            raise ValueError("decision references an unknown blind identity") from error
        decisions_by_sample[sample_id] = decision
    known_samples = {row.sample_id for row in observations}
    if not set(decisions_by_sample) <= known_samples:
        raise ValueError("decision mapping references an unknown observation")
    human_labels = tuple(
        HumanConfirmedLabel(
            sample_id=sample_id,
            final_correct=decision.final_correct,
            process_valid=decision.process_valid,
            first_error_step=decision.first_error_step,
            taxonomy=decision.taxonomy,
        )
        for sample_id, decision in decisions_by_sample.items()
    )
    initial_by_blind = {item.blind_id: item for item in decision_set.initial_decisions}
    changes = tuple(
        HumanDecisionChange(
            blind_id=delayed.blind_id,
            initial_decision_id=initial_by_blind[delayed.blind_id].decision_id,
            delayed_decision_id=delayed.decision_id,
            changed_fields=_changed_fields(initial_by_blind[delayed.blind_id], delayed),
        )
        for delayed in decision_set.delayed_decisions
        if _changed_fields(initial_by_blind[delayed.blind_id], delayed)
    )
    rereviewed_count = len(decision_set.delayed_decisions)
    agreement = HumanRereviewAgreement(
        rereviewed_count=rereviewed_count,
        unchanged_count=rereviewed_count - len(changes),
        agreement=(rereviewed_count - len(changes)) / rereviewed_count,
        changes=changes,
    )
    replay = HumanReviewReplay(
        replay_id=replay_id,
        batch_id=mapping.batch_id,
        source_decision_set_id=decision_set.decision_set_id,
        observations=observations,
        human_labels=human_labels,
        rereview_agreement=agreement,
    )
    artifacts.write_json(
        Path("human-review") / mapping.batch_id / "replays" / f"{replay_id}.json",
        replay.model_dump(mode="json"),
    )
    return replay
