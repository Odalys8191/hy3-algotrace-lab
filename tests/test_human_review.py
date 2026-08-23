from __future__ import annotations

from pathlib import Path

import pytest
from test_metrics import literal_rows
from test_run_service import valid_trace

from hy3_algotrace.artifacts import ArtifactExistsError, ArtifactStore
from hy3_algotrace.benchmark_models import (
    BlindPublicExample,
    HumanDecision,
    HumanDecisionSet,
    HumanReviewCandidate,
)
from hy3_algotrace.contracts import ErrorTaxonomy
from hy3_algotrace.human_review import (
    build_blind_batch,
    persist_blind_batch,
    persist_decisions,
    replay_decisions,
)


def test_blind_export_is_an_allowlist_and_mapping_is_separate() -> None:
    trace = valid_trace().model_copy(
        update={"problem_id": "secret-problem", "trace_id": "secret-trace"}
    )
    candidate = HumanReviewCandidate(
        sample_id="secret-sample",
        problem_id="secret-problem",
        trace_id="secret-trace",
        statement="Add one to the public integer.",
        public_examples=(BlindPublicExample(input_data="1\n", output_data="2\n"),),
        trace=trace,
    )

    export, mapping = build_blind_batch(
        batch_id="review-1",
        candidates=(candidate,),
        blind_ids=("candidate-a",),
    )

    payload = export.model_dump(mode="json")
    assert payload == {
        "schema_version": "1.2",
        "batch_id": "review-1",
        "items": [
            {
                "schema_version": "1.2",
                "blind_id": "candidate-a",
                "statement": "Add one to the public integer.",
                "public_examples": [
                    {
                        "schema_version": "1.2",
                        "input_data": "1\n",
                        "output_data": "2\n",
                    }
                ],
                "steps": [
                    {
                        "schema_version": "1.2",
                        "step_number": 1,
                        "claim": "Read x.",
                        "rationale": "The input contains one integer.",
                    },
                    {
                        "schema_version": "1.2",
                        "step_number": 2,
                        "claim": "Print x + 1.",
                        "rationale": "This is the requested value.",
                    },
                ],
                "problem_understanding": "Read one integer.",
                "algorithm": "Add one and print.",
                "correctness_argument": "The printed value is exactly one larger.",
                "time_complexity": "O(1)",
                "space_complexity": "O(1)",
                "edge_cases": ["negative integers"],
                "code": "#include <iostream>\nint main(){long long x;std::cin>>x;std::cout<<x+1;}",
            }
        ],
    }
    serialized = str(payload).casefold()
    for forbidden in (
        "secret-sample",
        "secret-problem",
        "secret-trace",
        "sample_kind",
        "gold_",
        "model",
        "verdict",
        "score",
        "taxonomy",
        "first_error",
        "reviewer",
        "arbiter",
        "judge",
        "hidden",
        "oracle",
        "reference",
    ):
        assert forbidden not in serialized
    assert mapping.entries[0].model_dump(mode="json") == {
        "schema_version": "1.2",
        "blind_id": "candidate-a",
        "sample_id": "secret-sample",
        "problem_id": "secret-problem",
        "trace_id": "secret-trace",
    }


def test_export_decisions_and_replays_are_separate_create_only_artifacts(
    tmp_path: Path,
) -> None:
    artifacts = ArtifactStore(tmp_path / "artifacts")
    candidate = HumanReviewCandidate(
        sample_id="n2",
        problem_id="problem-n2",
        trace_id="trace-n2",
        statement="Public statement",
        public_examples=(),
        trace=valid_trace(problem_id="problem-n2").model_copy(
            update={"trace_id": "trace-n2"}
        ),
    )
    export, mapping = build_blind_batch(
        batch_id="review-2", candidates=(candidate,), blind_ids=("blind-2",)
    )
    decision_set = HumanDecisionSet(
        batch_id="review-2",
        decision_set_id="decision-1",
        decisions=(
            HumanDecision(
                blind_id="blind-2",
                process_valid=False,
                first_error_step=2,
                taxonomy=ErrorTaxonomy.ALGORITHM_LOGIC,
            ),
        ),
    )

    export_ref, mapping_ref = persist_blind_batch(artifacts, export, mapping)
    decision_ref = persist_decisions(artifacts, decision_set)
    replay = replay_decisions(
        artifacts,
        replay_id="replay-1",
        observations=literal_rows(),
        mapping=mapping,
        decision_set=decision_set,
    )

    assert str(export_ref.path).endswith("review-2/export.json")
    assert str(mapping_ref.path).endswith("review-2/mapping.json")
    assert str(decision_ref.path).endswith("review-2/decisions/decision-1.json")
    replayed = {row.sample_id: row for row in replay.observations}
    assert replayed["n2"].predicted_process_valid is False
    assert replayed["n2"].predicted_first_error_step == 2
    assert replayed["n2"].predicted_taxonomy is ErrorTaxonomy.ALGORITHM_LOGIC
    assert replay.source_decision_set_id == "decision-1"
    assert (artifacts.root / "human-review/review-2/replays/replay-1.json").is_file()
    with pytest.raises(ArtifactExistsError):
        replay_decisions(
            artifacts,
            replay_id="replay-1",
            observations=literal_rows(),
            mapping=mapping,
            decision_set=decision_set,
        )
