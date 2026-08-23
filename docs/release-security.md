# Release and security boundaries

This is a local, single-user research application. Bind the API and UI only to localhost;
do not reverse-proxy or expose them to the internet. The C++17 Docker Judge is a constrained
local execution component, not a production internet sandbox or a multi-tenant isolation
guarantee.

## Credentials and release validation

`HY3_API_KEY` is read only from the local process environment. Do not add it to code, test
fixtures, Docker build arguments, artifacts, reports, screenshots, shell history, or logs.
`.env.example` contains placeholders only and `.env` is ignored. Run:

```sh
python -m hy3_algotrace.release_validation --root .
```

The command fails closed if release files are absent, the required Chinese non-official
disclaimer is absent, a Compose port is published on a non-localhost address, or a tracked
text file contains a non-placeholder value assigned to an API key/token/secret/password
variable. It does not print the suspected value.

## Artifact and data boundary

All persistent run and benchmark artifacts are create-only and content-addressed. Never
overwrite an existing run, human-review decision, benchmark ledger, frozen selection, or
formal report. Correct an error by creating a new versioned artifact and recording why the
previous artifact is superseded.

Only original-English Codeforces statements and public examples may enter a generation
prompt. Hidden/generated tests, oracle facts, reference answers, reviewer-only diagnostics,
and local paths remain outside public API/UI responses and model prompts. Do not redistribute
raw CodeContests records or third-party submitted code.

## Operational checks

Run static/unit/release checks before publication. Docker Judge checks require a locally
available Docker daemon and are skipped explicitly when unavailable; a skipped Docker test is
not evidence of production safety. Never represent a local smoke test as an internet-sandbox
assessment.
