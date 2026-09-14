# cf-1553-d Comparison Chain Implementation Plan

> **For agentic workers:** Execute inline in the existing `integrate-task6-8` worktree. The user explicitly prohibited commit, push, merge, reset, and clean, so this plan intentionally omits commit steps.

**Goal:** Consume the user's approved `cf-1553-d.output_comparison=case_insensitive` decision through a new create-only human-review, qualification, corpus, and Docker Judge evidence chain, then prove all 105 controlled samples satisfy their category rules.

**Architecture:** Preserve every old artifact byte-for-byte. Create a new human decision root, derive a complete 30-review qualification chain in a new data directory, rebuild the authored corpus in `prepaid-preparation-20260913-v6`, execute all four `cf-1553-d` samples because their comparison semantics changed, and reference the other 101 samples only after per-sample identity and evidence validation against `judge-v6`.

**Tech Stack:** Python 3.12, Pydantic models, existing `hy3_algotrace.dataset_cli`, C++17, digest-pinned Docker Judge, canonical SHA-256 artifacts.

**Spec:** `docs/CF1553D_COMPARISON_REVIEW_REQUIRED.md`, `docs/P1_LOCAL_VALIDATION_2026-09-13.md`, and `docs/FORMAL_CORPUS_LIFECYCLE.md`.

## Global Constraints

- Use `env -u PYTHONPATH .venv/bin/python` for every Python command.
- Use a fresh `/private/tmp/hy4oi-r007-20260913-*` basetemp for each pytest invocation.
- Never read `.env` or API keys; never call Hy3, generate natural samples, run a paid benchmark, freeze A, or perform a formal release.
- Keep the old human input, qualification, raw parquet, v5 corpus, judge-v4/v5/v6, and every failure artifact read-only.
- Do not modify `contracts.py` or weaken comparison, time-limit, process-metadata, or evidence validation.
- Do not commit, push, merge, reset, clean, or discard any dirty work.

---

### Task 1: Record and validate the human decision

**Files:**
- Create: `$HY3_REPO_HOME/review-output-20260913-v1/cf-1553-d-comparison-decision.md`
- Create: `$HY3_REPO_HOME/review-output-20260913-v1/human-review-checklist.corrected.json`
- Create: `$HY3_REPO_HOME/review-output-20260913-v1/derivation-report.json`

- [ ] Save the exact approved reviewer and timezone-aware decision time.
- [ ] Derive the new checklist from the prior corrected checklist.
- [ ] Verify the only per-row change is `cf-1553-d.output_comparison: null -> case_insensitive` and its reviewer/reviewed_at update to the supplied values; keep all other human fields and row identities unchanged.
- [ ] Record file and canonical hashes without overwriting the old review root.

### Task 2: Derive and replay a new qualification chain

**Files:**
- Create: `$HY3_DATA_HOME/codecontests-v1/qualification-20260913-v1/**`

- [ ] Derive 30 `CandidateReview` inputs and exact raw-row snapshots through the established parquet loaders.
- [ ] Run 30 `create-review-artifact`, two `create-review-set`, one `pin-review-manifest`, two `convert-formal`, `quota`, `freeze-selection`, and `verify-selection-chain` commands.
- [ ] Verify validation/test counts 13/17, all 15 quota cells contain exactly two selected problems, and comparison overrides are exactly `cf-1551-d1` and `cf-1553-d`.
- [ ] Save command argv/return codes, artifact hashes, the new selection hash, and replay receipt in the new root.

### Task 3: Build and validate the new authored corpus

**Files:**
- Create: `$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v6/authored-v1/**`
- Create: `$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v6/logs/**`

- [ ] Run `scripts/prepare_authored_corpus.py` with the new selection and review artifacts, while reading the unchanged v5 records and current authored specs.
- [ ] Verify 30 bundles, 105 controlled samples, 15 paradox cells, zero generated natural samples, and `formal_eligibility=false`.
- [ ] Compare v5 and v6: non-target problem records, sources, traces, and bundle entries must remain unchanged; `cf-1553-d` must gain a bound `checker.json` with `case_insensitive`; global selection/bundle/corpus hashes must change.

### Task 4: Execute affected Judge cases and compose the 105-sample evidence index

**Files:**
- Create: `$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v6/cf1553d-comparison-rerun-v1/**`
- Create: `$HY3_DATA_HOME/codecontests-v1/prepaid-preparation-20260913-v6/judge-v1/**`

- [ ] Probe the fixed Docker Judge image and bind the current source-tree identity.
- [ ] Execute all four `cf-1553-d` controlled samples (gold, wrong-1, wrong-2, paradox) across all hidden+generated tests with `case_insensitive` semantics.
- [ ] Require gold/paradox AC and both mutants compile successfully and remain detected; infrastructure errors are failures.
- [ ] For the other 101 samples, validate unchanged selection-entry, record, source, comparison, evidence, per-test, and process-metadata identities before referencing `v5/judge-v6` evidence.
- [ ] Write a standard `samples` evidence index covering 105 samples/22839 tests. Only if every category validates may `validation_passed=true`; keep `formal_eligibility=false` because natural/A/formal execution are absent.

### Task 5: Run all required quality gates and close out R007

- [ ] Run comparison/qualification/corpus/Judge focused tests.
- [ ] Run the complete non-Docker suite.
- [ ] Run the CI format check, `ruff check .`, `mypy src`, release validation, and `git diff --check`.
- [ ] Run the complete Docker integration suite with the local immutable validator image; preserve and report any intermittent failure.
- [ ] Update `docs/P1_LOCAL_VALIDATION_2026-09-13.md` and the single root `TODO.md` with exact commands, hashes, failures, blockers, next-round prompt, and `gpt-6-astra / high` recommendation.
