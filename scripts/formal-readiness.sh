#!/bin/sh
# Exit 3 means "not ready" rather than success. It never manufactures formal inputs.
set -eu

if [ ! -f src/hy3_algotrace/dataset_cli.py ]; then
    printf '%s\n' 'Task 7 dataset CLI is not integrated; formal readiness is not ready' >&2
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
    "${HY3_FORMAL_JUDGE_EVIDENCE:-}" \
    "${HY3_FORMAL_JUDGE_RAW_EVIDENCE:-}" \
    "${HY3_FORMAL_VALIDATION_RAW:-}" \
    "${HY3_FORMAL_TEST_RAW:-}" \
    "${HY3_FORMAL_VALIDATION_REVIEWS:-}" \
    "${HY3_FORMAL_TEST_REVIEWS:-}" \
    "${HY3_FORMAL_REVIEW_MANIFEST:-}" \
    "${HY3_FORMAL_DATA_ROOT:-}"; do
    if [ -z "$required" ] || [ ! -e "$required" ]; then
        printf '%s\n' 'formal data inputs are absent; formal readiness is not ready' >&2
        exit 3
    fi
done

for output in \
    "${HY3_FORMAL_SELECTION_REPLAY_RECEIPT:-}" \
    "${HY3_FORMAL_CORPUS_AUDIT:-}"; do
    case "$output" in
        */*) output_parent=${output%/*}; [ -n "$output_parent" ] || output_parent=/ ;;
        *) output_parent=. ;;
    esac
    if [ -z "$output" ] || [ -e "$output" ] || [ ! -d "$output_parent" ]; then
        printf '%s\n' 'formal create-only output is absent, already exists, or parent directory is not a directory; formal readiness is not ready' >&2
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

python -m hy3_algotrace.dataset_cli validate-selection-preliminary "$HY3_FORMAL_SELECTION" \
    --conversion "$HY3_FORMAL_CONVERSION_VALIDATION" \
    --conversion "$HY3_FORMAL_CONVERSION_TEST" \
    --quota "$HY3_FORMAL_QUOTA" \
    --acquisition "$HY3_FORMAL_ACQUISITION" \
    --validation-report "$HY3_FORMAL_ACQUISITION_VALIDATION"
python -m hy3_algotrace.dataset_cli verify-selection-chain "$HY3_FORMAL_SELECTION" \
    --validation-raw "$HY3_FORMAL_VALIDATION_RAW" \
    --test-raw "$HY3_FORMAL_TEST_RAW" \
    --validation-format "$HY3_FORMAL_VALIDATION_FORMAT" \
    --test-format "$HY3_FORMAL_TEST_FORMAT" \
    --validation-reviews "$HY3_FORMAL_VALIDATION_REVIEWS" \
    --test-reviews "$HY3_FORMAL_TEST_REVIEWS" \
    --review-manifest "$HY3_FORMAL_REVIEW_MANIFEST" \
    --acquisition "$HY3_FORMAL_ACQUISITION" \
    --validation-report "$HY3_FORMAL_ACQUISITION_VALIDATION" \
    --output "$HY3_FORMAL_SELECTION_REPLAY_RECEIPT"
python -m hy3_algotrace.dataset_cli lint-bundles "$HY3_FORMAL_BUNDLES" \
    --root "$HY3_FORMAL_DATA_ROOT" --selection "$HY3_FORMAL_SELECTION"
python -m hy3_algotrace.dataset_cli lint-corpus "$HY3_FORMAL_CORPUS" \
    --root "$HY3_FORMAL_DATA_ROOT" --selection "$HY3_FORMAL_SELECTION" \
    --bundles "$HY3_FORMAL_BUNDLES" --output "$HY3_FORMAL_CORPUS_AUDIT"

# A SelectionReplayReceipt has `capability_persisted=false`, and corpus lint reports only
# pending Judge evidence. Task 7 currently exposes no shell formal-Judge replay API for the
# protected raw JudgeEvidence plus FormalCorpusJudgeValidationReport. Do not infer eligibility
# from those persisted artifacts: a combined-tree integration must invoke
# validate_persisted_formal_judge_evidence in-process and retain the resulting capability only in
# memory, proving the 30 gold / 60 mutant / 15 paradox chain before this script may return zero.
printf '%s\n' 'formal Judge evidence replay integration is required; formal readiness is not ready' >&2
exit 3
