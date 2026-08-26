from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

import hy3_algotrace.dataset_models as dataset_models
from hy3_algotrace.artifacts import canonical_json_bytes, sha256_json
from hy3_algotrace.catalog import problem_content_hash
from hy3_algotrace.contracts import (
    ErrorTaxonomy,
    JudgeEvidence,
    JudgeStatus,
    PerTestEvidence,
    ProblemOracle,
    ProblemRecord,
    RatingBand,
    ReasoningStage,
    ReasoningStep,
    SolutionTrace,
    StepStatus,
    Topic,
)
from hy3_algotrace.contracts import TestCase as ContractTestCase
from hy3_algotrace.corpus import (
    ArtifactMediaType,
    ArtifactProvenance,
    ArtifactRef,
    AuthoredBundleEntry,
    AuthoringAttestation,
    CorpusDataError,
    CorpusManifest,
    CorpusSample,
    CorpusSampleKind,
    CorpusStatus,
    FrozenModelParameter,
    NaturalRunConfig,
    NaturalRunStatus,
    ProjectBundleManifest,
    build_corpus_manifest,
    build_project_bundle_manifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from hy3_algotrace.dataset_models import (
    AcquisitionAsset,
    AcquisitionManifest,
    CandidateReview,
    CandidateReviewArtifact,
    CandidateReviewSet,
    CheckerKind,
    ConversionTool,
    DatasetFormat,
    FrozenSelectionEntry,
    FrozenSelectionManifest,
    ReviewArtifactAsset,
    ReviewArtifactManifest,
    VerifiedSelectionChain,
    build_quota_report,
    convert_codecontests_file,
    freeze_selection,
    validate_acquired_assets,
    verify_frozen_selection_chain,
)
from hy3_algotrace.differential import (
    DifferentialDataError,
    FormalCorpusJudgeValidationReport,
    FormalCorpusJudgeValidationResult,
    JudgeCaseKind,
    JudgeSourceCase,
    validate_formal_corpus_judge_cases,
    validate_persisted_formal_judge_evidence,
)


def _problem_record(
    *,
    problem_id: str,
    source_split: Literal["validation", "test"],
    topic: Topic,
    rating: int,
    hidden_input_data: str = "2\n",
) -> ProblemRecord:
    contest_id = int(problem_id.split("-")[1])
    topic_tag = {
        Topic.CONSTRUCTION_SIMULATION: "implementation",
        Topic.GREEDY: "greedy",
        Topic.BINARY_SEARCH: "binary search",
        Topic.DYNAMIC_PROGRAMMING: "dp",
        Topic.GRAPH: "graphs",
    }[topic]
    provisional = ProblemRecord(
        problem_id=problem_id,
        title=f"Problem {contest_id}",
        statement_en="Print the input integer.",
        source_url=f"https://codeforces.com/problemset/problem/{contest_id}/A",
        attribution=(
            f"Codeforces problem {contest_id}A; metadata imported from "
            f"CodeContests {source_split} split."
        ),
        cf_contest_id=contest_id,
        cf_index="A",
        cf_tags=(topic_tag,),
        source_split=source_split,
        topic=topic,
        rating=rating,
        time_limit_ms=1000,
        memory_limit_mb=256,
        public_tests=(
            ContractTestCase(test_id="public-1", input_data="1\n", expected_output="1\n"),
        ),
        hidden_tests=(
            ContractTestCase(
                test_id="hidden-1",
                input_data=hidden_input_data,
                expected_output="2\n",
            ),
        ),
        generated_tests=(
            ContractTestCase(test_id="generated-1", input_data="3\n", expected_output="3\n"),
        ),
        content_hash="0" * 64,
    )
    return provisional.model_copy(update={"content_hash": problem_content_hash(provisional)})


def _selection(*, hidden_input_data: str = "2\n") -> FrozenSelectionManifest:
    entries: list[FrozenSelectionEntry] = []
    number = 5000
    for topic in Topic:
        for band, rating in (
            (RatingBand.FOUNDATION, 1300),
            (RatingBand.INTERMEDIATE, 1700),
            (RatingBand.ADVANCED, 2100),
        ):
            for _ in range(2):
                problem_id = f"cf-{number}-a"
                source_split = "validation" if number % 2 == 0 else "test"
                record = _problem_record(
                    problem_id=problem_id,
                    source_split=source_split,
                    topic=topic,
                    rating=rating,
                    hidden_input_data=hidden_input_data,
                )
                entries.append(
                    FrozenSelectionEntry(
                        problem_id=problem_id,
                        source_split=source_split,
                        topic=topic,
                        rating_band=band,
                        rating=rating,
                        raw_row_hash="a" * 64,
                        record_hash=sha256_json(record.model_dump(mode="json")),
                        review_hash="c" * 64,
                    )
                )
                number += 1
    payload = {
        "schema_version": "1.2",
        "kind": "formal_codecontests_selection_v2",
        "acquisition_manifest_hash": "d" * 64,
        "acquisition_validation_hash": "9" * 64,
        "quota_report_hash": "e" * 64,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    return FrozenSelectionManifest(
        acquisition_manifest_hash="d" * 64,
        acquisition_validation_hash="9" * 64,
        quota_report_hash="e" * 64,
        entries=tuple(entries),
        content_hash=sha256_json(payload),
    )


def _verified_selection_chain(
    root: Path,
    *,
    hidden_input_data: str = "2\n",
) -> tuple[VerifiedSelectionChain, dict[str, ProblemRecord]]:
    template = _selection(hidden_input_data=hidden_input_data)
    rows: dict[str, list[dict[str, object]]] = {"validation": [], "test": []}
    reviews: dict[str, list[CandidateReview]] = {"validation": [], "test": []}
    records: dict[str, ProblemRecord] = {}
    topic_tags = {
        Topic.CONSTRUCTION_SIMULATION: "implementation",
        Topic.GREEDY: "greedy",
        Topic.BINARY_SEARCH: "binary search",
        Topic.DYNAMIC_PROGRAMMING: "dp",
        Topic.GRAPH: "graphs",
    }
    for entry in template.entries:
        contest_id = int(entry.problem_id.split("-")[1])
        records[entry.problem_id] = _problem_record(
            problem_id=entry.problem_id,
            source_split=entry.source_split,
            topic=entry.topic,
            rating=entry.rating,
            hidden_input_data=hidden_input_data,
        )
        rows[entry.source_split].append(
            {
                "name": f"Problem {contest_id}",
                "description": "Print the input integer.",
                "source": 2,
                "cf_contest_id": contest_id,
                "cf_index": "A",
                "cf_rating": entry.rating,
                "cf_tags": [topic_tags[entry.topic]],
                "is_description_translated": False,
                "untranslated_description": "",
                "time_limit": {"seconds": "1", "nanos": 0},
                "memory_limit_bytes": 268435456,
                "input_file": "",
                "output_file": "",
                "public_tests": [{"input": "1\n", "output": "1\n"}],
                "private_tests": [{"input": hidden_input_data, "output": "2\n"}],
                "generated_tests": [{"input": "3\n", "output": "3\n"}],
            }
        )
        reviews[entry.source_split].append(
            CandidateReview(
                problem_id=entry.problem_id,
                checker_reviewed=True,
                checker_kind=CheckerKind.STANDARD,
                reviewer="formal-chain-curator",
                reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
                evidence_url=f"https://codeforces.com/problemset/problem/{contest_id}/A",
            )
        )
    paths = {split: root / f"formal-chain-{split}.json" for split in ("validation", "test")}
    for split in ("validation", "test"):
        paths[split].write_text(json.dumps(rows[split]), encoding="utf-8")
    converter = ConversionTool(name="formal-chain-json", version="1")
    assets = tuple(
        AcquisitionAsset(
            split=split,
            url=f"https://example.invalid/codecontests-{split}.json",
            byte_length=len(paths[split].read_bytes()),
            sha256=hashlib.sha256(paths[split].read_bytes()).hexdigest(),
            license="CC-BY-4.0 plus third-party terms",
            attribution="Google DeepMind CodeContests and Codeforces",
        )
        for split in ("validation", "test")
    )
    acquisition = AcquisitionManifest(
        dataset="google-deepmind/code_contests",
        assets=assets,
        converter=converter,
        third_party_terms_acknowledged=True,
    )
    acquisition_validation = validate_acquired_assets(
        acquisition,
        paths,
    )
    review_sets: dict[str, CandidateReviewSet] = {}
    review_paths = {
        split: root / f"formal-chain-reviews-{split}.json" for split in ("validation", "test")
    }
    for split in ("validation", "test"):
        artifacts = tuple(
            CandidateReviewArtifact.create(
                raw_row_hash=sha256_json(row),
                review=review,
            )
            for row, review in zip(rows[split], reviews[split], strict=True)
        )
        review_sets[split] = CandidateReviewSet.create(split=split, artifacts=artifacts)
        review_paths[split].write_bytes(
            canonical_json_bytes(review_sets[split].model_dump(mode="json"))
        )
    review_manifest = ReviewArtifactManifest.create(
        tuple(
            ReviewArtifactAsset(
                split=split,
                logical_id=f"codecontests-review-{split}",
                byte_length=len(review_paths[split].read_bytes()),
                sha256=hashlib.sha256(review_paths[split].read_bytes()).hexdigest(),
            )
            for split in ("validation", "test")
        )
    )
    conversions = tuple(
        convert_codecontests_file(
            paths[split],
            split=split,
            data_format=DatasetFormat.JSON,
            reviews=review_sets[split].artifacts,
            converter=converter,
            acquisition_validation=acquisition_validation,
        )
        for split in ("validation", "test")
    )
    quota = build_quota_report(conversions)
    selection = freeze_selection(
        tuple(records),
        conversions=conversions,
        quota=quota,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    chain = verify_frozen_selection_chain(
        selection.model_dump(mode="json"),
        raw_asset_paths=paths,
        data_formats={
            "validation": DatasetFormat.JSON,
            "test": DatasetFormat.JSON,
        },
        review_artifact_paths=review_paths,
        review_manifest=review_manifest,
        acquisition=acquisition,
        acquisition_validation=acquisition_validation,
    )
    return chain, records


def _write_ref(
    root: Path,
    relative: str,
    content: bytes,
    media_type: ArtifactMediaType,
    provenance: ArtifactProvenance = ArtifactProvenance.PROJECT_AUTHORED,
) -> ArtifactRef:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return ArtifactRef(
        path=relative,
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        provenance=provenance,
    )


def _bundle_entries(
    root: Path, selection: FrozenSelectionManifest
) -> tuple[AuthoredBundleEntry, ...]:
    entries: list[AuthoredBundleEntry] = []
    for selected in selection.entries:
        prefix = f"problems/{selected.problem_id}"
        reference_text = "// project authored\nint main() { return 0; }\n"
        reference = _write_ref(
            root,
            f"{prefix}/reference.cpp",
            reference_text.encode(),
            ArtifactMediaType.CPP,
        )
        oracle_value = ProblemOracle(
            problem_id=selected.problem_id,
            accepted_algorithm_families=("identity",),
            key_invariants=("The output equals the input.",),
            complexity_ceiling="O(1)",
            known_traps=("Whitespace does not change the value.",),
            adversarial_cases=("0",),
            decisive_facts=("There is one input value.",),
            reference_solution_hash=sha256_json(reference_text),
        )
        oracle = _write_ref(
            root,
            f"{prefix}/oracle.json",
            canonical_json_bytes(oracle_value.model_dump(mode="json")),
            ArtifactMediaType.JSON,
        )
        gold_value = _trace(
            trace_id=f"{selected.problem_id}-gold",
            problem_id=selected.problem_id,
            code=reference_text,
            step_id="algorithm-1",
            step_status=StepStatus.CORRECT,
        )
        gold = _write_ref(
            root,
            f"{prefix}/gold_trace.json",
            canonical_json_bytes(gold_value.model_dump(mode="json")),
            ArtifactMediaType.JSON,
        )
        mutants = tuple(
            _write_ref(
                root,
                f"{prefix}/mutant-{index}.cpp",
                f"// project mutant {index}\nint main() {{ return {index}; }}\n".encode(),
                ArtifactMediaType.CPP,
            )
            for index in (1, 2)
        )
        entries.append(
            AuthoredBundleEntry(
                problem_id=selected.problem_id,
                selection_entry_hash=sha256_json(selected.model_dump(mode="json")),
                reference_cpp=reference,
                oracle=oracle,
                gold_trace=gold,
                mutants=mutants,
                authoring_attestation=AuthoringAttestation.create(
                    reviewer="project-reviewer",
                    reviewed_at=datetime(2026, 8, 23, tzinfo=UTC),
                    evidence_logical_id=f"review-{selected.problem_id}",
                    evidence_sha256=sha256_json(f"human review evidence:{selected.problem_id}"),
                    source_provenance="project_authored_no_submitted_code",
                    source_provenance_sha256=sha256_json(
                        f"project source provenance:{selected.problem_id}"
                    ),
                ),
                third_party_submitted_code_included=False,
            )
        )
    return tuple(entries)


def _trace(
    *,
    trace_id: str,
    problem_id: str,
    code: str,
    step_id: str,
    step_status: StepStatus,
) -> SolutionTrace:
    return SolutionTrace(
        trace_id=trace_id,
        problem_id=problem_id,
        steps=(
            ReasoningStep(
                step_id=step_id,
                step_number=1,
                stage=ReasoningStage.ALGORITHM_DESIGN,
                claim="Use the identity operation.",
                rationale="The required output equals the input.",
                status=step_status,
            ),
        ),
        problem_understanding="Print the input value.",
        algorithm="Return the value unchanged.",
        correctness_argument="Identity preserves the requested value.",
        time_complexity="O(1)",
        space_complexity="O(1)",
        edge_cases=("Zero is preserved.",),
        code=code,
    )


def _natural_config(selection: FrozenSelectionManifest) -> NaturalRunConfig:
    problem_ids = tuple(entry.problem_id for entry in selection.entries)
    return NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=problem_ids,
        prompt_version="natural-v1",
        prompt_hash="f" * 64,
        model_name="hy3-formal-model",
        endpoint_url="https://api.example.invalid/v1",
        model_parameters=(
            FrozenModelParameter(name="temperature", value=0.2),
            FrozenModelParameter(name="max_tokens", value=4096),
        ),
        credential_env_var="HY3_API_KEY",
        status=NaturalRunStatus.PENDING_CREDENTIALS,
        pending_reason="Formal Hy3 credentials are not available.",
    )


def _sample(
    root: Path,
    *,
    sample_id: str,
    problem_id: str,
    kind: CorpusSampleKind,
    code_text: str | None = None,
) -> CorpusSample:
    provenance = (
        ArtifactProvenance.HY3_OUTPUT
        if kind is CorpusSampleKind.NATURAL
        else ArtifactProvenance.PROJECT_AUTHORED
    )
    prefix = f"corpus/{kind.value}/{sample_id}"
    step_id = "algorithm-1"
    step_status = StepStatus.CORRECT
    if kind is CorpusSampleKind.CONTROLLED_WRONG:
        step_status = StepStatus.INCORRECT
    elif kind is CorpusSampleKind.PARADOX:
        step_id = "proof-1"
        step_status = StepStatus.UNSUPPORTED
    marker = {
        CorpusSampleKind.GOLD: "gold",
        CorpusSampleKind.CONTROLLED_WRONG: "mutant",
        CorpusSampleKind.PARADOX: "paradox",
        CorpusSampleKind.NATURAL: "natural",
    }[kind]
    if code_text is None:
        code_text = f"// {marker}\nint main() {{ return 0; }}\n"
    trace_value = _trace(
        trace_id=sample_id,
        problem_id=problem_id,
        code=code_text,
        step_id=step_id,
        step_status=step_status,
    )
    trace = _write_ref(
        root,
        f"{prefix}.json",
        canonical_json_bytes(trace_value.model_dump(mode="json")),
        ArtifactMediaType.JSON,
        provenance,
    )
    code = _write_ref(
        root,
        f"{prefix}.cpp",
        code_text.encode(),
        ArtifactMediaType.CPP,
        provenance,
    )
    if kind is CorpusSampleKind.GOLD:
        return CorpusSample(
            sample_id=sample_id,
            problem_id=problem_id,
            kind=kind,
            trace=trace,
            cpp_source=code,
            final_expected_correct=True,
        )
    if kind is CorpusSampleKind.CONTROLLED_WRONG:
        return CorpusSample(
            sample_id=sample_id,
            problem_id=problem_id,
            kind=kind,
            trace=trace,
            cpp_source=code,
            final_expected_correct=False,
            primary_error=ErrorTaxonomy.ALGORITHM_LOGIC,
            first_error_step_id="algorithm-1",
        )
    if kind is CorpusSampleKind.PARADOX:
        return CorpusSample(
            sample_id=sample_id,
            problem_id=problem_id,
            kind=kind,
            trace=trace,
            cpp_source=code,
            final_expected_correct=True,
            primary_error=ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
            first_error_step_id="proof-1",
        )
    return CorpusSample(
        sample_id=sample_id,
        problem_id=problem_id,
        kind=kind,
        trace=trace,
        cpp_source=code,
        final_expected_correct=True,
    )


def _controlled_samples(
    root: Path,
    selection: FrozenSelectionManifest,
    bundle_manifest: ProjectBundleManifest,
) -> tuple[CorpusSample, ...]:
    samples: list[CorpusSample] = []
    bundles = {bundle.problem_id: bundle for bundle in bundle_manifest.bundles}
    for entry in selection.entries:
        bundle = bundles[entry.problem_id]
        samples.append(
            _sample(
                root,
                sample_id=f"{entry.problem_id}-gold",
                problem_id=entry.problem_id,
                kind=CorpusSampleKind.GOLD,
                code_text=(root / bundle.reference_cpp.path).read_text(encoding="utf-8"),
            )
        )
        for index, mutant in enumerate(bundle.mutants, start=1):
            samples.append(
                _sample(
                    root,
                    sample_id=f"{entry.problem_id}-wrong-{index}",
                    problem_id=entry.problem_id,
                    kind=CorpusSampleKind.CONTROLLED_WRONG,
                    code_text=(root / mutant.path).read_text(encoding="utf-8"),
                )
            )
    for entry in selection.entries[:15]:
        bundle = bundles[entry.problem_id]
        samples.append(
            _sample(
                root,
                sample_id=f"{entry.problem_id}-paradox",
                problem_id=entry.problem_id,
                kind=CorpusSampleKind.PARADOX,
                code_text=(root / bundle.reference_cpp.path).read_text(encoding="utf-8"),
            )
        )
    return tuple(samples)


def test_project_bundle_lint_binds_selection_authorship_and_file_bytes(tmp_path: Path) -> None:
    """A changed source file or third-party-code declaration must fail bundle lint."""

    selection = _selection()
    entries = _bundle_entries(tmp_path, selection)
    manifest = build_project_bundle_manifest(selection, entries)

    validated = lint_project_bundles(
        manifest.model_dump(mode="json"),
        root=tmp_path,
        selection=selection,
    )

    assert len(validated.bundles) == 30
    invalid_trace = b"{}"
    invalid_trace_ref = ArtifactRef(
        path=entries[0].gold_trace.path,
        byte_length=len(invalid_trace),
        sha256=hashlib.sha256(invalid_trace).hexdigest(),
        media_type=ArtifactMediaType.JSON,
        provenance=ArtifactProvenance.PROJECT_AUTHORED,
    )
    (tmp_path / invalid_trace_ref.path).write_bytes(invalid_trace)
    invalid_entry = entries[0].model_copy(update={"gold_trace": invalid_trace_ref})
    invalid_manifest = build_project_bundle_manifest(selection, (invalid_entry, *entries[1:]))
    with pytest.raises(CorpusDataError, match="gold trace"):
        lint_project_bundles(
            invalid_manifest.model_dump(mode="json"),
            root=tmp_path,
            selection=selection,
        )

    (tmp_path / entries[0].gold_trace.path).write_bytes(
        canonical_json_bytes(
            _trace(
                trace_id=f"{entries[0].problem_id}-gold",
                problem_id=entries[0].problem_id,
                code=(tmp_path / entries[0].reference_cpp.path).read_text(encoding="utf-8"),
                step_id="algorithm-1",
                step_status=StepStatus.CORRECT,
            ).model_dump(mode="json")
        )
    )
    changed = tmp_path / entries[0].reference_cpp.path
    changed.write_text("tampered", encoding="utf-8")
    with pytest.raises(CorpusDataError, match="byte length|SHA-256"):
        lint_project_bundles(
            manifest.model_dump(mode="json"),
            root=tmp_path,
            selection=selection,
        )
    invalid = entries[0].model_dump(mode="json")
    invalid["third_party_submitted_code_included"] = True
    with pytest.raises(ValidationError):
        AuthoredBundleEntry.model_validate_json(json.dumps(invalid))


def test_bundle_lint_reads_each_artifact_from_one_openat_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing an artifact pathname with a symlink after open cannot alter lint bytes."""

    selection = _selection()
    entries = _bundle_entries(tmp_path, selection)
    manifest = build_project_bundle_manifest(selection, entries)
    reference = tmp_path / entries[0].reference_cpp.path
    saved = tmp_path / "reference-before-swap.cpp"
    replacement = tmp_path / "attacker.cpp"
    replacement.write_text("attacker replacement", encoding="utf-8")
    real_open = dataset_models.os.open
    swapped = False

    def swap_after_open(path: object, *args: object, **kwargs: object) -> int:
        nonlocal swapped
        file_fd = real_open(path, *args, **kwargs)
        if path == "reference.cpp" and kwargs.get("dir_fd") is not None and not swapped:
            reference.rename(saved)
            reference.symlink_to(replacement)
            swapped = True
        return file_fd

    monkeypatch.setattr(dataset_models.os, "open", swap_after_open)

    validated = lint_project_bundles(
        manifest.model_dump(mode="json"),
        root=tmp_path,
        selection=selection,
    )

    assert swapped is True
    assert validated == manifest


def test_bundle_lint_requires_human_attestation_and_rejects_provenance_markers(
    tmp_path: Path,
) -> None:
    """Self-consistent source bytes still fail on hidden/submission provenance markers."""

    selection = _selection()
    entries = _bundle_entries(tmp_path, selection)
    assert entries[0].authoring_attestation.human_review_required is True
    invalid_attestation = entries[0].authoring_attestation.model_dump(mode="json")
    invalid_attestation["content_hash"] = "f" * 64
    with pytest.raises(ValidationError, match="content_hash"):
        AuthoringAttestation.model_validate_json(json.dumps(invalid_attestation))

    mutant = entries[0].mutants[0]
    marker_bytes = b"// generated_tests copied metadata\nint main() { return 1; }\n"
    (tmp_path / mutant.path).write_bytes(marker_bytes)
    marker_ref = mutant.model_copy(
        update={
            "byte_length": len(marker_bytes),
            "sha256": hashlib.sha256(marker_bytes).hexdigest(),
        }
    )
    changed_entry = entries[0].model_copy(update={"mutants": (marker_ref, entries[0].mutants[1])})
    marker_manifest = build_project_bundle_manifest(
        selection,
        (changed_entry, *entries[1:]),
    )

    with pytest.raises(CorpusDataError, match="forbidden provenance marker"):
        lint_project_bundles(
            marker_manifest.model_dump(mode="json"),
            root=tmp_path,
            selection=selection,
        )


def test_pending_corpus_proves_30_60_15_and_reports_natural_60_pending(tmp_path: Path) -> None:
    """Missing credentials may defer natural outputs but cannot alter controlled counts."""

    selection = _selection()
    bundle_manifest = build_project_bundle_manifest(selection, _bundle_entries(tmp_path, selection))
    samples = _controlled_samples(tmp_path, selection, bundle_manifest)
    natural_config = _natural_config(selection)

    manifest = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=samples,
        natural_run_config=natural_config,
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    audit = lint_corpus_manifest(
        manifest.model_dump(mode="json"),
        root=tmp_path,
        selection=selection,
        bundle_manifest=bundle_manifest,
    )

    assert audit.status is CorpusStatus.PENDING_CREDENTIALS
    assert audit.materialized_counts == {
        "gold": 30,
        "controlled_wrong": 60,
        "paradox": 15,
        "natural": 0,
    }
    assert audit.expected_counts == {
        "gold": 30,
        "controlled_wrong": 60,
        "paradox": 15,
        "natural": 60,
    }
    assert audit.credentials_pending is True
    assert audit.formal_eligibility is False
    assert audit.judge_evidence_pending is True
    assert len(manifest.samples) == 105

    tampered_gold = _sample(
        tmp_path,
        sample_id=samples[0].sample_id,
        problem_id=samples[0].problem_id,
        kind=CorpusSampleKind.GOLD,
        code_text="// alternate accepted code\nint main() { return 0; }\n",
    )
    tampered_manifest = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=(tampered_gold, *samples[1:]),
        natural_run_config=natural_config,
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    with pytest.raises(CorpusDataError, match="gold source"):
        lint_corpus_manifest(
            tampered_manifest.model_dump(mode="json"),
            root=tmp_path,
            selection=selection,
            bundle_manifest=bundle_manifest,
        )

    wrong_ids = (*natural_config.problem_ids[:-1], "cf-99999-a")
    wrong_config = NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=wrong_ids,
        prompt_version=natural_config.prompt_version,
        prompt_hash=natural_config.prompt_hash,
        model_name=natural_config.model_name,
        endpoint_url=natural_config.endpoint_url,
        model_parameters=natural_config.model_parameters,
        credential_env_var=natural_config.credential_env_var,
        status=NaturalRunStatus.PENDING_CREDENTIALS,
        pending_reason="Formal Hy3 credentials are not available.",
    )
    with pytest.raises(CorpusDataError, match="problem IDs"):
        build_corpus_manifest(
            selection=selection,
            bundle_manifest=bundle_manifest,
            samples=samples,
            natural_run_config=wrong_config,
            status=CorpusStatus.PENDING_CREDENTIALS,
        )


def test_corpus_model_rejects_self_rehashed_natural_selection_link(tmp_path: Path) -> None:
    """A persisted corpus cannot point its natural run at a different selection."""

    selection = _selection()
    bundle_manifest = build_project_bundle_manifest(selection, _bundle_entries(tmp_path, selection))
    manifest = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=_controlled_samples(tmp_path, selection, bundle_manifest),
        natural_run_config=_natural_config(selection),
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    payload = manifest.model_dump(mode="json")
    natural_payload = payload["natural_run_config"]
    natural_payload["selection_manifest_hash"] = "f" * 64
    natural_payload["content_hash"] = sha256_json(
        {key: value for key, value in natural_payload.items() if key != "content_hash"}
    )
    payload["content_hash"] = sha256_json(
        {key: value for key, value in payload.items() if key != "content_hash"}
    )

    with pytest.raises(ValidationError, match="natural.*selection"):
        CorpusManifest.model_validate_json(json.dumps(payload))


def test_natural_run_endpoint_rejects_query_credentials() -> None:
    """Frozen endpoint identity must not serialize API keys or any query string."""

    selection = _selection()
    baseline = _natural_config(selection)

    with pytest.raises(ValidationError, match="query|credentials"):
        NaturalRunConfig.create(
            selection_manifest_hash=selection.content_hash,
            problem_ids=baseline.problem_ids,
            prompt_version=baseline.prompt_version,
            prompt_hash=baseline.prompt_hash,
            model_name=baseline.model_name,
            endpoint_url="https://api.example.invalid/v1?api_key=SECRET",
            model_parameters=baseline.model_parameters,
            credential_env_var=baseline.credential_env_var,
            status=NaturalRunStatus.PENDING_CREDENTIALS,
            pending_reason=baseline.pending_reason,
        )


def test_formal_judge_audit_requires_all_30_gold_60_mutant_15_paradox(
    tmp_path: Path,
) -> None:
    """Formal eligibility is emitted only for the exact hash-linked 105-case set."""

    selection_chain, records = _verified_selection_chain(tmp_path)
    selection = selection_chain.selection
    bundle_manifest = build_project_bundle_manifest(selection, _bundle_entries(tmp_path, selection))
    manifest = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=_controlled_samples(tmp_path, selection, bundle_manifest),
        natural_run_config=_natural_config(selection),
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    controlled_kinds = {
        CorpusSampleKind.GOLD: JudgeCaseKind.GOLD,
        CorpusSampleKind.CONTROLLED_WRONG: JudgeCaseKind.MUTANT,
        CorpusSampleKind.PARADOX: JudgeCaseKind.PARADOX,
    }
    cases = tuple(
        JudgeSourceCase(
            case_id=sample.sample_id,
            kind=controlled_kinds[sample.kind],
            problem=records[sample.problem_id],
            cpp_source=(tmp_path / sample.cpp_source.path).read_text(encoding="utf-8"),
        )
        for sample in manifest.samples
    )

    def complete_evidence(problem: ProblemRecord, *, mutant: bool) -> JudgeEvidence:
        final_tests = (*problem.hidden_tests, *problem.generated_tests)
        return JudgeEvidence(
            compile_status=JudgeStatus.AC,
            verdict=JudgeStatus.WA if mutant else JudgeStatus.AC,
            tests=tuple(
                PerTestEvidence(
                    test_id=test.test_id,
                    status=JudgeStatus.WA if mutant and index == 0 else JudgeStatus.AC,
                    counterexample_input=test.input_data if mutant and index == 0 else None,
                )
                for index, test in enumerate(final_tests)
            ),
            first_counterexample_input=final_tests[0].input_data if mutant else None,
        )

    class SemanticJudge:
        def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
            return complete_evidence(problem, mutant="mutant" in cpp_source)

    result = validate_formal_corpus_judge_cases(
        corpus=manifest,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
        judge=SemanticJudge(),
    )

    assert result.formal_eligibility is True
    report = result.evidence_manifest
    serialized = report.model_dump_json()
    assert "formal_eligibility" not in serialized
    assert len(report.cases) == 105
    with pytest.raises(TypeError):
        FormalCorpusJudgeValidationResult(evidence_manifest=report)
    raw_evidence = {
        case.case_id: complete_evidence(
            case.problem,
            mutant=case.kind is JudgeCaseKind.MUTANT,
        )
        for case in cases
    }
    replayed = validate_persisted_formal_judge_evidence(
        report.model_dump(mode="json"),
        corpus=manifest,
        selection_chain=selection_chain,
        bundle_manifest=bundle_manifest,
        cases=cases,
        raw_evidence=raw_evidence,
    )
    assert replayed.formal_eligibility is True
    assert replayed.evidence_manifest == report

    forged = report.model_dump(mode="json")
    forged["cases"][0]["judge_evidence_hash"] = "0" * 64
    forged["content_hash"] = sha256_json(
        {key: value for key, value in forged.items() if key != "content_hash"}
    )
    with pytest.raises(ValidationError):
        FormalCorpusJudgeValidationReport.model_validate_json(json.dumps(forged))

    replaced_evidence = report.model_dump(mode="json")
    replaced_evidence["cases"][0]["judge_evidence_hash"] = "f" * 64
    replaced_evidence["content_hash"] = sha256_json(
        {key: value for key, value in replaced_evidence.items() if key != "content_hash"}
    )
    with pytest.raises(DifferentialDataError, match="evidence hash mismatch"):
        validate_persisted_formal_judge_evidence(
            replaced_evidence,
            corpus=manifest,
            selection_chain=selection_chain,
            bundle_manifest=bundle_manifest,
            cases=cases,
            raw_evidence=raw_evidence,
        )

    replaced_chain = report.model_dump(mode="json")
    replaced_chain["bundle_manifest_hash"] = "f" * 64
    replaced_chain["content_hash"] = sha256_json(
        {key: value for key, value in replaced_chain.items() if key != "content_hash"}
    )
    with pytest.raises(DifferentialDataError, match="chain hashes"):
        validate_persisted_formal_judge_evidence(
            replaced_chain,
            corpus=manifest,
            selection_chain=selection_chain,
            bundle_manifest=bundle_manifest,
            cases=cases,
            raw_evidence=raw_evidence,
        )
    with pytest.raises(DifferentialDataError, match="exactly match"):
        validate_formal_corpus_judge_cases(
            corpus=manifest,
            selection_chain=selection_chain,
            bundle_manifest=bundle_manifest,
            cases=cases[:-1],
            judge=SemanticJudge(),
        )

    forged_bundle_payload = bundle_manifest.model_dump(mode="json")
    forged_bundle_payload["selection_manifest_hash"] = "f" * 64
    forged_bundle_payload["content_hash"] = sha256_json(
        {key: value for key, value in forged_bundle_payload.items() if key != "content_hash"}
    )
    forged_bundle = ProjectBundleManifest.model_validate_json(json.dumps(forged_bundle_payload))
    forged_corpus_payload = manifest.model_dump(mode="json")
    forged_corpus_payload["bundle_manifest_hash"] = forged_bundle.content_hash
    forged_corpus_payload["content_hash"] = sha256_json(
        {key: value for key, value in forged_corpus_payload.items() if key != "content_hash"}
    )
    forged_corpus = CorpusManifest.model_validate_json(json.dumps(forged_corpus_payload))
    with pytest.raises(DifferentialDataError, match="bundle.*selection"):
        validate_formal_corpus_judge_cases(
            corpus=forged_corpus,
            selection_chain=selection_chain,
            bundle_manifest=forged_bundle,
            cases=cases,
            judge=SemanticJudge(),
        )


def test_complete_corpus_requires_sixty_natural_outputs_and_primary_labels(tmp_path: Path) -> None:
    """Complete status requires two natural outputs per problem and error labels on controls."""

    selection = _selection()
    bundle_manifest = build_project_bundle_manifest(selection, _bundle_entries(tmp_path, selection))
    controlled = list(_controlled_samples(tmp_path, selection, bundle_manifest))
    natural: list[CorpusSample] = []
    for entry in selection.entries:
        for index in (1, 2):
            natural.append(
                _sample(
                    tmp_path,
                    sample_id=f"{entry.problem_id}-natural-{index}",
                    problem_id=entry.problem_id,
                    kind=CorpusSampleKind.NATURAL,
                )
            )
    pending = _natural_config(selection)
    completed_config = NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=tuple(entry.problem_id for entry in selection.entries),
        prompt_version=pending.prompt_version,
        prompt_hash=pending.prompt_hash,
        model_name=pending.model_name,
        endpoint_url=pending.endpoint_url,
        model_parameters=pending.model_parameters,
        credential_env_var=pending.credential_env_var,
        status=NaturalRunStatus.COMPLETE,
        materialization_manifest_hash="1" * 64,
    )
    manifest = build_corpus_manifest(
        selection=selection,
        bundle_manifest=bundle_manifest,
        samples=(*controlled, *natural),
        natural_run_config=completed_config,
        status=CorpusStatus.COMPLETE,
    )

    audit = lint_corpus_manifest(
        manifest.model_dump(mode="json"),
        root=tmp_path,
        selection=selection,
        bundle_manifest=bundle_manifest,
    )

    assert len(manifest.samples) == 165
    assert audit.materialized_counts == audit.expected_counts
    assert audit.credentials_pending is False
    with pytest.raises(ValidationError, match="primary_error"):
        CorpusSample(
            sample_id="bad-wrong",
            problem_id=selection.entries[0].problem_id,
            kind=CorpusSampleKind.CONTROLLED_WRONG,
            trace=controlled[1].trace,
            cpp_source=controlled[1].cpp_source,
            final_expected_correct=False,
        )
