#!/bin/sh
# Wrapper for a verified Task 7 data layer; no fallback dataset or dummy report exists.
set -eu

if [ ! -f src/hy3_algotrace/dataset_cli.py ]; then
    printf '%s\n' 'Task 7 dataset CLI is not integrated; refusing data lint' >&2
    exit 3
fi

: "${HY3_ACQUISITION_MANIFEST:?Set immutable acquisition manifest path.}"
: "${HY3_RAW_VALIDATION:?Set acquired validation split path.}"
: "${HY3_RAW_TEST:?Set acquired test split path.}"
: "${HY3_ACQUISITION_REPORT:?Set create-only acquisition report output path.}"

python -m hy3_algotrace.dataset_cli validate-acquisition "$HY3_ACQUISITION_MANIFEST" \
    --validation "$HY3_RAW_VALIDATION" --test "$HY3_RAW_TEST" \
    --output "$HY3_ACQUISITION_REPORT"

exec scripts/formal-readiness.sh
