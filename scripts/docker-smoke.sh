#!/bin/sh
# CI-only smoke test: use repository Variables containing immutable public image metadata.
set -eu

require_value() {
    case "$1" in
        HY3_APP_RUNTIME_IMAGE) value=${HY3_APP_RUNTIME_IMAGE:-} ;;
        HY3_DOCKER_CLI_PACKAGE) value=${HY3_DOCKER_CLI_PACKAGE:-} ;;
        HY3_JUDGE_IMAGE) value=${HY3_JUDGE_IMAGE:-} ;;
        HY3_JUDGE_VALIDATOR_IMAGE) value=${HY3_JUDGE_VALIDATOR_IMAGE:-} ;;
        HY3_JUDGE_BASE_IMAGE) value=${HY3_JUDGE_BASE_IMAGE:-} ;;
        HY3_JUDGE_TIME_PACKAGE) value=${HY3_JUDGE_TIME_PACKAGE:-} ;;
        HY3_JUDGE_UTIL_LINUX_PACKAGE) value=${HY3_JUDGE_UTIL_LINUX_PACKAGE:-} ;;
        *) exit 64 ;;
    esac
    if [ -z "$value" ]; then
        printf '%s\n' "missing pinned Docker CI variable: $1" >&2
        exit 64
    fi
}

for name in \
    HY3_APP_RUNTIME_IMAGE HY3_DOCKER_CLI_PACKAGE HY3_JUDGE_IMAGE \
    HY3_JUDGE_VALIDATOR_IMAGE HY3_JUDGE_BASE_IMAGE \
    HY3_JUDGE_TIME_PACKAGE HY3_JUDGE_UTIL_LINUX_PACKAGE; do
    require_value "$name"
done

case "$HY3_APP_RUNTIME_IMAGE" in *@sha256:*) ;; *) exit 64 ;; esac
case "$HY3_JUDGE_IMAGE" in *@sha256:*) ;; *) exit 64 ;; esac
case "$HY3_JUDGE_VALIDATOR_IMAGE" in *@sha256:*) ;; *) exit 64 ;; esac
case "$HY3_JUDGE_BASE_IMAGE" in *@sha256:*) ;; *) exit 64 ;; esac
case "$HY3_DOCKER_CLI_PACKAGE" in docker.io=*) ;; *) exit 64 ;; esac
case "$HY3_JUDGE_TIME_PACKAGE" in time=*) ;; *) exit 64 ;; esac
case "$HY3_JUDGE_UTIL_LINUX_PACKAGE" in util-linux=*) ;; *) exit 64 ;; esac

export HY3_BASE_URL=http://127.0.0.1:9
export HY3_API_KEY=YOUR_HY3_API_KEY
export HY3_MODEL=ci-smoke-model
export HY3_CATALOG_ROOT_HOST=/tmp
export HY3_DOCKER_SOCKET_PATH=/var/run/docker.sock
export HY3_API_PORT=8000
export HY3_UI_PORT=8501

docker compose --profile ui config --format json > /tmp/hy3-compose.json
python -m hy3_algotrace.release_validation --root . --rendered-compose /tmp/hy3-compose.json

docker build --file docker/app/Dockerfile --tag hy3-algotrace-local:ci .
docker run --rm hy3-algotrace-local:ci python -c \
    'import fastapi, streamlit, uvicorn; import hy3_algotrace.local_app'
docker run --rm hy3-algotrace-local:ci streamlit --version

validator_repository=${HY3_JUDGE_VALIDATOR_IMAGE%@sha256:*}
validator_digest=${HY3_JUDGE_VALIDATOR_IMAGE#*@sha256:}
docker build --file docker/judge/Dockerfile --tag hy3-algotrace-judge:ci \
    --build-arg "JUDGE_VALIDATOR_REPOSITORY=$validator_repository" \
    --build-arg "JUDGE_VALIDATOR_DIGEST=$validator_digest" \
    --build-arg "JUDGE_BASE_IMAGE=$HY3_JUDGE_BASE_IMAGE" \
    --build-arg "JUDGE_TIME_PACKAGE=$HY3_JUDGE_TIME_PACKAGE" \
    --build-arg "JUDGE_UTIL_LINUX_PACKAGE=$HY3_JUDGE_UTIL_LINUX_PACKAGE" \
    docker/judge
