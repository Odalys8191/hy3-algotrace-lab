# Release and security boundaries

This is a localhost-only, local-single-user research application. Do not reverse-proxy it,
expose it to a LAN/internet, or use it as a multi-tenant code-execution service.

## Runtime configuration and image boundary

The model boundary reads only `HY3_BASE_URL`, `HY3_API_KEY`, and `HY3_MODEL` at process
runtime. The key is never a Docker build argument or artifact field. `.env.example` contains
placeholders only; a real local `.env` remains ignored and is excluded from Docker build context.
App runtime and Judge input images must use `repository@sha256` identities.
`docker/release-runtime-lock.json` lists the complete Python 3.12 dependency closure; a future
attested runtime image must include that exact closure **and Docker CLI**. The app build verifies
the bound image identity, lock hash, Docker CLI package attestation, and rejects any missing,
changed, or extra distribution before `pip --no-deps` installs this package. It performs no apt
operation, so mutable distro transitives cannot slip in. The checked-in `registry.invalid`
identity is intentionally not a runnable base image: release remains blocked until an
obtainable attested runtime recipe/image is supplied.

`docker compose up --build` is intentionally fail-closed if any required local runtime value,
formal catalog, immutable Judge image, or socket path is absent. Run the checks below; both
source and rendered Compose semantic checks reject short public ports, omitted `host_ip`,
`0.0.0.0`, and host network mode without trusting comments.

```sh
python -m hy3_algotrace.release_validation --root .
docker compose config --format json > /tmp/hy3-compose.json
python -m hy3_algotrace.release_validation --root . --rendered-compose /tmp/hy3-compose.json
```

## Docker socket risk

`HY3_DOCKER_SOCKET_PATH` deliberately has no default. If supplied, its host Docker socket gives
the API container effective host-root authority. Use it only on a controlled personal machine
for a local demonstration; never in a shared runner or public service. The per-run Judge
container's network/resource restrictions reduce the evaluated program's scope but cannot make
the socket mounting pattern production-safe. A missing Docker prerequisite is a hard failure,
not permission to execute submitted C++ on the host.

## Artifact, prompt, and public boundary

All run/configuration/report artifacts are create-only and content-addressed. Correct an error
by writing a new artifact that links to the earlier hash; never overwrite a run, benchmark
ledger, frozen selection, review decision, or chart.

Protected internal dataset artifacts (including hidden/generated tests and oracle material) are
allowed only under access control for Judge/provenance replay. They must never be copied into a
model prompt, public/API/UI response, or run artifact. Prompts and public objects use an
allowlist; logs and errors must not expose credentials, absolute paths, reference code, or
reviewer-only evidence.

The formal qualification output is a create-only hash summary. It excludes statements, public
and hidden tests, oracles, source, raw Judge evidence, diagnostics, counterexamples, credentials,
endpoint details, raw prompts/responses, and human reviewer identities. Natural-output and human
review provenance enter only as safe combined hashes. The `formal-readiness` Compose service
alone receives the read-only formal input mount and dedicated output mount; the Streamlit service
remains an HTTP-only API client.

## Secret detection

The Python validator rejects non-placeholder secret-like assignments without echoing their
values. CI fetches complete history and runs a SHA-pinned Gitleaks action with
`.gitleaks.toml`; its allowlist is restricted to named placeholder strings, not directories or
generic test paths. A historic finding requires credential rotation and a history remediation
decision—it is not resolved merely by deleting the current file.

For a workstation with Gitleaks installed, run `scripts/security-scan.sh`; it scans `--all`
history with redacted output and fails closed (`69`) if Gitleaks is absent.

The Python release scanner rejects bare lowercase and uppercase `api_key`, `token`, `secret`,
`password`, `private_key`, and `credential` assignments as well as prefixed variants. Its test
fixture exceptions are bound to exact file path, identifier, **and SHA-256 of the expected test
literal**; changing a literal cannot reuse the exception.
