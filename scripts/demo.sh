#!/bin/sh
set -eu

: "${HY3_DEMO_API_BASE_URL:=http://127.0.0.1:8000}"
: "${HY3_DEMO_PROBLEM_ID:?Set HY3_DEMO_PROBLEM_ID to a verified built-in problem ID.}"

case "$HY3_DEMO_API_BASE_URL" in
    http://127.0.0.1:*|http://localhost:*) ;;
    *) echo "Refusing a non-local demo API URL" >&2; exit 64 ;;
esac

python -m hy3_algotrace.release_validation --root .
curl --fail --silent --show-error "$HY3_DEMO_API_BASE_URL/api/v1/problems" >/dev/null
curl --fail --silent --show-error \
    --request POST "$HY3_DEMO_API_BASE_URL/api/v1/runs" \
    --header 'content-type: application/json' \
    --data "{\"schema_version\":\"1.2\",\"mode\":\"solve_and_audit\",\"problem_id\":\"$HY3_DEMO_PROBLEM_ID\"}"

printf '%s\n' 'Submitted one local demo run. Poll its public run_id before recording.'
