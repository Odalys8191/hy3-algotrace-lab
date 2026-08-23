# Reproducibility and formal-run protocol

## Data and readiness gates

This branch does not establish that Task 7's 30-problem/165-sample data is complete. After that
layer is independently integrated, `scripts/data-lint.sh` validates acquired validation/test
bytes against their frozen manifest, and `scripts/formal-readiness.sh` replays acquisition,
selection, bundle, and corpus lint gates. Either script exits `3` for an absent integration or
missing input, which is explicitly **not ready**.

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

For Docker reproduction, bind the `docker/release-runtime-lock.json` content hash to the
digest-pinned runtime image used by the app build, along with the exact Docker CLI package and
Judge build arguments. A changed lock, runtime digest, package version, or Judge input creates a
new configuration; it never replaces a prior result.

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
