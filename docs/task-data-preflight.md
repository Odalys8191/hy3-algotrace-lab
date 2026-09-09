# DATA-PREFLIGHT — actual CodeContests acquisition and review preparation

- Owner: Codex; independent reviewer: code-review subagent after implementation.
- Scope: decimal-byte memory import compatibility, a read-only-source data preflight
  CLI, external acquisition artifacts, candidate/assignment and human-review drafts.
- Inputs: user-downloaded validation/test Parquet; current 1.2 contracts.
- Outputs: content-addressed acquisition/validation/preflight JSON, readable review
  material; every preflight explicitly has `formal_eligibility=false`.
- Dependencies: Task 1–8 integrated at `73030c0`; no API or Docker required.
- Acceptance: verify source bytes, preserve original rows and hashes, apply existing
  import rules without fabricated human approvals, account for overlapping topics
  with a unique-problem maximum matching, report real shortages, reject overwrites
  and unsafe raw paths, exclude hidden tests and submitted code from review reports.
- Compatibility decision (2026-09-07): keep shared 1.2 contracts unchanged. Imported
  positive byte limits are conservatively floored to whole MiB; values below one
  MiB are rejected. Previously accepted exact-MiB inputs retain identical records.
  Non-whole-MiB records were previously rejected, so no persisted accepted record
  changes. Converter identity and preflight report record this policy.
- Source status: local files found and hashed. External source metadata verification
  is currently unavailable due DNS failure; do not claim publisher authentication.
- Evidence: baseline `pytest -q -m 'not docker_integration'`: 538 passed,
  9 deselected, one existing Starlette deprecation warning.
- RED: decimal memory regression failed twice before implementation; focused data tests
  then passed. Final preflight tests: 17 passed. Full data-phase suite: 555 passed,
  9 Docker tests deselected. Ruff, mypy, release validation and diff checks passed.
- Independent reviewer found no actionable issues; cross-checked matching against
  exhaustive optima on 500 random graphs. All five final artifact hashes verified;
  standalone acquisition revalidation reproduced the persisted result.
