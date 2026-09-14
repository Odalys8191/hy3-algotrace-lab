from __future__ import annotations

import copy
import json
import pickle
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_dataset_corpus import (
    _bundle_entries,
    _controlled_samples,
    _natural_config,
    _selection,
)

from hy3_algotrace import formal_lifecycle as lifecycle
from hy3_algotrace.artifacts import sha256_bytes
from hy3_algotrace.corpus import (
    CorpusSampleKind,
    CorpusStatus,
    NaturalRunConfig,
    build_corpus_manifest,
    build_project_bundle_manifest,
)
from hy3_algotrace.prompts import GENERATOR_PROMPT_VERSION, GENERATOR_SYSTEM_PROMPT

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "sha256:" + "c" * 64


def pending(root: Path):
    selection = _selection()
    bundles = build_project_bundle_manifest(selection, _bundle_entries(root, selection))
    original = _controlled_samples(root, selection, bundles)
    controlled = tuple(x for x in original if x.kind is not CorpusSampleKind.PARADOX)
    from test_dataset_corpus import _sample

    paradox = tuple(
        _sample(
            root,
            sample_id=f"{entry.problem_id}-paradox-plan",
            problem_id=entry.problem_id,
            kind=CorpusSampleKind.PARADOX,
            code_text=(root / bundle.reference_cpp.path).read_text(),
        )
        for entry, bundle in zip(selection.entries[::2], bundles.bundles[::2], strict=True)
    )
    natural_payload = _natural_config(selection).model_dump(mode="json")
    natural_payload.update(
        model_name="hy3",
        endpoint_url=lifecycle.FORMAL_ENDPOINT,
        prompt_version=GENERATOR_PROMPT_VERSION,
        prompt_hash=sha256_bytes(GENERATOR_SYSTEM_PROMPT.encode()),
    )
    natural_payload.pop("content_hash")
    from hy3_algotrace.artifacts import sha256_json

    natural = NaturalRunConfig.model_validate_json(
        json.dumps(natural_payload | {"content_hash": sha256_json(natural_payload)})
    )
    corpus = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundles,
        samples=controlled + paradox,
        natural_run_config=natural,
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    return selection, bundles, corpus


def freeze(root: Path):
    selection, bundles, corpus = pending(root)
    result = lifecycle.freeze_pre_run_intent(
        selection=selection,
        pending_corpus=corpus,
        bundle_manifest=bundles,
        data_root=root,
        repo_root=ROOT,
        recorded_at=datetime(2026, 9, 11, tzinfo=UTC),
        slug="lifecycle",
        judge_image_digest=DIGEST,
    )
    return result, selection, bundles, corpus


def test_a_freezes_actual_105_plus_reserved_60_without_placeholder_traces(tmp_path: Path):
    intent, selection, bundles, corpus = freeze(tmp_path)
    assert len(intent.planned_samples) == 165
    assert len(intent.natural_sample_ids) == 60
    assert intent.pending_corpus_hash == corpus.content_hash
    assert intent.code_identity.worktree_clean is False
    assert '"trace":' not in intent.model_dump_json()
    assert intent.selection_manifest_hash == selection.content_hash
    lifecycle.verify_pre_run_intent(intent, repo_root=ROOT)
    with pytest.raises(ValueError):
        lifecycle.PreRunIntent.model_validate_json(
            intent.model_dump_json().replace(corpus.content_hash, "0" * 64)
        )


def test_a_refuses_tampered_controlled_bytes_before_freeze(tmp_path: Path):
    selection, bundles, corpus = pending(tmp_path)
    (tmp_path / corpus.samples[0].cpp_source.path).write_text("placeholder")
    with pytest.raises(ValueError):
        lifecycle.freeze_pre_run_intent(
            selection=selection,
            pending_corpus=corpus,
            bundle_manifest=bundles,
            data_root=tmp_path,
            repo_root=ROOT,
            recorded_at=datetime.now(UTC),
            slug="changed",
            judge_image_digest=DIGEST,
        )


def test_gate_refuses_missing_a_timeout_code_and_deserialized_receipt(tmp_path: Path):
    intent, _, _, _ = freeze(tmp_path)
    runtime = dict(
        model="hy3",
        endpoint_identity=lifecycle.FORMAL_ENDPOINT,
        timeout_seconds=600,
        judge_image_digest=DIGEST,
    )
    with pytest.raises(ValueError, match="pre-run"):
        lifecycle.verify_pre_run_intent(None, repo_root=ROOT)
    capability = lifecycle.verify_pre_run_intent(intent, repo_root=ROOT)
    lifecycle.assert_formal_runtime(capability, **runtime)
    with pytest.raises(ValueError, match="timeout"):
        lifecycle.assert_formal_runtime(capability, **(runtime | {"timeout_seconds": 60}))
    with pytest.raises(TypeError):
        pickle.dumps(capability)
    with pytest.raises(TypeError):
        copy.copy(capability)
    with pytest.raises(ValueError):
        lifecycle.assert_formal_runtime(intent.model_dump(mode="json"), **runtime)
    bad = intent.model_copy(
        update={"code_identity": intent.code_identity.model_copy(update={"tree_hash": "0" * 64})}
    )
    with pytest.raises(ValueError):
        lifecycle.verify_pre_run_intent(bad, repo_root=ROOT)


def test_source_identity_tracks_uncommitted_sources_and_does_not_read_env(tmp_path: Path):
    # HEAD is read from the real repository, while isolated source-byte changes
    # are tested through the exact inventory helper used by code identity.
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "module.py"
    source.write_text("x = 1\n")
    (tmp_path / ".env").write_text("never inspect this value")
    before = lifecycle.source_tree_inventory(tmp_path)
    assert all(".env" not in item.path for item in before)
    source.write_text("x = 2\n")
    assert before != lifecycle.source_tree_inventory(tmp_path)


@pytest.mark.parametrize("missing_stage", ["pre_run_intent_path", "materialized_freeze_path"])
def test_formal_qualification_refuses_missing_a_or_b(tmp_path: Path, missing_stage: str):
    from test_formal_qualification import _build_fixture

    from hy3_algotrace.formal_qualification import (
        FormalQualificationError,
        FormalQualificationInputs,
        qualify_formal_run,
    )

    fixture = _build_fixture(tmp_path)
    inputs = dict(fixture.inputs)
    inputs[missing_stage] = None
    with pytest.raises(FormalQualificationError):
        qualify_formal_run(FormalQualificationInputs(**inputs))


def test_formal_generator_checks_a_before_any_transport(tmp_path: Path):
    import httpx

    from hy3_algotrace.artifacts import ArtifactStore
    from hy3_algotrace.formal_generation import FormalNaturalGenerator
    from hy3_algotrace.hy3_client import Hy3Config

    intent, selection, bundles, corpus = freeze(tmp_path)
    calls = []
    transport = httpx.MockTransport(lambda request: calls.append(request))
    with pytest.raises(ValueError):
        FormalNaturalGenerator(
            intent=None,
            selection=selection,
            pending_corpus=corpus,
            bundle_manifest=bundles,
            data_root=tmp_path,
            repo_root=ROOT,
            artifacts=ArtifactStore(tmp_path / "run"),
            hy3_config=Hy3Config(
                base_url=lifecycle.FORMAL_ENDPOINT,
                **{"api_key": "placeholder"},
                model="hy3",
                timeout_seconds=600,
            ),
            judge_image_digest=DIGEST,
            transport=transport,
        )
    assert calls == []
