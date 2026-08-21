# Hy3 AlgoTrace Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every production behavior uses test-driven development and every task requires an independent review.

**Goal:** Build a local, reproducible algorithm-contest solution auditing application that generates structured Hy3 solutions, executes C++17 safely, evaluates reasoning, localizes the first material error, and reports benchmark metrics.

**Architecture:** A Python 3.12 modular monolith exposes versioned Pydantic contracts through FastAPI, renders a Streamlit client, and persists immutable JSON artifacts. Docker supplies deterministic C++17 execution; deterministic rules, two isolated Hy3 reviewers, and conditional arbitration produce evidence-backed audit reports.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, Streamlit, httpx, pytest, ruff, mypy, Docker, GCC/C++17.

**Spec:** `task/start-task.md` plus the user-approved Hy3 AlgoTrace Lab plan in the task conversation.

## Global Constraints

- Public name is `Hy3 AlgoTrace Lab`; every public entry point states that it is a personal activity project and not an official Tencent release.
- The service binds to localhost by default and is a local single-user research application, not a multi-tenant remote code execution service.
- Python runtime is 3.12 and generated/judged code is C++17 only.
- API keys come only from environment variables and are never persisted in artifacts or logs.
- All persistent dataset and run artifacts are immutable, versioned JSON files with content hashes; no database is introduced.
- Formal evaluation uses 30 built-in CodeContests/Codeforces problems across five topics and three rating bands; custom unverified problems are out of scope.
- Model-visible input contains the original English statement and public examples only. Hidden/generated tests and oracle facts never enter the generation prompt.
- Model responses use a versioned structured `SolutionTrace`; one schema-repair call is allowed, then failure is classified as `FORMAT_SCHEMA`.
- Final correctness is determined only by sandbox execution. Evidence precedence is execution, deterministic rules, reviewer consensus, then conditional arbitration.
- Tests must be written and observed failing before production code is added. Test reports record RED and GREEN commands/output.
- Never silently replace formal runs, change thresholds after seeing results, or commit secrets.

---

### Task 1: Project Foundation and Versioned Contracts

**Files:** Create the Python package skeleton, packaging configuration, public contract models, contract tests, `AGENTS.md`, and the platform-neutral coordination workflow.

**Interfaces:** Produce Pydantic v2 models `ProblemRecord`, `ProblemOracle`, `ReasoningStep`, `SolutionTrace`, `ReviewerVerdict`, `AuditReport`, and `RunManifest`, each with `schema_version`. Define enums for stages, step statuses, error taxonomy, run status, and judge status. Enforce unique step IDs, valid dependency references, acyclic dependencies, rating/topic bands, C++17 language, and material-error semantics.

**Acceptance:** Focused contract tests first fail because the package/models do not exist, then pass. `pytest`, `ruff check`, and `mypy` run clean. Coordination docs define task-card fields, ownership, review, immutable-run, and schema-change rules.

### Task 2: Artifact Store and Problem Catalog

**Files:** Create artifact storage/catalog modules, CodeContests import/selection CLI, deterministic JSON serialization, five pilot problem bundles, and data validation tests.

**Interfaces:** Consume Task 1 models. Produce atomic create-only artifact writes keyed by SHA-256, problem discovery/detail APIs for the service layer, a selector enforcing five topics × three rating bands × two problems, and manifest validation. Reject overwrite, traversal, missing attribution, ambiguous topic, non-standard I/O, missing hidden tests, translated statements, and invalid resource limits.

**Acceptance:** RED/GREEN tests cover canonical hashing, immutable writes, safe paths, catalog loading, duplicate IDs, selector quotas, and invalid bundles. Five pilot bundles include public and hidden tests, oracle, gold trace, and authored C++17 reference code.

### Task 3: Docker C++17 Judge

**Files:** Create judge interfaces, Docker implementation, fixed judge image definition, security configuration, and focused unit/integration tests.

**Interfaces:** Consume `ProblemRecord` tests/limits and C++17 source. Produce `JudgeEvidence` with compile status, aggregate verdict, per-test outcomes, sanitized diagnostics, timing, memory metadata, and the first safe counterexample. Run without network, with read-only root, dropped capabilities, no-new-privileges, PID/CPU/memory/tmp/output limits. Web code never executes binaries directly.

**Acceptance:** Tests cover AC, compile error, WA, TLE, runtime error, oversized output, path safety, and Docker argument security. Docker-dependent tests skip with an explicit reason only when Docker is unavailable.

