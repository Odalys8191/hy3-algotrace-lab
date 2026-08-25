#!/bin/sh
# Exit 3 means complete external formal inputs are absent. Validation failures propagate.
set -eu

for required_file in \
    "${HY3_FORMAL_SELECTION:-}" \
    "${HY3_FORMAL_ACQUISITION:-}" \
    "${HY3_FORMAL_ACQUISITION_VALIDATION:-}" \
    "${HY3_FORMAL_VALIDATION_RAW:-}" \
    "${HY3_FORMAL_TEST_RAW:-}" \
    "${HY3_FORMAL_VALIDATION_REVIEWS:-}" \
    "${HY3_FORMAL_TEST_REVIEWS:-}" \
    "${HY3_FORMAL_REVIEW_MANIFEST:-}" \
    "${HY3_FORMAL_BUNDLES:-}" \
    "${HY3_FORMAL_CORPUS:-}" \
    "${HY3_FORMAL_JUDGE_CASES:-}" \
    "${HY3_FORMAL_JUDGE_EVIDENCE:-}" \
    "${HY3_FORMAL_JUDGE_RAW_EVIDENCE:-}" \
    "${HY3_FORMAL_BENCHMARK_CANDIDATE:-}"; do
    if [ -z "$required_file" ] || [ ! -f "$required_file" ]; then
        printf '%s\n' 'formal qualification inputs are absent; formal readiness is not ready' >&2
        exit 3
    fi
done

for required_directory in \
    "${HY3_FORMAL_DATA_ROOT:-}" \
    "${HY3_FORMAL_BENCHMARK_ROOT:-}" \
    "${HY3_FORMAL_QUALIFICATION_ROOT:-}"; do
    if [ -z "$required_directory" ] || [ ! -d "$required_directory" ]; then
        printf '%s\n' 'formal qualification inputs are absent; formal readiness is not ready' >&2
        exit 3
    fi
done

case "${HY3_FORMAL_VALIDATION_FORMAT:-}" in json|jsonl|parquet|riegeli) ;; *)
    printf '%s\n' 'formal validation format is invalid; formal readiness is not ready' >&2
    exit 3
esac
case "${HY3_FORMAL_TEST_FORMAT:-}" in json|jsonl|parquet|riegeli) ;; *)
    printf '%s\n' 'formal test format is invalid; formal readiness is not ready' >&2
    exit 3
esac

python -m hy3_algotrace.formal_qualification \
    --selection "$HY3_FORMAL_SELECTION" \
    --acquisition "$HY3_FORMAL_ACQUISITION" \
    --acquisition-validation "$HY3_FORMAL_ACQUISITION_VALIDATION" \
    --validation-raw "$HY3_FORMAL_VALIDATION_RAW" \
    --test-raw "$HY3_FORMAL_TEST_RAW" \
    --validation-format "$HY3_FORMAL_VALIDATION_FORMAT" \
    --test-format "$HY3_FORMAL_TEST_FORMAT" \
    --validation-reviews "$HY3_FORMAL_VALIDATION_REVIEWS" \
    --test-reviews "$HY3_FORMAL_TEST_REVIEWS" \
    --review-manifest "$HY3_FORMAL_REVIEW_MANIFEST" \
    --bundles "$HY3_FORMAL_BUNDLES" \
    --corpus "$HY3_FORMAL_CORPUS" \
    --data-root "$HY3_FORMAL_DATA_ROOT" \
    --judge-cases "$HY3_FORMAL_JUDGE_CASES" \
    --judge-report "$HY3_FORMAL_JUDGE_EVIDENCE" \
    --judge-raw-evidence "$HY3_FORMAL_JUDGE_RAW_EVIDENCE" \
    --candidate "$HY3_FORMAL_BENCHMARK_CANDIDATE" \
    --benchmark-root "$HY3_FORMAL_BENCHMARK_ROOT" \
    --output-root "$HY3_FORMAL_QUALIFICATION_ROOT"
