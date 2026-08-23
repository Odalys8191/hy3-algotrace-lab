# The digest-pinned runtime image contains every dependency *and the Docker CLI* in
# release-runtime-lock.json. This Dockerfile never runs apt: doing so would resolve mutable
# distro transitives outside the attested runtime image.
ARG HY3_APP_RUNTIME_IMAGE
FROM ${HY3_APP_RUNTIME_IMAGE}

ARG HY3_APP_RUNTIME_IMAGE
ARG HY3_DOCKER_CLI_PACKAGE

WORKDIR /opt/hy3-algotrace
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN printf '%s\n' "$HY3_APP_RUNTIME_IMAGE" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9._:/-]*@sha256:[0-9a-f]{64}$' \
    && printf '%s\n' "$HY3_DOCKER_CLI_PACKAGE" | grep -Eq '^docker.io=[A-Za-z0-9][A-Za-z0-9.+:~_-]*$' \
    && command -v docker >/dev/null \
    && docker --version >/dev/null

COPY docker/release-runtime-lock.json docker/verify-runtime-lock.py /tmp/
RUN python /tmp/verify-runtime-lock.py \
    --runtime-image "$HY3_APP_RUNTIME_IMAGE" \
    --docker-cli-package "$HY3_DOCKER_CLI_PACKAGE"

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-build-isolation --no-deps .

CMD ["python", "-m", "uvicorn", "hy3_algotrace.local_app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
