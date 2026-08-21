# Platform-neutral coordination workflow

This repository uses task cards and immutable evidence so work can be coordinated in any issue tracker, document system, or local workflow.

## Task card

Every implementation task records these fields before work starts:

| Field | Required content |
| --- | --- |
| ID and title | Stable identifier and one-sentence outcome |
| Owner | One accountable implementer and any named reviewers |
| Scope | Files/modules in scope and explicitly excluded work |
| Inputs and outputs | Contract versions, artifacts, and consuming tasks |
| Dependencies | Prerequisite task cards and decisions |
| Acceptance criteria | Observable behaviors and required checks |
| Evidence | RED/GREEN commands, outputs, static checks, and artifact hashes |
| Review | Reviewer, outcome, follow-up items, and resolution |
| Decisions | Date, decision, rationale, and compatibility impact |

## Ownership and review

One owner writes a file at a time. Handoffs name the new owner and include the current task-card evidence. Every completed task receives an independent review against its acceptance criteria, including contract compatibility when it touches shared models. Review findings are either resolved with fresh checks or recorded as explicit concerns.

## Immutable runs and artifacts

Persistent dataset and run artifacts are versioned JSON, serialized deterministically, content-addressed with SHA-256, and create-only. A rerun creates a new run ID and artifact set. Formal configurations, thresholds, and inputs are frozen before execution and cannot be replaced after results are known. Secrets are excluded from artifacts and logs.

## Schema changes

Shared contracts are versioned. Additive, backwards-compatible fields require a task-card decision and consumer review. Breaking changes require a new schema version, migration or reader strategy, focused compatibility tests, and sign-off from affected task owners. Historical artifacts remain readable according to their recorded schema version.

The unpersisted pre-release `1.0` draft has no migration obligation. The reviewed `1.1` contract is superseded by frozen `1.2`: use `migrate_v1_1_to_v1_2` only when every new required field is already present in a versioned JSON mapping. The migration intentionally fails rather than inventing provenance, reviewer evidence, scores, or other semantics that cannot be inferred. After the `1.2` freeze, every breaking change requires a new version and an explicit reader or migration path before implementation.
