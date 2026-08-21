# Hy3 AlgoTrace Lab contributor guide

Hy3 AlgoTrace Lab is a personal activity project and not an official Tencent release.

## Non-negotiable rules

- Use Python 3.12 and generate/judge C++17 only.
- Keep API keys in environment variables only; never put them in source, artifacts, fixtures, or logs.
- Write tests first for production behavior, record a failing run, then add the smallest implementation.
- Treat all dataset and run artifacts as create-only, versioned JSON with a content hash. Never overwrite, mutate, or silently replace a formal run.
- Keep hidden tests and oracle facts out of model-generation prompts and public API responses.

## Shared-contract rule

`src/hy3_algotrace/contracts.py` is a public boundary. A schema change requires a task card, an explicit compatibility decision, a schema-version bump for breaking changes, migration/reader coverage, and review by every downstream owner. Do not change a contract opportunistically.

## Quality gate

Before committing, run the focused tests plus the complete suite, `ruff check .`, and `mypy src`. Report the commands and output in the task report.
