from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_benchmark import config as benchmark_config

from hy3_algotrace.artifacts import ArtifactExistsError, ArtifactStore, sha256_json
from hy3_algotrace.benchmark_models import BenchmarkConfig
from hy3_algotrace.formal_lifecycle import CodeIdentity, SourceFileIdentity
from hy3_algotrace.nonformal_continuation import (
    NonformalResourceAuthorization,
    NonformalRunCarryover,
    assess_authorized_continuation,
    assess_chained_continuation,
    assess_continuation,
    build_successor_config,
    derive_chained_carryover,
    derive_conservative_carryover,
    verify_authorized_successor_package,
    verify_chained_successor_package,
    write_authorized_successor_package,
    write_chained_successor_package,
    write_continuation_bundle,
    write_successor_package,
)
from hy3_algotrace.prompts import (
    ADVERSARIAL_REVIEW_PROMPT_VERSION,
    ARBITER_PROMPT_VERSION,
    GENERATOR_PROMPT_VERSION,
    LOGIC_REVIEW_PROMPT_VERSION,
)


def predecessor(tmp_path: Path) -> tuple[ArtifactStore, NonformalRunCarryover]:
    store = ArtifactStore(tmp_path / "predecessor-artifacts")
    benchmark_id = "balanced75-old"
    event_refs = []
    for sequence, (operation, phase) in enumerate(
        (
            ("logic-dependency-review-v1", "request"),
            ("logic-dependency-review-v1", "schema_repair"),
            ("adversarial-review-v1", "request"),
            ("adversarial-review-v1", "schema_repair"),
        ),
        start=1,
    ):
        event_refs.append(
            store.write_json(
                Path("benchmarks") / benchmark_id / "ledger" / f"{sequence:06d}.json",
                {
                    "schema_version": "1.2",
                    "benchmark_id": benchmark_id,
                    "sequence": sequence,
                    "sample_id": "cf-1613-c-gold",
                    "operation": operation,
                    "phase": phase,
                    "retry_number": 1,
                },
            )
        )
    index_ref = store.write_json(
        Path("benchmarks") / benchmark_id / "ledger-index.json",
        {
            "schema_version": "1.2",
            "benchmark_id": benchmark_id,
            "event_paths": [str(ref.path) for ref in event_refs],
            "event_hashes": [ref.content_hash for ref in event_refs],
        },
    )
    failure_ref = store.write_json(
        Path("benchmarks") / benchmark_id / "failure.json",
        {
            "schema_version": "1.2",
            "status": "execution_failed",
            "formal_eligibility": False,
        },
    )
    manifest = NonformalRunCarryover(
        predecessor_benchmark_id=benchmark_id,
        successor_benchmark_id="balanced75-successor",
        predecessor_failure_hash=failure_ref.content_hash,
        predecessor_ledger_index_hash=index_ref.content_hash,
        predecessor_event_hashes=tuple(ref.content_hash for ref in event_refs),
        consumed_attempts=4,
        remote_attempt_limit=220,
        spend_limit_rmb="15",
        charged_upper_bound_rmb="15",
        cost_evidence="conservative_full_cap_unknown_usage",
        unknown_usage_attempts=(1, 2, 3, 4),
    )
    return store, manifest


