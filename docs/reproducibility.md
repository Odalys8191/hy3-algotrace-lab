# Reproducibility and formal-run protocol

## Data and readiness gates

This tree does not establish that the external 30-problem/165-sample data is complete.
`scripts/data-lint.sh` validates acquired validation/test bytes against their frozen manifest.
`scripts/formal-readiness.sh` accepts only a complete external chain and invokes the same-process
qualification boundary; it never pre-creates selection receipts or corpus audits. The boundary
rebuilds the verified selection capability from raw/review bytes, validates every referenced
bundle and corpus byte, and directly replays exactly 30 gold, 60 mutant, and 15 paradox cases
from the original `JudgeEvidence`. Only while that ephemeral result exists does it validate the
165 ordered observations/human labels and complete contiguous call ledger. A receipt, audit,
persisted qualification report, or boolean cannot rehydrate eligibility.

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

Reserve every remote model attempt before sending it; record transport failure and response
hash afterwards. Cache hits cost zero. A run that exceeds 500 reserved attempts, lacks a ledger
entry, or has a broken artifact linkage is immutable partial evidence and cannot be called a
formal result.

## Human review and reports

Export reviewers a blinded package containing only permitted public evidence. Keep the mapping,
decision, and replay inputs separate and immutable. Draw a seeded 20% subset for delayed blind
re-review; record its due date, reviewer, result, disagreement handling, and hashes. A lone
reviewer is not independent confirmation, and a same-model reviewer shares potential bias with
the generator.

Use the create-only [method](method-report-template.md),
[results](results-report-template.md), and [audit](audit-record-template.md) templates. Never
replace a report/chart after seeing results. The planned 30/60/15/60 composition, 500-attempt
ceiling, and any breakpoint/metric result remain specifications rather than completed facts.
