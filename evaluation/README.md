# Public evaluation package

This directory is the repository-safe projection of the current evaluation work. It contains
project-authored C++17 answers and reasoning traces plus aggregate, redacted results. It does
not contain copied problem statements, raw CodeContests rows, hidden/generated tests, oracle
facts, raw Judge evidence, prompts, model responses, credentials, or machine-local paths.

## Materials

[`materials/manifest.json`](materials/manifest.json) is the source of truth:

- 30 linked Codeforces problems;
- five topics and three rating bands, with two problems in every topic/band cell;
- 30 gold, 60 controlled-wrong, and 15 paradox samples;
- exact expected final correctness, first-error step and taxonomy labels;
- byte lengths and SHA-256 values for all 210 C++/trace files.

Run the self-contained integrity and schema check:

```sh
python -m hy3_algotrace.public_release validate --root evaluation/materials
```

The validator does not claim semantic correctness against tests that are intentionally absent
from the public tree. The redacted aggregate of the externally retained Judge evidence is in
[`results/current-results.json`](results/current-results.json).

To recreate the public projection from an authorised external corpus, always choose a new,
nonexistent destination:

```sh
python -m hy3_algotrace.public_release export \
  --authored-root "$HY3_AUTHORED_ROOT" \
  --quota "$HY3_SELECTION_QUOTA" \
  --output evaluation/materials-next
```

The exporter is create-only and accepts only manifest-referenced paths below
`corpus/{gold,controlled_wrong,paradox}`.

## Validation boundary

The current release has no human-confirmed localization/FPR dataset. See
[`validation/status.json`](validation/status.json) for machine-readable null metrics and
[`validation/manual-audit-template.csv`](validation/manual-audit-template.csv) for the exact
fields a real blind review must complete. An empty template is not a review result.