def failed_authorized_successor(
    tmp_path: Path,
) -> tuple[ArtifactStore, ArtifactStore, ArtifactStore, BenchmarkConfig, CodeIdentity]:
    ancestor_store, old_manifest = predecessor(tmp_path)
    parent_manifest = old_manifest.model_copy(update={"successor_benchmark_id": "balanced75-v5"})
    authorization = NonformalResourceAuthorization(
        successor_benchmark_id="balanced75-v5",
        provider="TokenHub",
        model="hy3",
        free_token_limit=5_000_000,
        additional_spend_limit_rmb="15",
        evidence="user_attested_console_remaining_quota",
        billing_priority="free_quota_first",
        data_scope="public_codeforces_and_project_authored_trace_code",
    )
    source_file = SourceFileIdentity(path="src/example.py", byte_length=4, sha256="d" * 64)
    identity = CodeIdentity(
        head_revision="e" * 40,
        worktree_clean=False,
        files=(source_file,),
        tree_hash=sha256_json([source_file.model_dump(mode="json")]),
    )
    old_config = benchmark_config(
        benchmark_id="balanced75-old",
        sample_ids=("natural-1",),
        generation_ids=("natural-1",),
        audit_ids=("natural-1",),
        budget=220,
    )
    parent_config = build_successor_config(
        old_config,
        successor_benchmark_id="balanced75-v5",
        source_identity=identity,
    )
    parent_package = ArtifactStore(tmp_path / "parent-package")
    write_authorized_successor_package(
        parent_package,
        manifest=parent_manifest,
        authorization=authorization,
        predecessor_artifacts=ancestor_store,
        successor_config=parent_config,
        source_identity=identity,
    )

    latest_store = ArtifactStore(tmp_path / "latest-artifacts")
    root = Path("benchmarks/balanced75-v5")
    event_refs = []
    operations = (
        LOGIC_REVIEW_PROMPT_VERSION,
        ADVERSARIAL_REVIEW_PROMPT_VERSION,
        ARBITER_PROMPT_VERSION,
        LOGIC_REVIEW_PROMPT_VERSION,
        LOGIC_REVIEW_PROMPT_VERSION,
    )
    phases = ("request", "request", "request", "request", "schema_repair")
    for sequence, (operation, phase) in enumerate(zip(operations, phases, strict=True), start=5):
        event_refs.append(
            latest_store.write_json(
                root / "ledger" / f"{sequence:06d}.json",
                {
                    "schema_version": "1.2",
                    "benchmark_id": "balanced75-v5",
                    "sequence": sequence,
                    "sample_id": "natural-1",
                    "operation": operation,
                    "phase": phase,
                    "retry_number": 1,
                },
            )
        )
        charged_tokens = (sequence - 4) * 4_000
        charged_rmb = f"{(sequence - 4) / 100:.6f}"
        latest_store.write_json(
            root / "live-evidence/natural-1/attempts" / f"{sequence:06d}/settlement.json",
            {
                "schema_version": "1.0",
                "kind": "nonformal_hy3_attempt_settlement",
                "formal_eligibility": False,
                "sample_id": "natural-1",
                "attempt_sequence": sequence,
                "category": "accepted" if sequence < 9 else "validation_error",
                "http_status": 200,
                "finish_reason": "stop",
                "usage_status": "reported",
                "usage": {
                    "prompt_tokens": 2_000,
                    "completion_tokens": 2_000,
                    "total_tokens": 4_000,
                },
                "charged_attempt_upper_bound_rmb": "0.010000",
                "charged_upper_bound_rmb": charged_rmb,
                "remaining_upper_bound_rmb": f"{15 - (sequence - 4) / 100:.6f}",
                "charged_attempt_upper_bound_tokens": 4_000,
                "charged_upper_bound_tokens": charged_tokens,
                "remaining_upper_bound_tokens": 5_000_000 - charged_tokens,
                "validation_issues": (
                    [{"path": "per_step_reviews", "code": "unknown_step_id"}]
                    if sequence == 9
                    else []
                ),
            },
        )
    latest_store.write_json(
        root / "ledger-index.json",
        {
            "schema_version": "1.2",
            "benchmark_id": "balanced75-v5",
            "event_paths": [str(ref.path) for ref in event_refs],
            "event_hashes": [ref.content_hash for ref in event_refs],
        },
    )
    latest_store.write_json(
        root / "failure.json",
        {
            "schema_version": "1.2",
            "status": "execution_failed",
            "formal_eligibility": False,
        },
    )
    return ancestor_store, parent_package, latest_store, parent_config, identity


def test_unknown_predecessor_usage_consumes_full_shared_spend_cap_and_blocks(
    tmp_path: Path,
) -> None:
    store, manifest = predecessor(tmp_path)

    preflight = assess_continuation(manifest, predecessor_artifacts=store)

    assert preflight.predecessor_evidence_valid is True
    assert preflight.consumed_attempts == 4
    assert preflight.remaining_attempts == 216
    assert preflight.spend_limit_rmb == "15"
    assert preflight.charged_upper_bound_rmb == "15"
    assert preflight.remaining_upper_bound_rmb == "0"
    assert preflight.ready_for_remote_run is False
    assert preflight.block_reason == "spend_cap_exhausted_by_conservative_carryover"
    assert preflight.formal_eligibility is False


def test_carryover_refuses_undercharging_unknown_usage() -> None:
    with pytest.raises(ValueError, match="full spend cap"):
        NonformalRunCarryover(
            predecessor_benchmark_id="old",
            successor_benchmark_id="new",
            predecessor_failure_hash="a" * 64,
            predecessor_ledger_index_hash="b" * 64,
            predecessor_event_hashes=("c" * 64,),
            consumed_attempts=1,
            remote_attempt_limit=220,
            spend_limit_rmb="15",
            charged_upper_bound_rmb="0.5",
            cost_evidence="conservative_full_cap_unknown_usage",
            unknown_usage_attempts=(1,),
        )


