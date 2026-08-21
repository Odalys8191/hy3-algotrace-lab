FROM gcc:13.3.0-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends time \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 judge \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin judge

COPY runner.sh /usr/local/bin/hy3-judge-runner
RUN chown root:root /usr/local/bin/hy3-judge-runner \
    && chmod 0555 /usr/local/bin/hy3-judge-runner

USER 65532:65532
ENTRYPOINT ["/usr/local/bin/hy3-judge-runner"]
