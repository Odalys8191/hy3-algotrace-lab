#!/bin/sh
# Exit 3 means "not ready" rather than success. It never manufactures formal inputs.
set -eu

if [ ! -f src/hy3_algotrace/dataset_cli.py ]; then
    printf '%s\n' 'formal dataset tooling is not integrated; formal readiness is not ready' >&2
    exit 3
fi

for required in \
    "${HY3_FORMAL_SELECTION:-}" \
    "${HY3_FORMAL_ACQUISITION:-}" \
    "${HY3_FORMAL_ACQUISITION_VALIDATION:-}" \
    "${HY3_FORMAL_CONVERSION_VALIDATION:-}" \
    "${HY3_FORMAL_CONVERSION_TEST:-}" \
    "${HY3_FORMAL_QUOTA:-}" \
    "${HY3_FORMAL_BUNDLES:-}" \
    "${HY3_FORMAL_CORPUS:-}" \
    "${HY3_FORMAL_CORPUS_AUDIT:-}" \
    "${HY3_FORMAL_DATA_ROOT:-}"; do
    if [ -z "$required" ] || [ ! -e "$required" ]; then
        printf '%s\n' 'formal data inputs are absent; formal readiness is not ready' >&2
        exit 3
    fi
done

python -m hy3_algotrace.dataset_cli validate-selection "$HY3_FORMAL_SELECTION" \
    --conversion "$HY3_FORMAL_CONVERSION_VALIDATION" \
    --conversion "$HY3_FORMAL_CONVERSION_TEST" \
    --quota "$HY3_FORMAL_QUOTA" \
    --acquisition "$HY3_FORMAL_ACQUISITION" \
    --validation-report "$HY3_FORMAL_ACQUISITION_VALIDATION"
python -m hy3_algotrace.dataset_cli lint-bundles "$HY3_FORMAL_BUNDLES" \
    --root "$HY3_FORMAL_DATA_ROOT" --selection "$HY3_FORMAL_SELECTION"
python -m hy3_algotrace.dataset_cli lint-corpus "$HY3_FORMAL_CORPUS" \
    --root "$HY3_FORMAL_DATA_ROOT" --selection "$HY3_FORMAL_SELECTION" \
    --bundles "$HY3_FORMAL_BUNDLES" --output "$HY3_FORMAL_CORPUS_AUDIT"