def test_successor_config_changes_identity_and_source_prompts_but_not_sample_plan(
    tmp_path: Path,
) -> None:
    predecessor_store, expected_manifest = predecessor(tmp_path)
    derived = derive_conservative_carryover(
        predecessor_artifacts=predecessor_store,
        predecessor_benchmark_id="balanced75-old",
        successor_benchmark_id="balanced75-successor",
        remote_attempt_limit=220,
        spend_limit_rmb="15",
    )
    assert derived == expected_manifest

    source_file = SourceFileIdentity(path="src/example.py", byte_length=4, sha256="d" * 64)
    identity = CodeIdentity(
        head_revision="e" * 40,
        worktree_clean=False,
        files=(source_file,),
        tree_hash=sha256_json([source_file.model_dump(mode="json")]),
    )
    predecessor_config = benchmark_config(
        benchmark_id="balanced75-old",
        sample_ids=("natural-1",),
        generation_ids=("natural-1",),
        audit_ids=("natural-1",),
        budget=220,
    )

    successor = build_successor_config(
        predecessor_config,
        successor_benchmark_id="balanced75-successor",
        source_identity=identity,
    )

    assert successor.benchmark_id == "balanced75-successor"
    assert successor.ordered_sample_ids == predecessor_config.ordered_sample_ids
    assert successor.sample_specs == predecessor_config.sample_specs
    assert successor.remote_attempt_budget == 220
    assert successor.formal is False
    assert successor.code_revision == f"{'e' * 40}+dirty-{identity.tree_hash}"
    assert (
        successor.generator_prompt_version,
        successor.logic_review_prompt_version,
        successor.adversarial_review_prompt_version,
        successor.arbiter_prompt_version,
    ) == (
        GENERATOR_PROMPT_VERSION,
        LOGIC_REVIEW_PROMPT_VERSION,
        ADVERSARIAL_REVIEW_PROMPT_VERSION,
        ARBITER_PROMPT_VERSION,
    )

    output = ArtifactStore(tmp_path / "package")
    refs = write_successor_package(
        output,
        manifest=derived,
        predecessor_artifacts=predecessor_store,
        successor_config=successor,
        source_identity=identity,
    )
    assert [ref.path.name for ref in refs] == [
        "source-identity.json",
        "config.json",
        "carryover.json",
        "preflight.json",
    ]
    preflight = output.read_json("preflight.json")
    assert preflight["successor_config_hash"] == sha256_json(successor.model_dump(mode="json"))
    assert preflight["source_tree_hash"] == identity.tree_hash
    assert preflight["ready_for_remote_run"] is False


def test_carryover_rejects_tampered_predecessor_event(tmp_path: Path) -> None:
    store, manifest = predecessor(tmp_path)
    event = tmp_path / "predecessor-artifacts/benchmarks/balanced75-old/ledger/000004.json"
    event.write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="event hash"):
        assess_continuation(manifest, predecessor_artifacts=store)


def test_continuation_bundle_is_create_only(tmp_path: Path) -> None:
    predecessor_store, manifest = predecessor(tmp_path)
    output = ArtifactStore(tmp_path / "successor")

    refs = write_continuation_bundle(
        output,
        manifest=manifest,
        predecessor_artifacts=predecessor_store,
    )

    assert [ref.path.name for ref in refs] == ["carryover.json", "preflight.json"]
    with pytest.raises(ArtifactExistsError):
        write_continuation_bundle(
            output,
            manifest=manifest,
            predecessor_artifacts=predecessor_store,
        )


def test_user_attested_free_tokens_create_separate_bounded_ready_authorization(
    tmp_path: Path,
) -> None:
    predecessor_store, old_manifest = predecessor(tmp_path)
    manifest = old_manifest.model_copy(update={"successor_benchmark_id": "balanced75-v5"})
    authorization = NonformalResourceAuthorization(
        successor_benchmark_id="balanced75-v5",
        provider="TokenHub",
        model="hy3",
        free_token_limit=5_000_000,
        additional_spend_limit_rmb="15",
        evidence="user_attested_console_remaining_quota",
        billing_priority="free_quota_first",
        data_scope="public_codeforces_and_project_authored_trace_code",
    )

    preflight = assess_authorized_continuation(
        manifest,
        authorization=authorization,
        predecessor_artifacts=predecessor_store,
    )

    assert preflight.ready_for_remote_run is True
    assert preflight.block_reason is None
    assert preflight.consumed_attempts == 4
    assert preflight.remaining_attempts == 216
    assert preflight.historical_charged_upper_bound_rmb == "15"
    assert preflight.free_token_limit == 5_000_000
    assert preflight.additional_spend_limit_rmb == "15"
    assert preflight.formal_eligibility is False


