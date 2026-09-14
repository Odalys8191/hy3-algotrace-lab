"""Build pending authored inputs locally; never generates natural or Judge evidence."""

from __future__ import annotations

import argparse
import json
import os
import runpy
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hy3_algotrace.artifacts import canonical_json_bytes, sha256_bytes, sha256_json
from hy3_algotrace.contracts import (
    CheckerSemantics,
    ErrorTaxonomy,
    OutputComparison,
    ProblemOracle,
    ProblemRecord,
    ReasoningStage,
    ReasoningStep,
    SolutionTrace,
    StepStatus,
)
from hy3_algotrace.corpus import (
    AgentAuthoringRecord,
    ArtifactMediaType,
    ArtifactProvenance,
    ArtifactRef,
    AuthoredBundleEntry,
    CorpusSample,
    CorpusSampleKind,
    CorpusStatus,
    FrozenModelParameter,
    NaturalRunConfig,
    NaturalRunStatus,
    build_corpus_manifest,
    build_project_bundle_manifest,
    lint_corpus_manifest,
    lint_project_bundles,
)
from hy3_algotrace.dataset_models import CandidateReviewArtifact, FrozenSelectionManifest
from hy3_algotrace.prompts import GENERATOR_PROMPT_VERSION, GENERATOR_SYSTEM_PROMPT


class AuthoringBuildError(ValueError):
    """Invalid input or an occupied create-only destination."""


def _trace(
    pid: str, sample_id: str, spec: Mapping[str, Any], code: str, claim: str | None = None
) -> SolutionTrace:
    stages = tuple(ReasoningStage)
    claims = (
        spec["steps"][0],
        claim or spec["algorithm"],
        spec["proof"],
        f"Time: {spec['time']}; space: {spec['space']}.",
        "Implementation follows these obligations: " + " ".join(spec["steps"]),
        "Check boundary cases: " + " ".join(spec["edges"]),
    )
    steps = tuple(
        ReasoningStep(
            step_id=f"s{index + 1}",
            step_number=index + 1,
            stage=stages[index],
            claim=text,
            rationale=text,
            depends_on=(f"s{index}",) if index else (),
            status=StepStatus.INCORRECT if index == 1 and claim else StepStatus.CORRECT,
        )
        for index, text in enumerate(claims)
    )
    return SolutionTrace(
        trace_id=sample_id,
        problem_id=pid,
        steps=steps,
        problem_understanding=spec["steps"][0],
        algorithm=spec["algorithm"],
        correctness_argument=spec["proof"],
        time_complexity=spec["time"],
        space_complexity=spec["space"],
        edge_cases=tuple(spec["edges"]),
        code=code,
    )


def assemble_authored_corpus(
    *,
    out_dir: Path,
    selection: FrozenSelectionManifest,
    records: Mapping[str, ProblemRecord],
    reviews: Mapping[str, CandidateReviewArtifact],
    specs: Mapping[str, Any],
    source_files: Mapping[str, bytes],
) -> dict[str, Any]:
    """Validate all inputs and staged bytes before exclusively publishing a new root.

    Full records live only under private/ (0700, files 0600). Provenance contains
    hashes of public specifications and source bytes, never test values or oracles.
    Human selection review is not represented as review of this generated corpus.
    """
    out_dir = Path(out_dir)
    if out_dir.exists() or out_dir.is_symlink():
        raise AuthoringBuildError("output already exists")
    try:
        return _assemble(out_dir, selection, records, reviews, specs, source_files)
    except (ValueError, KeyError, TypeError, OSError):
        # Do not echo private records, validation payloads, or file contents.
        raise AuthoringBuildError("invalid authored input or create-only output") from None


