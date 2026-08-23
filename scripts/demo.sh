#!/bin/sh
set -eu

: "${HY3_DEMO_API_BASE_URL:=http://127.0.0.1:8000}"
: "${HY3_DEMO_PROBLEM_ID:?Set HY3_DEMO_PROBLEM_ID to a verified built-in problem ID.}"

python -m hy3_algotrace.release_validation --root .
python -m hy3_algotrace.demo_cli \
    --base-url "$HY3_DEMO_API_BASE_URL" \
    --problem-id "$HY3_DEMO_PROBLEM_ID" \
    --timeout-seconds "${HY3_DEMO_TIMEOUT_SECONDS:-110}"