def test_authorized_successor_package_is_create_only_and_identity_bound(tmp_path: Path) -> None:
    predecessor_store, old_manifest = predecessor(tmp_path)
    manifest = old_manifest.model_copy(update={"successor_benchmark_id": "balanced75-v5"})
    authorization = NonformalResourceAuthorization(
        successor_benchmark_id="balanced75-v5",
        provider="TokenHub",
        model="hy3",
        free_token_limit=5_000_000,
        additional_spend_limit_rmb="15",
        evidence="user_attested_console_remaining_quota",
        billing_priority="free_quota_first",
        data_scope="public_codeforces_and_project_authored_trace_code",
    )
    source_file = SourceFileIdentity(path="src/example.py", byte_length=4, sha256="d" * 64)
    identity = CodeIdentity(
        head_revision="e" * 40,
        worktree_clean=False,
        files=(source_file,),
        tree_hash=sha256_json([source_file.model_dump(mode="json")]),
    )
    old_config = benchmark_config(
        benchmark_id="balanced75-old",
        sample_ids=("natural-1",),
        generation_ids=("natural-1",),
        audit_ids=("natural-1",),
        budget=220,
    )
    successor = build_successor_config(
        old_config,
        successor_benchmark_id="balanced75-v5",
        source_identity=identity,
    )
    output = ArtifactStore(tmp_path / "authorized-package")

    refs = write_authorized_successor_package(
        output,
        manifest=manifest,
        authorization=authorization,
        predecessor_artifacts=predecessor_store,
        successor_config=successor,
        source_identity=identity,
    )

    assert [ref.path.name for ref in refs] == [
        "source-identity.json",
        "config.json",
        "carryover.json",
        "authorization.json",
        "preflight.json",
    ]
    preflight = output.read_json("preflight.json")
    assert preflight["successor_config_hash"] == sha256_json(successor.model_dump(mode="json"))
    assert preflight["source_identity_hash"] == sha256_json(identity.model_dump(mode="json"))
    assert preflight["authorization_hash"] == sha256_json(authorization.model_dump(mode="json"))
    verified = verify_authorized_successor_package(
        package_root=output.root,
        predecessor_artifacts=predecessor_store,
        successor_config=successor,
        current_source_identity=identity,
    )
    assert verified.ready_for_remote_run is True
    assert verified.consumed_attempts == 4
    assert verified.free_token_limit == 5_000_000
    with pytest.raises(ArtifactExistsError):
        write_authorized_successor_package(
            output,
            manifest=manifest,
            authorization=authorization,
            predecessor_artifacts=predecessor_store,
            successor_config=successor,
            source_identity=identity,
        )


def test_authorized_successor_runtime_verification_rejects_tampered_preflight(
    tmp_path: Path,
) -> None:
    predecessor_store, old_manifest = predecessor(tmp_path)
    manifest = old_manifest.model_copy(update={"successor_benchmark_id": "balanced75-v5"})
    authorization = NonformalResourceAuthorization(
        successor_benchmark_id="balanced75-v5",
        provider="TokenHub",
        model="hy3",
        free_token_limit=5_000_000,
        additional_spend_limit_rmb="15",
        evidence="user_attested_console_remaining_quota",
        billing_priority="free_quota_first",
        data_scope="public_codeforces_and_project_authored_trace_code",
    )
    source_file = SourceFileIdentity(path="src/example.py", byte_length=4, sha256="d" * 64)
    identity = CodeIdentity(
        head_revision="e" * 40,
        worktree_clean=False,
        files=(source_file,),
        tree_hash=sha256_json([source_file.model_dump(mode="json")]),
    )
    old_config = benchmark_config(
        benchmark_id="balanced75-old",
        sample_ids=("natural-1",),
        generation_ids=("natural-1",),
        audit_ids=("natural-1",),
        budget=220,
    )
    successor = build_successor_config(
        old_config,
        successor_benchmark_id="balanced75-v5",
        source_identity=identity,
    )
    output = ArtifactStore(tmp_path / "authorized-package")
    write_authorized_successor_package(
        output,
        manifest=manifest,
        authorization=authorization,
        predecessor_artifacts=predecessor_store,
        successor_config=successor,
        source_identity=identity,
    )
    preflight_path = output.root / "preflight.json"
    preflight = output.read_json("preflight.json")
    preflight["free_token_limit"] = 4_999_999
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")

    with pytest.raises(ValueError, match="preflight"):
        verify_authorized_successor_package(
            package_root=output.root,
            predecessor_artifacts=predecessor_store,
            successor_config=successor,
            current_source_identity=identity,
        )


