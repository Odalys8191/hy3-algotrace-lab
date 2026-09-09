# Poisoned Dagger: non-formal smoke assets v1

This directory contains an original AI-authored C++17 reference, a schema 1.2
`ProblemOracle`, and a six-stage schema 1.2 `SolutionTrace` for Codeforces 1613C.
The filename `gold_trace.json` is an integration convention: this is **unreviewed,
non-formal, nonofficial** smoke material, not human-approved ground truth.
It is not an official Tencent, Codeforces, or DeepMind release.

Problem attribution: [Codeforces 1613C, Poisoned Dagger](https://codeforces.com/problemset/problem/1613/C),
accessed through the local [DeepMind CodeContests](https://github.com/google-deepmind/code_contests)
v1 test Parquet. Only the explicitly projected public columns `name`,
`description`, `cf_contest_id`, `cf_index`, and `public_tests` were read, filtered
to contest 1613 and index C. No dataset solutions, incorrect solutions, hidden
tests, or generated tests were read or copied. The full statement and dataset
row are not redistributed here. The algorithm, explanation, and code were
written for this project from the public problem specification.

## Algorithm and proof

For duration k, consecutive attacks separated by gap g contribute min(k,g)
damage before the next attack; the last attack contributes k. Therefore
D(k) = k + sum(min(k,gap)). These disjoint segments cover all poisoned seconds,
including the attack second, without double counting refreshed poison.
Every term is nondecreasing, so D(k) >= h is a monotone predicate. The first
feasible duration is in [1,h], because the last attack alone makes h feasible.
Binary search preserves that first feasible duration in its inclusive interval
and finishes when both endpoints coincide. This proves minimality.

Each check takes O(n), giving O(n log(h+1)) time and O(n) storage per case.
The implementation uses signed 64-bit integers. Since k <= h <= 10^18 and
sum(min(k,gap)) <= sum(gap) = last_attack - first_attack < 10^9,
its damage sum cannot overflow. The midpoint uses low + (high-low)/2.

## Verification and limitations

Judge status: **not_run / unverified**. No Docker Judge, Codeforces submission,
live model API, or host execution of a submitted program was used in authoring.
No human reviewer or signed formal approval is claimed. Step status `correct`
is the author's proposed annotation and has not received independent review.

`tests/test_smoke_example.py` checks shared contracts, exact trace/reference
identity, content hashing, and all six reasoning stages. Where a C++ compiler is
available, it performs C++17 syntax checking with warnings treated as errors and
compile-time static assertions of the actual reference functions. The 756 tiny
cases use an independent union-of-integer-seconds oracle (all nonempty subsets
of attack times 1..6, health 1..12), plus three checks for maximal health and a
public sample. No executable is produced or run. These checks do not replace
sandboxed compilation/execution on the official test data or independent review.

## Task card and evidence

- ID: Task 7 smoke authoring, CF-1613-C v1.
- Owner: Codex AI author; independent reviewer pending, no human identity claimed.
- Scope: this directory and `tests/test_smoke_example.py`; no core changes.
- Inputs: projected public CodeContests fields and frozen schema 1.2.
- Outputs: reference string, oracle, and trace for the external non-formal catalog.
- Dependencies: existing contracts and canonical JSON hash helpers.
- Acceptance: valid schema 1.2, six meaningful stages, exact code/hash agreement,
  original code, bounded arithmetic, explicit provenance and unverified status.
- RED: focused pytest before asset creation: 2 failed (reference file absent).
- GREEN: focused pytest after authoring: 2 passed, including compile-time checks.
- Review: pending independent review; no formal qualification is asserted.
- Decision (2026-09-08): use existing schema 1.2 without contract changes; retain
  this version create-only, and create a new version rather than replacing it.

Canonical `sha256_json` hashes (the reference hash hashes the JSON string, not
raw source-file bytes):

| Asset | SHA-256 |
| --- | --- |
| Reference string | `a12043cc685edc59ff6d644d87cb3641f93f3a0290e65f6ac29308780ea57861` |
| Oracle JSON object | `c47e19a44dd1a33ae3ae5f5038dfe788627fe20d4ad186f624973ad9d00a5487` |
| Trace JSON object | `f854fa08841f0d21eaca5b1a782173c8ed302c1cb34b992f6d942ea094e494e2` |
