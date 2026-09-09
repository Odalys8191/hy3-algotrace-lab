# LIVE-SMOKE — executable non-formal benchmark wiring

- Owner: Codex; independent review: reviewer subagent.
- Goal: run the existing CLI with an actual Hy3 client, restricted Docker Judge,
  rules/review/fusion pipeline, immutable sample evidence and request accounting.
- Scope: new `live_benchmark.py`, `benchmark_cli.py` wiring, focused integration
  tests, one authored cf-1613-c example and external non-formal catalog/config.
- Inputs: validated catalog bundles; a hash-bound live sample input manifest;
  frozen BenchmarkConfig; runtime environment credentials and immutable image.
- Outputs: existing benchmark observations/metrics/ledger/report, per-sample trace,
  raw JudgeEvidence and audit/review evidence under a protected live-evidence path.
- Compatibility: shared 1.2 contracts unchanged; existing injected executors and
  artifact replay retain their behavior. The new CLI adapter rejects formal=true
  until formal natural-generation/freeze and human-label timing are implemented.
- Execution: reject config/input/catalog/prompt/parameter/model/endpoint/image
  mismatches before any API call; generate each natural sample with a new uncached
  Hy3Client, feed the Runner observer directly into that client's attempt observer,
  judge through Docker only, retain evidence and map step IDs to step numbers.
- Failure: budget exhaustion remains a partial Runner result; other execution
  failures create a safe failure marker and ledger index, return nonzero, and never
  convert missing execution evidence into algorithm errors or fabricated metrics.
- Test plan: first write failing tests for automatic CLI wiring, uncached repeated
  generation, raw evidence, hidden-generation-input separation, budget cap, invalid
  frozen inputs, infrastructure failure and non-formal-only boundary. Then run
  focused tests, full non-Docker suite, Ruff, mypy and release validation.
- Constraints: no API keys in artifacts/logs; no fake human review, no public raw
  tests or submitted code, no use of host execution as a Judge fallback.
- Runtime status: Docker CLI exists but Docker desktop application was not found;
  real Docker Judge and paid Hy3 requests are not part of offline acceptance.
- Task breakdown: (1) CLI adapter and regression tests; (2) independently authored
  real problem example; (3) assemble external smoke inputs, review and validate.

## 2026-09-08 continuation: safe CLI failure boundaries

- Work stayed in `codex/integrate-task6-8`; all pre-existing modified/untracked
  files were retained. No shared 1.2 contract or host Judge fallback was changed.
- RED: six live CLI cases for missing, malformed JSON and invalid-schema configs
  failed before the fix. Config loading now returns safe JSON and exit 2 for
  automatic live run/static validation; injected/replay behavior is preserved.
- Independent code review found an additional P2: unusable artifact roots,
  duplicate runs and failure-marker persistence could expose raw exceptions.
  Three real ArtifactStore regression cases failed before implementation, then
  passed after bounded CLI handling. Existing artifact bytes remain unchanged.
  The independent reviewer rechecked the fix and closed the finding.
- Final focused command: `.venv/bin/pytest -q tests/test_real_data_preflight.py
  tests/test_live_benchmark.py tests/test_smoke_example.py tests/test_benchmark_cli.py
  tests/test_benchmark.py tests/test_docker_judge_commands.py
  tests/test_docker_judge_backend.py` → **186 passed**.
- `.venv/bin/pytest -q -m 'not docker_integration'` → **579 passed, 9 deselected**,
  one existing Starlette deprecation warning.
- `.venv/bin/ruff check .` → all checks passed; `.venv/bin/mypy src` → no issues
  in 35 source files; `.venv/bin/python -m hy3_algotrace.release_validation --root .`
  → passed, 130 files checked; `git diff --check` → exit 0.
- Command output is retained in the external smoke directory under
  `continuation-20260908-v1/quality-gates/ea76f30a72c95306df68d10d26038c0071611fef9bb81bc9d6179de3d302f9f6.json`.
- Docker Desktop is now installed and daemon 29.2.1 started successfully.
  This supersedes the earlier runtime-status note. Actual image/Judge/API outcomes
  are recorded separately in `docs/LIVE_SMOKE_2026-09-08.md`.