def _assemble(
    out_dir: Path,
    selection: FrozenSelectionManifest,
    records: Mapping[str, ProblemRecord],
    reviews: Mapping[str, CandidateReviewArtifact],
    specs: Mapping[str, Any],
    source_files: Mapping[str, bytes],
) -> dict[str, Any]:
    selection = FrozenSelectionManifest.model_validate_json(selection.model_dump_json())
    ids = {entry.problem_id for entry in selection.entries}
    if set(records) != ids or set(reviews) != ids or set(specs) != ids or not source_files:
        raise ValueError("input coverage must exactly match selection")
    source_hashes = {name: sha256_bytes(content) for name, content in sorted(source_files.items())}
    generator_hash = sha256_json(source_hashes)
    files: dict[str, bytes] = {}

    def artifact(path: str, content: bytes, media: ArtifactMediaType) -> ArtifactRef:
        if path in files:
            raise ValueError("duplicate artifact path")
        files[path] = content
        return ArtifactRef(
            path=path,
            byte_length=len(content),
            sha256=sha256_bytes(content),
            media_type=media,
            provenance=ArtifactProvenance.PROJECT_AUTHORED,
        )

    bundles = []
    samples = []
    provenance_rows = []
    cells = set()
    for entry in selection.entries:
        pid = entry.problem_id
        record = ProblemRecord.model_validate_json(records[pid].model_dump_json())
        review = CandidateReviewArtifact.model_validate_json(reviews[pid].model_dump_json())
        if (
            record.problem_id != pid
            or sha256_json(record.model_dump(mode="json")) != entry.record_hash
            or review.review.problem_id != pid
            or review.content_hash != entry.review_hash
            or review.raw_row_hash != entry.raw_row_hash
        ):
            raise ValueError("record or pinned review mismatch")
        spec = specs[pid]
        code = spec["code"]
        if len(spec["steps"]) < 4 or len(spec["mutants"]) != 2:
            raise ValueError("four reasoning stages and two mutants required")
        mutated = []
        for mutant in spec["mutants"]:
            if not mutant["old"] or code.count(mutant["old"]) != 1 or not mutant["claim"]:
                raise ValueError("mutation must replace exactly one source occurrence")
            ErrorTaxonomy(mutant["taxonomy"])
            mutated.append(code.replace(mutant["old"], mutant["new"], 1))
        if len(set([code, *mutated])) != 3:
            raise ValueError("mutants must differ from each other and reference")
        public = record.model_dump(
            mode="json", exclude={"hidden_tests", "generated_tests", "content_hash"}
        )
        evidence = {
            "problem_id": pid,
            "public_problem_hash": sha256_json(public),
            "specification_hash": sha256_json(spec),
            "generator_hash": generator_hash,
        }
        provenance_rows.append(evidence)
        prefix = f"problems/{pid}"
        reference = artifact(f"{prefix}/reference.cpp", code.encode(), ArtifactMediaType.CPP)
        oracle_value = ProblemOracle(
            problem_id=pid,
            accepted_algorithm_families=(spec["algorithm"],),
            key_invariants=tuple(spec["invariants"]),
            complexity_ceiling=spec["time"],
            known_traps=tuple(spec["traps"]),
            adversarial_cases=tuple(spec["edges"]),
            decisive_facts=(spec["proof"],),
            reference_solution_hash=sha256_json(code),
        )
        oracle = artifact(
            f"{prefix}/oracle.json",
            canonical_json_bytes(oracle_value.model_dump(mode="json")),
            ArtifactMediaType.JSON,
        )
        gold_bytes = canonical_json_bytes(
            _trace(pid, f"{pid}-gold", spec, code).model_dump(mode="json")
        )
        gold = artifact(f"{prefix}/gold_trace.json", gold_bytes, ArtifactMediaType.JSON)
        mutant_refs = tuple(
            artifact(f"{prefix}/mutant-{i}.cpp", text.encode(), ArtifactMediaType.CPP)
            for i, text in enumerate(mutated, 1)
        )
        checker = None
        if (
            review.review.output_comparison or OutputComparison.EXACT
        ) is not OutputComparison.EXACT:
            checker = artifact(
                f"{prefix}/checker.json",
                canonical_json_bytes(
                    CheckerSemantics(
                        problem_id=pid,
                        output_comparison=(
                            review.review.output_comparison or OutputComparison.EXACT
                        ),
                    ).model_dump(mode="json")
                ),
                ArtifactMediaType.JSON,
            )
        bundles.append(
            AuthoredBundleEntry(
                problem_id=pid,
                selection_entry_hash=sha256_json(entry.model_dump(mode="json")),
                reference_cpp=reference,
                oracle=oracle,
                gold_trace=gold,
                mutants=mutant_refs,
                checker_json=checker,
                third_party_submitted_code_included=False,
                authoring_attestation=AgentAuthoringRecord.create(
                    generator_sha256=generator_hash,
                    evidence_sha256=sha256_json(evidence),
                    source_provenance_sha256=sha256_json(public),
                ),
            )
        )
        variants = [(CorpusSampleKind.GOLD, f"{pid}-gold", code, None, None)]
        variants.extend(
            (
                CorpusSampleKind.CONTROLLED_WRONG,
                f"{pid}-wrong-{i}",
                text,
                mutant["claim"],
                ErrorTaxonomy(mutant["taxonomy"]),
            )
            for i, (text, mutant) in enumerate(zip(mutated, spec["mutants"], strict=True), 1)
        )
        cell = (entry.topic, entry.rating_band)
        if cell not in cells:
            cells.add(cell)
            variants.append(
                (
                    CorpusSampleKind.PARADOX,
                    f"{pid}-paradox",
                    code,
                    "The algorithm is correct because its output is correct.",
                    ErrorTaxonomy.PROOF_GAP_CIRCULARITY,
                )
            )
        for kind, sample_id, text, claim, taxonomy in variants:
            sample_prefix = f"corpus/{kind.value}/{sample_id}"
            trace_bytes = canonical_json_bytes(
                _trace(pid, sample_id, spec, text, claim).model_dump(mode="json")
            )
            samples.append(
                CorpusSample(
                    sample_id=sample_id,
                    problem_id=pid,
                    kind=kind,
                    trace=artifact(f"{sample_prefix}.json", trace_bytes, ArtifactMediaType.JSON),
                    cpp_source=artifact(
                        f"{sample_prefix}.cpp", text.encode(), ArtifactMediaType.CPP
                    ),
                    final_expected_correct=kind is not CorpusSampleKind.CONTROLLED_WRONG,
                    primary_error=taxonomy,
                    first_error_step_id="s2" if claim else None,
                )
            )
        files[f"private/problem-records/{pid}.json"] = canonical_json_bytes(
            record.model_dump(mode="json")
        )
    if len(cells) != 15:
        raise ValueError("paradox must cover all fifteen quota cells")
    manifest = build_project_bundle_manifest(selection, bundles)
    natural = NaturalRunConfig.create(
        selection_manifest_hash=selection.content_hash,
        problem_ids=tuple(entry.problem_id for entry in selection.entries),
        prompt_version=GENERATOR_PROMPT_VERSION,
        prompt_hash=sha256_bytes(GENERATOR_SYSTEM_PROMPT.encode()),
        model_name="hy3",
        endpoint_url="https://tokenhub.tencentmaas.com/v1",
        model_parameters=(FrozenModelParameter(name="reasoning_effort", value="high"),),
        credential_env_var="HY3_API_KEY",
        status=NaturalRunStatus.PENDING_CREDENTIALS,
        pending_reason="Natural generation has not been authorized or executed.",
    )
    corpus = build_corpus_manifest(
        selection=selection,
        bundle_manifest=manifest,
        samples=samples,
        natural_run_config=natural,
        status=CorpusStatus.PENDING_CREDENTIALS,
    )
    provenance = {
        "kind": "automated_project_authoring",
        "human_review_performed": False,
        "source_files": source_hashes,
        "problems": provenance_rows,
    }
    files["authored-provenance.json"] = canonical_json_bytes(
        provenance | {"content_hash": sha256_json(provenance)}
    )
    files["bundle-manifest.json"] = canonical_json_bytes(manifest.model_dump(mode="json"))
    files["corpus-pending.json"] = canonical_json_bytes(corpus.model_dump(mode="json"))
    # Validate through production readers before the destination can become visible.
    temporary_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix="hy4oi-authored-", dir=temporary_root) as temporary:
        staging = Path(temporary)
        _write_files(staging, files)
        lint_project_bundles(manifest.model_dump(mode="json"), root=staging, selection=selection)
        lint_corpus_manifest(
            corpus.model_dump(mode="json"),
            root=staging,
            selection=selection,
            bundle_manifest=manifest,
        )
    out_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
    _write_files(out_dir, files)
    return {
        "sample_count": len(samples),
        "bundle_count": len(bundles),
        "natural_reserved": natural.target_sample_count,
        "formal_eligibility": False,
        "corpus_hash": corpus.content_hash,
        "bundle_hash": manifest.content_hash,
    }


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--records-dir", type=Path, required=True)
    parser.add_argument("--reviews-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        sources = {Path(__file__).name: Path(__file__).read_bytes()}
        specs = {}
        for group in ("a", "b"):
            source = Path(__file__).with_name(f"formal_authoring_specs_{group}.py")
            sources[source.name] = source.read_bytes()
            group_specs = runpy.run_path(str(source))["SPECS"]
            if specs.keys() & group_specs.keys():
                raise AuthoringBuildError("duplicate specification")
            specs.update(group_specs)
        selection = FrozenSelectionManifest.model_validate_json(args.selection.read_bytes())
        records = {
            record.problem_id: record
            for path in args.records_dir.glob("*.json")
            if (record := ProblemRecord.model_validate_json(path.read_bytes()))
        }
        reviews = {
            review.review.problem_id: review
            for path in args.reviews_dir.glob("*.json")
            if (review := CandidateReviewArtifact.model_validate_json(path.read_bytes()))
        }
        result = assemble_authored_corpus(
            out_dir=args.out_dir,
            selection=selection,
            records=records,
            reviews=reviews,
            specs=specs,
            source_files=sources,
        )
    except (ValueError, KeyError, TypeError, OSError):
        print("Authored corpus preparation failed closed.")
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
