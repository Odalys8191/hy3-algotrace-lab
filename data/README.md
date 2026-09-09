# Task 7 external-data workflow

This repository does not contain the CodeContests validation/test records, a
formal 30-problem selection, third-party submitted solutions, or fabricated
problem bundles.

## Start with downloaded Parquet files

The data preflight command hashes user-supplied raw files, runs the existing import
checks without human annotations, and creates acquisition/validation reports plus
a safe candidate report and unsigned review drafts. It never creates formal
eligibility. Use Python 3.12 and install `pyarrow` if it is not already available.

```sh
# Set HY3_DATA_HOME to the external directory containing raw/validation.parquet
# and raw/test.parquet. Choose a NEW output directory for each preflight version.
python -m hy3_algotrace.data_preflight \
  --validation "$HY3_DATA_HOME/raw/validation.parquet" \
  --test "$HY3_DATA_HOME/raw/test.parquet" \
  --validation-url 'https://huggingface.co/datasets/deepmind/code_contests/resolve/main/data/valid-00000-of-00001-5e672c5751f060d3.parquet' \
  --test-url 'https://huggingface.co/datasets/deepmind/code_contests/resolve/main/data/test-00000-of-00001-9c49eeff30aacaa8.parquet' \
  --format parquet \
  --output-root "$HY3_DATA_HOME/preflight-new-run" \
  --acknowledge-third-party-terms
```

URLs are declared provenance: this offline command does **not** authenticate a
publisher, verify an upstream revision, or claim that a recorded local hash was
published upstream. Replace the example URLs with the actual source URLs when
different. Retain independent upstream verification separately when available.
The acquisition manifest's converter name/version must also be supplied unchanged
to subsequent `convert-preliminary` / `convert-formal` commands.

All JSON outputs are content-addressed and create-only. The command prints a JSON
map of relative artifact paths, including an `index` file. Repeating a command
against the same artifacts fails without overwriting them. The report excludes
statements, test content, and submitted code; it retains raw-row hashes for review
binding. No raw-row export is performed. Load the exact row from its original
split and one-based row number when creating a reviewed artifact.

The maximum matching prevents one multi-topic problem from occupying two quota
slots. It is only an optimistic feasibility bound before checker/topic review.
Advisory statement patterns flag possible multiple answers, interaction, or
tolerance checking. If a complete unflagged assignment exists, it is preferred;
absence of a warning is never proof of standard checking. The review-draft JSON
has a separate kind and null human identity/timestamp: it is not a valid signed
`CandidateReview` or frozen selection input.

Memory import policy: acquired positive byte limits are floored to integral MiB
because the existing Judge contract accepts whole MiB. For example, 256000000
bytes maps to 244 MiB, never above the source limit; limits below 1 MiB are rejected.
The raw bytes/row hash remain unchanged. Existing exact-MiB inputs retain the same
record, and the converter identity records the new policy. This conservative
rounding can make an execution limit slightly stricter than the acquired limit.

The actual 2026-09-07 preflight and human worksheet are documented in
`docs/DATA_PREFLIGHT_REVIEW_2026-09-07.md` (relative to the project root).

## Formal acquisition and review chain

Formal inputs are limited to the Google DeepMind CodeContests `validation` and
`test` splits. Keep both raw files outside the repository. Before conversion,
create an acquisition manifest that records, for each split, its HTTPS source,
exact byte length, SHA-256, license/attribution text, and the converter name and
version. The template in `manifests/acquisition.example.json` is intentionally
invalid until every `REPLACE_*` value is replaced with observed metadata.

The supported workflow is:

1. Validate external bytes with `python -m hy3_algotrace.dataset_cli
   validate-acquisition`. Logical identities are derived, not supplied:
   `codecontests-raw-validation` and `codecontests-raw-test`. The path-free,
   self-hashed report records the canonical acquisition manifest hash and the
   size/SHA-256 observed from one no-follow file descriptor per split. Relabeling
   or swapping the two logical identities is invalid even if the report is
   rehashed.
