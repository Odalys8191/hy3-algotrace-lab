# Hy3 AlgoTrace Lab

> **个人活动实战作品，非腾讯官方发布。**

Hy3 AlgoTrace Lab is a personal activity project, not an official Tencent release. It is
a local, single-user research prototype for auditing C++17 algorithm-contest solution
traces: sandbox execution determines final-program correctness, while deterministic
rules and structured reviews help identify the first material reasoning error.

## Status and honest scope

This repository contains the versioned contracts, artifact/catalog layer, Docker judge,
Hy3 client/evaluator, and local FastAPI orchestration foundations. This release branch
does **not** claim a completed formal 30-problem selection, 165-sample corpus, recorded
two-minute demo, production internet sandbox, or multi-user deployment. The formal data
and natural-output work must remain pending until their source, human-review, Judge, and
credential gates have independently passed.

The Streamlit client and final application composition may be supplied by Task 6/Task 5
integration. The included Compose file is deliberately a fail-closed localhost wiring
template: it requires explicit integration targets and must not be presented as a working
UI before those files exist.

## Architecture

```text
Streamlit UI (HTTP client only; Task 6 integration)
        |
        v
FastAPI /api/v1 (Task 5 application composition)
        |
        +-- immutable, content-addressed run artifacts
        +-- Hy3 generation and structured review (environment credential only)
        +-- deterministic process evaluator
        `-- Docker-only C++17 Judge (no direct web-process execution)
```

The public API deliberately allowlists problem, trace, Judge-summary, and audit fields;
hidden/generated tests, oracle facts, local paths, and credentials must not reach prompts,
public API responses, artifacts, or logs. Persistent datasets, formal configurations, run
ledgers, reports, and review records are create-only JSON with content hashes. A rerun uses
a new run ID; it never overwrites or retroactively changes a formal artifact.

## Clean local setup

Requires Python 3.12, a C++17-capable Docker installation for Judge integration, and no
API key for static checks or unit tests.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m hy3_algotrace.release_validation --root .
```

Copy `.env.example` to `.env` only for an explicitly authorised local Hy3 run. Keep the
real `.env` untracked. Values in `.env.example` are placeholders, not usable keys.

```sh
cp .env.example .env
# Edit locally: never commit, print, or paste HY3_API_KEY into an issue, artifact, or log.
```

## Local Compose integration template

`compose.yaml` maps only `127.0.0.1` host ports. Before running it, provide an actual Task
5 FastAPI factory and Task 6 Streamlit file through `HY3_API_APP_MODULE` and
`HY3_STREAMLIT_APP_PATH`; the template exits before serving if either remains a placeholder.
This is intentional: this branch must not invent missing application entry points.

```sh
docker compose config
docker compose --profile ui up --build
```

The Compose template is local-development wiring, not a claim of a production-safe remote
code-execution service. It does not make Docker, Hy3, arbitrary model endpoints, or the
host network production-ready.

## Reproducibility and formal runs

Before a formal benchmark, freeze source acquisition metadata, the selected IDs, model and
endpoint identity without credentials, prompts/parameters, judge image identity, metric
version, seed, call budget, and review configuration. Every remote attempt must be recorded
before transmission; partial or budget-exhausted output is immutable but not formal.

The planned formal corpus is 30 selected problems with 30 gold, 60 controlled-wrong, 15
correct-result/invalid-process, and 60 natural-output samples. That is a specification, not
a completion claim. See [docs/reproducibility.md](docs/reproducibility.md); Task 7's data
documentation appears only when its verified data layer is integrated.

## Security and limitations

- Localhost only; this project is not multi-tenant and must not be exposed as a public code
  execution endpoint.
- The Docker Judge is a defense-in-depth local sandbox, not a proof of safe execution on an
  internet-facing production host.
- API credentials are environment-only. Release validation and CI fail when secret-like
  assignments appear in tracked release text.
- CodeContests/Codeforces material is external and subject to its own licence and terms.
  Do not commit raw external records, hidden tests, or third-party submitted solutions.
- A single reviewer is not independent verification. Same-model generator/reviewers can
  share systematic bias, and human review can be contaminated by unblinded evidence.
- Bootstrap intervals are descriptive under their documented IID-row assumption; repeated
  samples from one problem can be correlated. Model comparisons are relative baselines, not
  causal or general performance claims.

See [docs/release-security.md](docs/release-security.md),
[docs/license-and-attribution.md](docs/license-and-attribution.md), and
[docs/demo.md](docs/demo.md) for operational detail.
