# FORMAL-LIFECYCLE — separate intent freeze from result freeze

- Owner: Codex; independent review: reviewer subagent.
- Goal: make a formal benchmark configuration freezable before natural
  generation runs, while corpus materialisation legitimately happens after the
  run, without ever allowing a prefabricated or cached corpus hash to satisfy a
  formal check.
- Problem: today `BenchmarkConfig.corpus_hash` must be complete before a run,
  but natural corpus materialisation depends on generation events and final
  traces produced by that same run. Formal natural generation is therefore
  unreachable without either forging the hash or reusing another run's events.
- Scope: shared 1.2 contracts, `benchmark_models.py`, `benchmark_cli.py`,
  live/formal conversion paths, migration and reader coverage, focused tests.
- Inputs: existing frozen BenchmarkConfig, sample specs, live-input manifest,
  verified selection chain, generation events and traces, human labels.
- Outputs: an explicit two-phase freeze model with distinct artifact kinds for
  execution-intent freeze and run-result freeze, plus binding rules for
  `sample_id`/`trace_id` and the exact moment human labels may be attached.
- Compatibility: `contracts.py` is a public boundary. Any schema change needs a
  compatibility decision, a schema-version bump for breaking changes, migration
  and reader coverage, and downstream owner review. Prefer additive fields with
  safe defaults over breaking edits.
- Execution: bind sample identity at intent-freeze time; bind trace and corpus
  identity at result-freeze time; require the result freeze to reference the
  intent freeze by content hash; require human labels to be attached only after
  result freeze, or through an explicit, separately versioned amendment.
- Failure: a formal run missing either freeze, or whose corpus hash was derived
  from cache, replay, fixture, or another run's generation events, must fail
  closed with `formal_eligibility=false`. A persisted receipt alone must never
  restore formal eligibility.
- Test plan: first write failing tests for (1) forging a corpus hash before
  generation, (2) reusing another run's generation events, (3) cache or replay
  satisfying a formal check, (4) attaching human labels before result freeze,
  (5) sample/trace binding mismatch, (6) missing intent or result freeze,
  (7) migration from an existing 1.2 config without the new fields. Then run
  focused tests, full non-Docker suite, `ruff check .`, `mypy src` and
  release validation.
- Constraints: no API keys in artifacts or logs; no host execution as a Judge
  fallback; no fabricated human review; no new formal capability implied by
  lint or fixture evidence.
- Dependency: this task is blocked by the 30-problem human review reaching a
  frozen formal selection, and by a successful non-formal live smoke run.

## Suggested prompt for the next round

See the copy-paste prompt section at the end of this card. It is written to be
self-contained: pasting it into a fresh session must be enough to start.

```text
You are working in the git worktree
/Users/odalys/Documents/hy4oi/.worktrees/integrate-task6-8 on branch
codex/integrate-task6-8. Read AGENTS.md, docs/task-live-smoke.md,
docs/LIVE_SMOKE_2026-09-08.md and docs/DATA_PREFLIGHT_REVIEW_2026-09-07.md
before writing anything.

Task: implement the formal freeze lifecycle described in
docs/task-formal-lifecycle.md. Split "execution intent freeze" from
"run result freeze" so a formal BenchmarkConfig can be frozen before natural
generation, while corpus materialisation happens after the run. Define when
sample_id and trace_id bind, and when human labels may be attached.

Rules that must hold:
- src/hy3_algotrace/contracts.py is a public boundary. Any schema change needs
  an explicit compatibility decision, a schema-version bump for breaking
  changes, migration and reader coverage. Prefer additive fields.
- Tests first: record a failing run for each case listed in the task card's
  test plan, then write the smallest implementation that passes.
- Fail closed. A corpus hash derived from cache, replay, fixture, or another
  run's generation events must never satisfy a formal check. A persisted
  receipt must never restore formal eligibility on its own.
- No API keys in source, artifacts, fixtures or logs. No host execution as a
  Judge fallback. No fabricated human review.

Deliver: focused tests, then full non-Docker pytest, ruff check ., mypy src and
release validation, and report the exact commands and outputs. Update
docs/task-formal-lifecycle.md with what you actually did. Do not commit or
push without asking.
```