### Task 4: Hy3 Client, Rules, Reviewers, and Evidence Fusion

**Files:** Create OpenAI-compatible Hy3 adapter, prompt templates, response cache, deterministic rule engine, reviewer orchestration, arbitration, scoring, and tests using a protocol fake at the network boundary.

**Interfaces:** Generator emits `SolutionTrace`; reviewers emit `ReviewerVerdict`. Cache key is SHA-256 over model, endpoint identity without credentials, prompt version, parameters, and canonical input. Reviewer A checks logic/dependencies; reviewer B seeks counterexamples/constraints; material disagreements call the arbiter. Fusion honors evidence precedence, computes weighted score 20/25/20/10/10/15, identifies the earliest independent material error, and can return `needs_human_review`.

**Acceptance:** RED/GREEN tests cover cache hits, one repair only, transient retry, secret redaction, all nine error categories, dependency-root localization, reviewer agreement/disagreement, arbitration, paradox samples, and execution evidence overriding model opinion.

### Task 5: Run Orchestration and FastAPI

**Files:** Create run service, in-process background executor, versioned FastAPI routes, app configuration, and API/integration tests.

**Interfaces:** `POST /api/v1/runs` accepts `solve_and_audit` or `audit` for a built-in `problem_id` and returns a `run_id`; `GET /api/v1/runs/{run_id}` returns status/report; problems list/detail routes never expose hidden tests/oracles. Run state is persisted as immutable transition artifacts; restart reconciliation marks abandoned active runs failed rather than silently resuming.

**Acceptance:** Tests cover both modes, invalid IDs, invalid traces, status transitions, generation failure, infrastructure failure, hidden-data redaction, concurrent run IDs, and a correct/wrong/paradox vertical slice.

### Task 6: Streamlit Client, Benchmark CLI, Metrics, and Reports

**Files:** Create Streamlit UI, benchmark CLI, human-review queue/export, metric computation, bootstrap analysis, charts, and tests.

**Interfaces:** UI selects built-in problems, launches/polls runs, renders step timeline, code, judge evidence, first error, taxonomy, and `needs_human_review`. CLI runs frozen configs with a call ledger and hard budget. Metrics include final accuracy, process correctness, detection/localization, within-one localization, paradox detection, standard gold false-positive rate, audited flagged-case proportions, taxonomy macro-F1, agreement/arbitration, topic/difficulty breakdowns, and 95% bootstrap intervals. A stable breakpoint requires a ≥20-point adjacent decline whose interval excludes zero.

**Acceptance:** Tests use literal fixtures for every metric, deterministic bootstrap seeds, budget exhaustion, immutable report generation, human-review blinding/review replay, and UI service-boundary behavior.

### Task 7: Thirty-Problem Dataset and 165-Sample Corpus

**Files:** Populate the frozen problem manifest and per-problem bundles; add validation, mutation-generation, differential-testing, and corpus audit commands.

**Interfaces:** Exactly 30 original-English Codeforces entries from CodeContests validation/test: five primary topics (`construction_simulation`, `greedy`, `binary_search`, `dynamic_programming`, `graph`) × rating bands 1200–1500, 1600–1900, 2000–2400 × two. Produce 30 correct gold traces, 60 wrong-result controlled samples, 15 correct-result/invalid-process samples, and configuration for 60 natural Hy3 outputs. Project-authored reference code and attribution are mandatory; raw third-party submitted code is not redistributed.

**Acceptance:** Data lint proves quotas, attribution, hashes, hidden-test separation, all reference programs AC, wrong-result mutants fail, paradox code remains AC, primary error/first-step labels exist, and the corpus counts are exactly 30/60/15/60. Missing formal Hy3 credentials may prevent generating the last 60 outputs but must not weaken the schema, run config, or audit tooling.

### Task 8: Release Documentation, CI, Security, and Demo

**Files:** Create bilingual-ready README content, `.env.example`, Docker/Compose startup, CI, method/results report templates, audit record template, license/attribution documentation, and a sub-two-minute demo script.

**Interfaces:** Document clean setup, endpoint variables, dataset acquisition, formal-run freeze procedure, limitations, contamination risk, relative-baseline caveat, single-reviewer limitation, same-model reviewer bias, and immutable rerun policy. CI runs unit/static/data/security checks and optional Docker integration tests.

**Acceptance:** Fresh-environment commands succeed without secrets; secret scan, full tests, lint, type check, dataset lint, API smoke test, and Docker judge smoke test pass. README contains the non-official disclaimer and every required deliverable has a concrete path or generation command.

