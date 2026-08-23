ARG JUDGE_VALIDATOR_REPOSITORY
ARG JUDGE_VALIDATOR_DIGEST
ARG JUDGE_BASE_IMAGE
FROM ${JUDGE_VALIDATOR_REPOSITORY}@sha256:${JUDGE_VALIDATOR_DIGEST} AS input-validator

ARG JUDGE_BASE_IMAGE
ARG JUDGE_TIME_PACKAGE
ARG JUDGE_UTIL_LINUX_PACKAGE

COPY validate-build-args.sh /usr/local/bin/hy3-validate-build-args
RUN chown root:root /usr/local/bin/hy3-validate-build-args \
    && chmod 0555 /usr/local/bin/hy3-validate-build-args \
    && /usr/local/bin/hy3-validate-build-args \
        "$JUDGE_BASE_IMAGE" \
        "$JUDGE_TIME_PACKAGE" \
        "$JUDGE_UTIL_LINUX_PACKAGE" \
    && mkdir -p /validation \
    && printf 'validated\n' > /validation/build-args

FROM ${JUDGE_BASE_IMAGE} AS judge

ARG JUDGE_TIME_PACKAGE
ARG JUDGE_UTIL_LINUX_PACKAGE

COPY --from=input-validator /validation/build-args /usr/local/share/hy3-build-args

RUN test "$(cat /usr/local/share/hy3-build-args)" = validated \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        "$JUDGE_TIME_PACKAGE" \
        "$JUDGE_UTIL_LINUX_PACKAGE" \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 judge \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin judge

COPY runner.sh /usr/local/bin/hy3-judge-runner
RUN chown root:root /usr/local/bin/hy3-judge-runner \
    && chmod 0555 /usr/local/bin/hy3-judge-runner

USER 65532:65532
ENTRYPOINT ["/usr/local/bin/hy3-judge-runner"]