def test_chained_carryover_binds_ancestor_and_latest_ledgers_and_reported_usage(
    tmp_path: Path,
) -> None:
    ancestor, parent_package, latest, parent_config, identity = failed_authorized_successor(
        tmp_path
    )

    manifest = derive_chained_carryover(
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
        latest_benchmark_id="balanced75-v5",
        successor_benchmark_id="balanced75-v6",
    )
    preflight = assess_chained_continuation(
        manifest,
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
    )

    assert manifest.ancestor_benchmark_id == "balanced75-old"
    assert manifest.predecessor_benchmark_id == "balanced75-v5"
    assert manifest.parent_consumed_attempts == 4
    assert manifest.consumed_attempts == 9
    assert len(manifest.predecessor_event_hashes) == 5
    assert [item.sequence for item in manifest.settlements] == [5, 6, 7, 8, 9]
    assert manifest.resource_token_limit == 5_000_000
    assert manifest.resource_charged_upper_bound_tokens == 20_000
    assert manifest.resource_spend_limit_rmb == "15"
    assert manifest.resource_charged_upper_bound_rmb == "0.050000"
    assert preflight.predecessor_evidence_valid is True
    assert preflight.consumed_attempts == 9
    assert preflight.remaining_attempts == 211
    assert preflight.remaining_upper_bound_tokens == 4_980_000
    assert preflight.remaining_upper_bound_rmb == "14.950000"
    assert preflight.ready_for_remote_run is False
    assert preflight.block_reason == "explicit_remote_reapproval_required"

    successor = build_successor_config(
        parent_config,
        successor_benchmark_id="balanced75-v6",
        source_identity=identity,
    )
    output = ArtifactStore(tmp_path / "chained-package")
    refs = write_chained_successor_package(
        output,
        manifest=manifest,
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
        successor_config=successor,
        source_identity=identity,
    )

    assert [ref.path.name for ref in refs] == [
        "source-identity.json",
        "config.json",
        "carryover.json",
        "authorization.json",
        "preflight.json",
    ]
    verified = verify_chained_successor_package(
        package_root=output.root,
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
        successor_config=successor,
        current_source_identity=identity,
    )
    assert verified == preflight.model_copy(
        update={
            "successor_config_hash": sha256_json(successor.model_dump(mode="json")),
            "source_identity_hash": sha256_json(identity.model_dump(mode="json")),
            "source_tree_hash": identity.tree_hash,
            "carryover_hash": sha256_json(manifest.model_dump(mode="json")),
            "authorization_hash": sha256_json(output.read_json("authorization.json")),
        }
    )
    with pytest.raises(ArtifactExistsError):
        write_chained_successor_package(
            output,
            manifest=manifest,
            parent_package_root=parent_package.root,
            ancestor_artifacts=ancestor,
            latest_artifacts=latest,
            successor_config=successor,
            source_identity=identity,
        )


def test_chained_carryover_rejects_tampered_latest_settlement(tmp_path: Path) -> None:
    ancestor, parent_package, latest, _, _ = failed_authorized_successor(tmp_path)
    manifest = derive_chained_carryover(
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
        latest_benchmark_id="balanced75-v5",
        successor_benchmark_id="balanced75-v6",
    )
    settlement = next(latest.root.rglob("000009/settlement.json"))
    settlement.write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="settlement"):
        assess_chained_continuation(
            manifest,
            parent_package_root=parent_package.root,
            ancestor_artifacts=ancestor,
            latest_artifacts=latest,
        )


def test_chained_carryover_rechecks_ancestor_hashes(tmp_path: Path) -> None:
    ancestor, parent_package, latest, _, _ = failed_authorized_successor(tmp_path)
    manifest = derive_chained_carryover(
        parent_package_root=parent_package.root,
        ancestor_artifacts=ancestor,
        latest_artifacts=latest,
        latest_benchmark_id="balanced75-v5",
        successor_benchmark_id="balanced75-v6",
    )
    event = ancestor.root / "benchmarks/balanced75-old/ledger/000004.json"
    event.write_text('{"tampered":true}', encoding="utf-8")

    with pytest.raises(ValueError, match="event hash"):
        assess_chained_continuation(
            manifest,
            parent_package_root=parent_package.root,
            ancestor_artifacts=ancestor,
            latest_artifacts=latest,
        )
