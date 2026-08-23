#!/bin/sh
# A release requires completed formal Judge replay; a pending data layer blocks release.
set -eu

set +e
scripts/formal-readiness.sh
status=$?
set -e

if [ "$status" -eq 0 ]; then
    exit 0
fi
if [ "$status" -eq 3 ]; then
    printf '%s\n' 'formal release gate blocked: persisted/replayed Task 7 Judge evidence is not ready' >&2
    exit 1
fi
exit "$status"
