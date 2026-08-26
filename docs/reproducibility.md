# Reproducibility and formal-run protocol

## Data and readiness gates

This tree does not establish that the external 30-problem/165-sample data is complete.
`scripts/data-lint.sh` validates acquired validation/test bytes against their frozen manifest.
`scripts/formal-readiness.sh` accepts only a complete external chain and invokes the same-process
qualification boundary; it never pre-creates selection receipts or corpus audits. The boundary
rebuilds the verified selection capability from raw/review bytes, validates every referenced
bundle and corpus byte, and directly replays exactly 30 gold, 60 mutant, and 15 paradox cases
from the original `JudgeEvidence`, including the exact ordered hidden-plus-generated per-test
matrix and aggregate/counterexample consistency. Only while that ephemeral result exists does
it resolve the content-addressed 60-row natural materialization, reconstruct the 165-item blind
human-review export/mapping/decision/replay chain, and validate the ordered observations and
complete contiguous call ledger. A receipt, audit, bare label set, persisted qualification
report, or boolean cannot rehydrate eligibility.

Readiness exits `3` for missing inputs/format selection, `2` for invalid data or a create-only
output conflict, and `0` only after creating
`formal-qualification/<content_hash>.json`. `scripts/formal-release-gate.sh` converts exit `3`
to release failure `1` and propagates other failures. `scripts/docker-smoke.sh` returns `64` for
missing immutable CI inputs rather than substituting a mutable default. See README for the exact
input environment list and Compose directory layout.

Only original-English Codeforces records with standard stdin/stdout, source attribution,
acquisition hashes, conversion/reviewer linkage, and 15-cell quota evidence can progress. The
1200–1500 foundation band is not a claim of beginner performance. Project-authored bundles may
be used; raw third-party submitted solutions are not released. Record historical contamination
from prior data/problem/prompt/output exposure before selection and treat conclusions as
relative baselines when contamination cannot be ruled out.

## Frozen benchmark configuration

Before one formal run, create an immutable configuration that binds, at minimum:

- acquisition/validation/conversion/selection/bundle/corpus/Judge-evidence hashes;
- ordered sample IDs and sample categories;
- `HY3_MODEL`, credential-free endpoint identity, prompt/version hashes, parameters, code
  revision, immutable Judge image, metric/chart implementation versions;
- seed, bootstrap replicate count, and a reserved-call ledger with a hard limit of 500;
- blind-export, reviewer assignment, replay, and delayed 20% re-review configuration.

The natural materialization manifest is addressed by its canonical content hash and covers the
60 natural samples in corpus order. Every row binds exact source/trace bytes, the canonical
parsed trace hash, the verified selected problem record, model-visible input, repository
generator prompt content, frozen model and credential-free endpoint, ordered JSON-typed scalar
parameters, recomputed request/cache identity, and the exact generation-attempt event hashes in
the Task 6 ledger. Where no remote result digest exists, the parsed trace hash and exact request
attempts form the immutable provenance/replay link; they do not cryptographically attest remote
service behavior.

For Docker reproduction, bind the `docker/release-runtime-lock.json` canonical content hash to
the digest-pinned runtime image used by the app build, along with the exact Docker CLI package
and Judge build arguments. The verification compares the whole distribution set, so an extra
package also invalidates the runtime. This branch carries only a `registry.invalid` sentinel:
there is no obtainable attested runtime image yet, and that is a release blocker rather than a
reproducibility claim. A changed lock, runtime digest, package version, or Judge input creates a
new configuration; it never replaces a prior result.

The Hatchling `1.27.0` official PyPI core metadata declares `packaging>=24.2`,
`pathspec>=0.10.1`, `pluggy>=1.0.0`, and `trove-classifiers` (with `tomli` only below Python
3.11). Accordingly, the Python 3.12 lock records `pathspec==1.1.1`, `pluggy==1.6.0`, and
`trove-classifiers==2026.6.1.19` alongside the existing `packaging` row. This is a dependency
declaration derived from PyPI metadata, not evidence that these wheels have been built or
attested together in Linux; the `registry.invalid` sentinel continues to block release until
that independent runtime attestation exists.

Reserve every remote model attempt before sending it. Bind generation outputs through the
materialization manifest and exact request-attempt hashes; cache hits cost zero. A run that
exceeds 500 reserved attempts, lacks a ledger entry, or has a broken artifact linkage is
immutable partial evidence and cannot be called a formal result.

## Human review and reports

Export reviewers a blinded package containing only permitted public evidence. Keep the mapping,
decision, and replay inputs separate and immutable. Draw a seeded 20% subset for delayed blind
re-review; record its due date, reviewer, result, disagreement handling, and hashes. A lone
reviewer is not independent confirmation, and a same-model reviewer shares potential bias with
the generator. Formal qualification rebuilds the blind export from the verified public problem
records and all 165 corpus traces, replays the initial and delayed decisions, recomputes agreement,
and requires the replay observations and labels to match the benchmark exactly. Only one combined
human-review provenance hash enters the safe qualification report.

Use the create-only [method](method-report-template.md),
[results](results-report-template.md), and [audit](audit-record-template.md) templates. Never
replace a report/chart after seeing results. The planned 30/60/15/60 composition, 500-attempt
ceiling, and any breakpoint/metric result remain specifications rather than completed facts.
