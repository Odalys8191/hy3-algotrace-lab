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
   validate-acquisition`.
2. Convert verified JSON, JSONL, or Parquet rows with `convert`. Official
   Riegeli input uses a trusted external converter command whose argument list
   contains the separate `{input}` and `{output}` tokens. Missing `pyarrow` or
   a Riegeli converter fails with an actionable error.
3. Store checker-review annotations outside the repository. A candidate is not
   eligible until a human has excluded interactive, special-judge,
   multiple-answer, and tolerance checking. Ambiguous target tags require a
   reviewed primary-topic annotation.
4. Run `quota` on both split conversions. `unfulfilled_quota` is a valid,
   expected outcome and is never padded.
5. Only after every one of the 15 topic/rating cells has at least two reviewed
   candidates, use `freeze-selection` with an explicit 30-ID list. The command
   proves both conversion files match the acquisition manifest before freezing.
6. Author reference C++17, traces, oracles, mutants, and paradox samples in the
   project. `lint-bundles` and `lint-corpus` verify relative paths, hashes,
   authorship declarations, selection links, labels, and counts. Corpus lint
   deliberately reports `formal_eligibility=false` until the exact hash-linked
   30 gold, 60 mutant, and 15 paradox sources pass
   `validate_formal_corpus_judge_cases` through an injected production Judge.
   Project-authored adversarial cases can also use `run_differential_tests`;
   its persisted report contains hashes rather than raw hidden inputs/outputs.

The controlled corpus must contain 30 gold, 60 controlled-wrong, and 15
paradox samples. A natural-run configuration always freezes two Hy3 calls per
problem (60 total). Without formal credentials, its honest status is
`pending_credentials` and no natural output is materialized; only a complete
run may claim the final 60 samples.

Dataset non-code material is offered by DeepMind as CC BY 4.0, while the
official README warns that Codeforces and other third-party materials may be
governed by separate terms. Preserve both DeepMind/AlphaCode and per-problem
Codeforces attribution. Never commit raw scraped submitted code.
