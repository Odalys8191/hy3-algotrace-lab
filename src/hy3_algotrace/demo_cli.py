"""Safe local-only driver used by the unrecorded two-minute demo checklist."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


class DemoConfigurationError(ValueError):
    """Raised for a target that is not the exact local FastAPI endpoint."""


def validate_local_demo_url(value: str) -> str:
    """Allow exactly an HTTP loopback authority with an explicit port and no suffix."""

    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise DemoConfigurationError("demo API URL port is invalid") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise DemoConfigurationError("demo API URL must be http://127.0.0.1:<port>")
    if not 1 <= port <= 65535:
        raise DemoConfigurationError("demo API URL port is invalid")
    return urlunsplit(("http", f"127.0.0.1:{port}", "", "", ""))


def run_demo(*, base_url: str, problem_id: str, timeout_seconds: float) -> Mapping[str, object]:
    """Submit one run, then return its terminal public report or first safe error."""

    safe_base = validate_local_demo_url(base_url)
    if timeout_seconds <= 0:
        raise DemoConfigurationError("demo timeout must be positive")
    _request_json(f"{safe_base}/api/v1/problems", method="GET")
    accepted = _request_json(
        f"{safe_base}/api/v1/runs",
        method="POST",
        payload={"schema_version": "1.2", "mode": "solve_and_audit", "problem_id": problem_id},
    )
    run_id = accepted.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise DemoConfigurationError("API did not return a run ID")
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = _request_json(f"{safe_base}/api/v1/runs/{run_id}", method="GET")
        if result.get("status") in {"completed", "failed"}:
            return result
        if time.monotonic() >= deadline:
            raise DemoConfigurationError("demo run did not reach a terminal state before timeout")
        time.sleep(0.5)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one local demo without printing credentials or hidden evidence."""

    parser = argparse.ArgumentParser(description="Run one local Hy3 AlgoTrace demo request.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--problem-id", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=110.0)
    arguments = parser.parse_args(argv)
    try:
        result = run_demo(
            base_url=arguments.base_url,
            problem_id=arguments.problem_id,
            timeout_seconds=arguments.timeout_seconds,
        )
    except (DemoConfigurationError, HTTPError, URLError, ValueError):
        print("demo failed; inspect the local API's public response or report")
        return 1
    print(json.dumps(_demo_summary(result), sort_keys=True, ensure_ascii=False))
    return 0


def _request_json(
    url: str, *, method: str, payload: Mapping[str, object] | None = None
) -> dict[str, object]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"content-type": "application/json"})
    with urlopen(request, timeout=15.0) as response:  # noqa: S310 - URL is validated above.
        decoded = json.loads(response.read().decode("utf-8"))
    if not isinstance(decoded, dict):
        raise DemoConfigurationError("API response must be a JSON object")
    return decoded


def _demo_summary(result: Mapping[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {"run_id": result.get("run_id"), "status": result.get("status")}
    if result.get("status") == "failed":
        summary["first_error"] = result.get("failure")
    elif result.get("status") == "completed":
        summary["report"] = result.get("report")
    return summary


if __name__ == "__main__":  # pragma: no cover - covered through main
    raise SystemExit(main())
