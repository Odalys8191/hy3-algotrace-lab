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
Task 6 Streamlit client (HTTP only; `ui` Compose profile)
        |  HY3_API_BASE_URL=http://api:8000
        v
Task 5 FastAPI <- local_app.create_app() zero-argument composition
        |-- immutable ArtifactStore and public-field allowlist
        |-- Hy3Client: HY3_BASE_URL, HY3_API_KEY, HY3_MODEL (runtime only)
        |-- deterministic rules and review orchestration
        `-- DockerJudge -> separately restricted C++17 Judge image@sha256
```

The Streamlit process is only an HTTP client. It cannot read the catalog, benchmark/formal
artifact roots, Judge socket, hidden tests, oracle, credentials, or model endpoint. The API
owns those boundaries. The separate `formal-readiness` profile receives read-only formal inputs
and a dedicated create-only output mount.

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
scripts/formal-readiness.sh # exits 3 while any external formal input is absent
scripts/formal-release-gate.sh # turns that pending state into a release-blocking failure
```

`formal-readiness.sh` exits `3` only for absent inputs or invalid format selection. A present but
invalid/tampered chain, an existing create-only report, or any qualification failure exits `2`.
`formal-release-gate.sh` converts readiness exit `3` to release-blocking exit `1` and propagates
other failures. `docker-smoke.sh` exits `64` when immutable CI image inputs are missing. These
are intended, honest not-ready/failure signals, not successful verification.

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

Start the HTTP-only client with:

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

Use the explicit commands rather than hand-editing reports:

```sh
scripts/data-lint.sh
scripts/formal-readiness.sh
```

`data-lint.sh` validates immutable validation/test acquisition bytes and hashes. Formal
readiness invokes only `hy3_algotrace.formal_qualification`. In one Python process it rebuilds
the verified selection capability from raw validation/test bytes and pinned human reviews,
validates all referenced bundle/corpus bytes, directly replays exactly 105 controlled source
cases against the persisted Judge manifest and original raw `JudgeEvidence`, and—while those
ephemeral results are live—requires every case's complete hidden-plus-generated per-test matrix,
resolves the content-addressed 60-row natural materialization provenance, reconstructs the blind
human-review batch and decision replay, and validates the complete Task 6 benchmark chain. A
selection receipt, corpus audit, persisted qualification report, bare human-label set, or
deserialized boolean is never authority.

The shell interface requires these existing paths: `HY3_FORMAL_SELECTION`,
`HY3_FORMAL_ACQUISITION`, `HY3_FORMAL_ACQUISITION_VALIDATION`,
`HY3_FORMAL_VALIDATION_RAW`, `HY3_FORMAL_TEST_RAW`,
`HY3_FORMAL_VALIDATION_REVIEWS`, `HY3_FORMAL_TEST_REVIEWS`,
`HY3_FORMAL_REVIEW_MANIFEST`, `HY3_FORMAL_BUNDLES`, `HY3_FORMAL_CORPUS`,
`HY3_FORMAL_NATURAL_MATERIALIZATION`,
`HY3_FORMAL_DATA_ROOT`, `HY3_FORMAL_JUDGE_CASES`, `HY3_FORMAL_JUDGE_EVIDENCE`,
`HY3_FORMAL_JUDGE_RAW_EVIDENCE`, `HY3_FORMAL_BENCHMARK_CANDIDATE`,
`HY3_FORMAL_HUMAN_REVIEW_EXPORT`, `HY3_FORMAL_HUMAN_REVIEW_MAPPING`,
`HY3_FORMAL_HUMAN_DECISIONS`, `HY3_FORMAL_HUMAN_REVIEW_REPLAY`, and
`HY3_FORMAL_BENCHMARK_ROOT`; it also requires `HY3_FORMAL_VALIDATION_FORMAT` and
`HY3_FORMAL_TEST_FORMAT` (`json`, `jsonl`, `parquet`, or `riegeli`) and an existing
`HY3_FORMAL_QUALIFICATION_ROOT` directory.

Success creates exactly one safe report at
`$HY3_FORMAL_QUALIFICATION_ROOT/formal-qualification/<content_hash>.json`. It contains only
chain hashes, counts, and the attempt total—never identities, statements, tests, oracles, source,
raw evidence, counterexamples, credentials, or endpoint details. Re-running the same chain does
not overwrite it. This repository supplies no formal data, so the release gate remains blocking
until maintainers externally acquire/review the 30-problem/165-sample data, preserve the 105-case
raw Judge evidence, execute the live benchmark and human confirmation, and supply the complete
immutable inputs. No fixture or generated substitute is allowed.

For Compose, arrange `HY3_FORMAL_INPUT_ROOT_HOST` as `selection.json`, `acquisition.json`,
`acquisition-validation.json`, `validation.raw`, `test.raw`, `validation-reviews.json`,
`test-reviews.json`, `review-manifest.json`, `bundles.json`, `corpus.json`,
`judge-cases.json`, `judge-evidence.json`, `judge-raw-evidence.json`, plus `data/` and
`benchmark/`. Store the natural manifest at
`data/natural-materialization/<content_hash>.json`; keep human artifacts at the canonical
`benchmark/human-review/<batch>/...` create-only paths. Set
`HY3_FORMAL_BENCHMARK_ID`, `HY3_FORMAL_NATURAL_MATERIALIZATION_HASH`,
`HY3_FORMAL_HUMAN_REVIEW_BATCH_ID`, `HY3_FORMAL_HUMAN_DECISION_SET_ID`, and
`HY3_FORMAL_HUMAN_REPLAY_ID`, then run:

```sh
docker compose --profile formal-readiness run --build --rm formal-readiness
```

Only original-English, standard-stdin/stdout Codeforces entries with source attribution may be
candidates. Project-authored references are allowed; raw third-party submitted solutions are
not redistributed.

Protected internal dataset artifacts may be retained under access control for Judge and
provenance replay. They must never enter a model prompt, public/API/UI response, or a run
artifact. Public release material contains only safe summaries and hashes.

## Reproducibility, reviews, and reporting

Before a formal run, freeze source/acquisition, selection/corpus, Judge evidence, model and
credential-free endpoint identity, prompts/parameters, code/Judge image versions, metric
version, bootstrap settings, random seed, and the call ledger. Reserve every remote attempt
before transmission; the hard cap is 500 calls. Cache hits cost zero. A partial or exhausted
run is immutable evidence but not a formal result.

Each natural materialization row binds the exact corpus trace/source hashes and parsed trace,
verified problem record and model-visible input, repository generator-prompt hash, frozen model,
credential-free endpoint, type-preserving ordered parameters, recomputed cache key, and exact
generation-attempt event hashes. This is an immutable provenance/replay chain; it is not
cryptographic proof of what a remote service executed. The qualification report contains only
the combined materialization hash, never the prompt, statement, response, endpoint, or code.

Human review exports a blind package, keeps reviewer/mapping/replay artifacts separate, and
requires a delayed blind re-review of a seeded 20% sample. A single reviewer is not independent
verification; same-model generation and review can share bias. Use the create-only method,
results, and audit templates in `docs/`; they intentionally contain no claimed outcome.

## Security and attribution

- Runtime connection settings use `HY3_BASE_URL`, `HY3_API_KEY`, and `HY3_MODEL`; credentials
  never pass through Docker build args, artifacts, prompts, reports, screenshots, or logs.
  Optional `HY3_TIMEOUT_SECONDS` accepts finite positive seconds (default 60). For long
  non-streaming responses, export a larger value such as 300 into the CLI/API process.
  This changes HTTP waiting time, not model parameters or request budgets; the client does
  not automatically load `.env`.
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
