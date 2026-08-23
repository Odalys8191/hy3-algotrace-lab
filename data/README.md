# Task 7 external-data workflow

This repository does not contain the CodeContests validation/test records, a
formal 30-problem selection, third-party submitted solutions, or fabricated
problem bundles.

Formal inputs are limited to the Google DeepMind CodeContests `validation` and
`test` splits. Keep both raw files outside the repository. Before conversion,
create an acquisition manifest that records, for each split, its HTTPS source,
exact byte length, SHA-256, license/attribution text, and the converter name and
version. The template in `manifests/acquisition.example.json` is intentionally
invalid until every `REPLACE_*` value is replaced with observed metadata.

The supported workflow is:

1. Validate external bytes with `python -m hy3_algotrace.dataset_cli
   validate-acquisition`, supplying controlled `--validation-id` and `--test-id`
   values. The path-free, self-hashed report records the canonical acquisition
   manifest hash and the size/SHA-256 observed from one no-follow file descriptor
   per split.
2. Convert verified JSON, JSONL, or Parquet rows with `convert`. Official
   Riegeli input uses a trusted external converter command whose argument list
   contains the separate `{input}` and `{output}` tokens. Missing `pyarrow` or
   a Riegeli converter fails with an actionable error. Every `convert` command
   requires `--validation-report`; the raw bytes are reopened safely and must
   match the report before conversion.
3. Store checker-review annotations outside the repository. A candidate is not
   eligible until a human has excluded interactive, special-judge,
   multiple-answer, and tolerance checking. Ambiguous target tags require a
   reviewed primary-topic annotation.
4. Run `quota` on both split conversions. `unfulfilled_quota` is a valid,
   expected outcome and is never padded.
5. Only after every one of the 15 topic/rating cells has at least two reviewed
   candidates, use `freeze-selection` with an explicit 30-ID list. The command
   requires the same `--validation-report` and proves both conversion files
   match both observed split records and the acquisition manifest before freezing.
6. Author reference C++17, traces, oracles, mutants, and paradox samples in the
   project. `lint-bundles` and `lint-corpus` verify relative paths, hashes,
   authorship declarations, selection links, labels, and counts. Corpus lint
   deliberately reports `formal_eligibility=false`. The persisted Judge artifact
   contains only per-case canonical source/problem/evidence hashes and the
   selection/bundle/corpus chain; parsing it never restores eligibility. Only
   `validate_persisted_formal_judge_evidence`, supplied the original raw
   `JudgeEvidence`, can replay the exact 30 gold, 60 mutant, and 15 paradox cases
   and return an in-memory eligibility result.
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
