# Hy3 AlgoTrace Lab

> **个人活动实战作品，非腾讯官方发布。**

Hy3 AlgoTrace Lab is a personal local-single-user research prototype for auditing C++17
algorithm-solution traces. It is not a Tencent product, not a production internet sandbox,
and not evidence of a completed benchmark or a recorded demo.

## Status and limits

This branch supplies contracts, immutable artifacts, catalog/Judge/API foundations, an
environment-backed FastAPI composition, and release checks. It does **not** claim a completed
30-problem selection, 165-sample corpus, 500-call benchmark, recorded two-minute video,
production deployment, or internet-facing sandbox safety. A missing dataset, formal gate, or
review artifact is a not-ready result—not permission to substitute examples, generated data,
or a success claim.

The 1200–1500 foundation band is the lowest proposed formal rating band. It is not labelled
“beginner” and does not establish novice-level performance. Historical exposure to public
problems, data, prompts, or prior outputs is a contamination risk that must be recorded; it
cannot be retroactively cured by a rerun.

## Architecture

```text
Task 6 Streamlit client (HTTP only; integrated after its controller merge)
        |  HY3_API_BASE_URL=http://api:8000
        v
Task 5 FastAPI <- local_app.create_app() zero-argument composition
        |-- immutable ArtifactStore and public-field allowlist
        |-- Hy3Client: HY3_BASE_URL, HY3_API_KEY, HY3_MODEL (runtime only)
        |-- deterministic rules and review orchestration
        `-- DockerJudge -> separately restricted C++17 Judge image@sha256
```

The Streamlit process is only an HTTP client. It must not read the catalog, artifact store,
Judge socket, hidden tests, oracle, credentials, or model endpoint. The API owns those
boundaries. Until Task 6 is merged, the `streamlit` Compose profile deliberately points at the
anticipated `hy3_algotrace.streamlit_app` and will not start; this is not a fabricated UI.

## Clean local verification

Requires Python 3.12. Static/unit checks require no credential, external data, Docker image,
or network access.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
python -m pytest -q -m "not docker_integration"
python -m ruff format --check src/hy3_algotrace/release_validation.py \
  src/hy3_algotrace/demo_cli.py src/hy3_algotrace/local_app.py \
  docker/verify-runtime-lock.py tests/test_release_validation.py \
  tests/test_demo_cli.py tests/test_local_release_wiring.py
python -m ruff check .
python -m mypy src
python -m hy3_algotrace.release_validation --root .
scripts/security-scan.sh
scripts/formal-readiness.sh # exits 3 while the persisted Task 7 Judge replay is absent
scripts/formal-release-gate.sh # turns that pending state into a release-blocking failure
```

`formal-readiness.sh` exits `3` while Task 7 data/replay inputs are absent or the formal Judge
bridge is unavailable; `formal-release-gate.sh` converts that pending state to release-blocking
exit `1`. `docker-smoke.sh` exits `64` when immutable CI image inputs are missing. These are
intended, honest not-ready signals, not successful verification.

## Local Compose build and run

Copy placeholders only; never commit a real `.env` or print its API key.

```sh
cp .env.example .env
# Fill only local values: locked runtime/Judge images, exact Docker CLI package,
# trusted formal-catalog directory, and authorised HY3 runtime values.
docker compose config
docker compose up --build
```

`--build` corresponds to `docker/app/Dockerfile`, but this branch deliberately has **no
attested public runtime-image digest or complete release wheelhouse**. The checked-in runtime
lock is a `registry.invalid` release-blocker sentinel, so Docker build must fail until a
maintainer produces and signs an obtainable Python 3.12 runtime image. That image must already
contain the complete locked Python closure **and Docker CLI**; the app Dockerfile runs no apt or
pip dependency resolution. It compares the locked runtime identity, canonical lock hash, exact
Docker CLI package attestation, and the complete installed distribution set (including rejecting
extras) before installing this package with `--no-deps`.

Once that attestation exists, the API starts through
`hy3_algotrace.local_app:create_app --factory`, whose composition is zero-arg and uses the
existing catalog, artifact store, Hy3 client, Docker Judge, reviewer, and background executor.
It still fails closed before formal use if the catalog, `HY3_BASE_URL`, `HY3_API_KEY`,
`HY3_MODEL`, or immutable `HY3_JUDGE_IMAGE` is unavailable.