2. Store checker-review annotations outside the repository. Use
   `create-review-artifact` with the exact raw row and one `CandidateReview`;
   the resulting self-hashed artifact binds that annotation to the canonical
   raw-row hash. Use `create-review-set` separately for validation and test,
   then `pin-review-manifest` to observe both files through trusted descriptors
   and freeze their canonical identities, lengths, and SHA-256 values.
3. Convert verified JSON, JSONL, or Parquet rows with `convert-formal`, supplying
   the matching `--review-set` and independently approved `--review-manifest`.
   Every eligible assessment then carries its exact review-artifact hash through
   quota and selection freeze. Official Riegeli input uses a trusted external
   converter command whose argument list contains the separate `{input}` and
   `{output}` tokens. Missing `pyarrow` or a Riegeli converter fails with an
   actionable error. Every conversion requires `--validation-report`; the raw
   bytes are reopened safely and must match the report before conversion.
   `convert-preliminary` accepts bare review annotations for exploration only;
   its output cannot be used by `freeze-selection`.
4. Independently record and human-approve the exact
   `ReviewArtifactManifest.content_hash` as the review trust root for this data
   version. Self-hashing detects inconsistency; it does **not** authenticate the
   reviewer or prove real-world identity. Changing a reviewer, row binding, or
   review-set byte requires a new manifest hash and a new explicit human approval.
   A caller may deliberately reroot to that newly approved version, but must
   never silently treat a rerooted manifest as already formal.
5. A candidate is not eligible until the approved human review has excluded
   interactive, special-judge, multiple-answer, and tolerance checking.
   Ambiguous target tags require a reviewed primary-topic annotation.
6. Run `quota` on both split conversions. `unfulfilled_quota` is a valid,
   expected outcome and is never padded.
7. Only after every one of the 15 topic/rating cells has at least two reviewed
   candidates, use `freeze-selection` with an explicit 30-ID list. The command
   requires the same `--validation-report` and proves both conversion files
   match both observed split records and the acquisition manifest before freezing.
   `validate-selection-preliminary` may replay those persisted derived reports,
   but is structural-only and does not establish formal readiness.
8. Run `verify-selection-chain` with both trusted raw files, their formats, the
   acquisition manifest/validation report, both pinned review-set files, the
   independently approved review manifest, and the selection. This secure path
   accepts no conversion report or quota as a trust input: it deterministically
   reconstructs them and issues only an in-memory capability. The CLI may write
   a self-hashed replay receipt, but that receipt explicitly has
   `formal_eligibility=false` and `capability_persisted=false`; loading it never
   recreates the capability.
9. Author reference C++17, traces, oracles, mutants, and paradox samples in the
project. `lint-bundles` and `lint-corpus` verify relative paths, hashes,
   authorship declarations, selection links, labels, and counts. Corpus lint
   deliberately reports `formal_eligibility=false`. The persisted Judge artifact
   contains only per-case canonical source/problem/evidence hashes and the
   selection/bundle/corpus chain; parsing it never restores eligibility. Only
   `validate_persisted_formal_judge_evidence`, supplied the original raw
   `JudgeEvidence` and the live verified-selection capability, can replay the
   exact 30 gold, 60 mutant, and 15 paradox cases and return an in-memory
   eligibility result. Preliminary selection validation and persisted replay
   receipts are not accepted by this formal bridge.
   Project-authored adversarial cases can also use `run_differential_tests`;
   its persisted report contains hashes rather than raw hidden inputs/outputs.

The controlled corpus must contain 30 gold, 60 controlled-wrong, and 15
paradox samples. A natural-run configuration always freezes two Hy3 calls per
problem (60 total). Without formal credentials, its honest status is
`pending_credentials` and no natural output is materialized; only a complete
run may claim the final 60 samples.

Every authored bundle also requires a hash-linked human attestation naming its
reviewer, review evidence, and project source-provenance record. Automated lint
rejects hidden/private/generated-test and submitted-code markers in paths and
contents, but this scan is defense in depth and never replaces the recorded
human provenance review.

Dataset non-code material is offered by DeepMind as CC BY 4.0, while the
official README warns that Codeforces and other third-party materials may be
governed by separate terms. Preserve both DeepMind/AlphaCode and per-problem
Codeforces attribution. Never commit raw scraped submitted code.
