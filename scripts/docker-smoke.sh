#!/bin/sh
# CI-only Docker integration test: no real Hy3 request is allowed to leave the runner.
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

compose_args='-f compose.yaml -f docker/ci/compose.stub.yaml'
docker compose $compose_args config --format json > /tmp/hy3-compose.json
python -m hy3_algotrace.release_validation --root . --rendered-compose /tmp/hy3-compose.json

docker build \
    --file docker/app/Dockerfile \
    --build-arg "HY3_APP_RUNTIME_IMAGE=$HY3_APP_RUNTIME_IMAGE" \
    --build-arg "HY3_DOCKER_CLI_PACKAGE=$HY3_DOCKER_CLI_PACKAGE" \
    --tag hy3-algotrace-local:dev .

validator_repository=${HY3_JUDGE_VALIDATOR_IMAGE%@sha256:*}
validator_digest=${HY3_JUDGE_VALIDATOR_IMAGE#*@sha256:}
docker build --file docker/judge/Dockerfile --tag hy3-algotrace-judge:ci \
    --build-arg "JUDGE_VALIDATOR_REPOSITORY=$validator_repository" \
    --build-arg "JUDGE_VALIDATOR_DIGEST=$validator_digest" \
    --build-arg "JUDGE_BASE_IMAGE=$HY3_JUDGE_BASE_IMAGE" \
    --build-arg "JUDGE_TIME_PACKAGE=$HY3_JUDGE_TIME_PACKAGE" \
    --build-arg "JUDGE_UTIL_LINUX_PACKAGE=$HY3_JUDGE_UTIL_LINUX_PACKAGE" \
    docker/judge

cleanup() {
    docker compose $compose_args down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f /tmp/hy3-compose.json /tmp/hy3-run.json
}
trap cleanup EXIT INT TERM

# The override runs ci_stub_app: it creates a deterministic fixture catalog and in-process
# generator/reviewer/Judge.  It exercises normal public HTTP routes but never reads HY3_BASE_URL
# or sends a credential.  It is not a formal data, model, or Judge-success claim.
docker compose $compose_args up --detach --no-build api
attempt=0
until curl --fail --silent --show-error http://127.0.0.1:8000/api/v1/problems >/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 30 ]; then
        docker compose $compose_args logs api >&2 || true
        exit 1
    fi
    sleep 1
done

curl --fail --silent --show-error \
    -H 'content-type: application/json' \
    --data '{"schema_version":"1.2","mode":"solve_and_audit","problem_id":"cf-123-a"}' \
    http://127.0.0.1:8000/api/v1/runs > /tmp/hy3-run.json
run_id=$(python -c 'import json; print(json.load(open("/tmp/hy3-run.json"))["run_id"])')
curl --fail --silent --show-error "http://127.0.0.1:8000/api/v1/runs/$run_id" > /tmp/hy3-run.json
python -c 'import json; payload=json.load(open("/tmp/hy3-run.json")); assert payload["status"] == "completed"; assert payload["report"]["audit"]["final_correct"] is True'