After the Task 6 controller merge supplies the anticipated module, start the client with:

```sh
docker compose --profile ui up --build
```

Both host ports are hard-bound to `127.0.0.1`; release validation checks source and rendered
Compose semantics. Do not edit a port mapping to expose it.

### Docker Judge boundary

The Compose API receives a bind-mounted **local host Docker socket** only when
`HY3_DOCKER_SOCKET_PATH` is explicitly set. This is effectively host-root authority. It is
acceptable only for one controlled local user who understands that risk; it is forbidden for
shared, CI multi-tenant, or internet-facing deployment. The Judge itself creates a separate
immutable image with network disabled and resource limits, but that does not eliminate socket
authority. If the socket, exact Judge image, or Docker daemon is unavailable, judging fails
closed; do not replace it with host-process execution.

## Data acquisition and formal readiness

After verified Task 7 integration, use the explicit commands rather than hand-editing reports:

```sh
scripts/data-lint.sh
scripts/formal-readiness.sh
```

`data-lint.sh` validates immutable validation/test acquisition bytes and hashes. Formal
readiness additionally requires Task 7's persisted formal Judge evidence plus protected raw
JudgeEvidence replay, which proves the frozen 30 gold / 60 mutant / 15 paradox chain in-memory.
A `CorpusAuditReport` saying evidence is pending exits `3`; selection/bundle/corpus lint alone
can never return formal success. Task 7 currently exposes secure
`validate-selection-preliminary` and `verify-selection-chain` commands only; its persisted
selection receipt expressly has `capability_persisted=false`. A combined-tree in-process formal
Judge replay adapter is still required, so this release remains blocked. It requires paths
supplied through documented local environment variables and does not create fake data. Only original-English,
standard-stdin/stdout Codeforces entries with source attribution may be candidates. Project-
authored references are allowed; raw third-party submitted solutions are not redistributed.

Protected internal dataset artifacts may be retained under access control for Judge and
provenance replay. They must never enter a model prompt, public/API/UI response, or a run
artifact. Public release material contains only safe summaries and hashes.

## Reproducibility, reviews, and reporting

Before a formal run, freeze source/acquisition, selection/corpus, Judge evidence, model and
credential-free endpoint identity, prompts/parameters, code/Judge image versions, metric
version, bootstrap settings, random seed, and the call ledger. Reserve every remote attempt
before transmission; the hard cap is 500 calls. Cache hits cost zero. A partial or exhausted
run is immutable evidence but not a formal result.

Human review exports a blind package, keeps reviewer/mapping/replay artifacts separate, and
requires a delayed blind re-review of a seeded 20% sample. A single reviewer is not independent
verification; same-model generation and review can share bias. Use the create-only method,
results, and audit templates in `docs/`; they intentionally contain no claimed outcome.

## Security and attribution

- Runtime model settings use only `HY3_BASE_URL`, `HY3_API_KEY`, and `HY3_MODEL`; credentials
  never pass through Docker build args, artifacts, prompts, reports, screenshots, or logs.
- The release validator rejects public Compose ports, hard-coded secret-like assignments, and
  missing disclosures. CI performs a full-history Gitleaks scan with a deliberately tiny
  placeholder-only allowlist.
- CodeContests/Codeforces material and all dependencies retain their own licences and terms.
- Bootstrap intervals are descriptive under their stated IID-row assumption; correlated rows
  and contamination mean model comparisons are relative baselines, not causal claims.

The Docker release CI is deliberately **not green**. Seven public, non-secret repository
Variables are required to run its actual Compose/API controlled-fixture integration and real
Judge verdict matrix; absent inputs fail in `docker-release-not-ready`. Even with those inputs,
the formal-release gate and the deliberately unattested runtime lock prevent a release claim
until independently provided Task 7 replay evidence and a real runtime-image attestation are
committed.

Read [release security](docs/release-security.md), [reproducibility](docs/reproducibility.md),
[attribution](docs/license-and-attribution.md), and the [unrecorded demo checklist](docs/demo.md)
before any local run.
