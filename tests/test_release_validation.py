from __future__ import annotations

import json
from pathlib import Path

import pytest

from hy3_algotrace.release_validation import (
    ReleaseValidationError,
    validate_release_files,
    validate_release_tree,
    validate_rendered_compose,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_release_tree_has_required_disclosure_and_safe_local_configuration() -> None:
    """The checked-in release surface must be honest and localhost-only."""

    report = validate_release_tree(REPOSITORY_ROOT)

    assert report.checked_files
    assert report.secret_findings == ()


def test_release_validation_fails_closed_when_required_files_are_missing(tmp_path: Path) -> None:
    """A partial release directory cannot be reported as ready."""

    with pytest.raises(ReleaseValidationError, match="missing required release file"):
        validate_release_tree(tmp_path)


def test_release_validation_rejects_real_secret_and_nonlocal_port_mapping() -> None:
    """A release artifact must not expose credentials or a public bind."""

    with pytest.raises(ReleaseValidationError) as error:
        validate_release_files(
            {
                ".env.example": "HY3_API_KEY=sk-real-secret-value\n",
                "compose.yaml": 'ports: ["0.0.0.0:8000:8000"]\n',
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
            }
        )

    message = str(error.value)
    assert "secret-like value" in message
    assert "localhost" in message


@pytest.mark.parametrize(
    "compose",
    (
        'services:\n  api:\n    ports: ["8000:8000"]\n',
        "services:\n  api:\n    # 127.0.0.1 is safe only in this comment\n"
        "    ports:\n      - target: 8000\n        published: 8000\n        host_ip: 0.0.0.0\n",
        "services:\n  api:\n    ports:\n      - target: 8000\n        published: 8000\n",
    ),
)
def test_release_validation_rejects_public_compose_semantic_bypasses(compose: str) -> None:
    """Every published port must declare a localhost host IP, not merely mention one."""

    with pytest.raises(ReleaseValidationError, match="Compose port mappings"):
        validate_release_files(
            {
                ".env.example": "HY3_API_KEY=YOUR_HY3_API_KEY\n",
                "compose.yaml": compose,
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
            }
        )


def test_release_validation_detects_generic_credential_assignment() -> None:
    """Secret scanning must not be limited to the project-branded key name."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                ".env.example": "OPENAI_API_KEY=live-value-not-a-placeholder\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
            }
        )


def test_release_validation_fixture_allowlist_requires_exact_path_and_identifier() -> None:
    """The sole redaction fixture cannot become a broad test-directory exemption."""

    safe_files = {
        "README.md": "个人活动实战作品，非腾讯官方发布\n",
        "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
        "tests/test_run_service.py": 'raw_secret = "fixture-only-value"\n',
    }
    assert validate_release_files(safe_files).secret_findings == ()

    for path, name in (
        ("tests/other_test.py", "raw_secret"),
        ("tests/test_run_service.py", "other_secret"),
    ):
        with pytest.raises(ReleaseValidationError, match="secret-like value"):
            validate_release_files(
                {
                    **safe_files,
                    path: f'{name} = "not-an-allowed-fixture"\n',
                }
            )


@pytest.mark.parametrize(
    "port",
    (
        "8000:8000",
        {"target": 8000, "published": "8000"},
        {"target": 8000, "published": "8000", "host_ip": "0.0.0.0"},
    ),
)
def test_rendered_compose_rejects_docker_public_port_defaults(port: object) -> None:
    """Rendered semantics reject public defaults even when source comments look safe."""

    with pytest.raises(ReleaseValidationError, match="Compose port mappings"):
        validate_rendered_compose({"services": {"api": {"ports": [port]}}})


def test_rendered_compose_accepts_explicit_loopback_only() -> None:
    """Only a rendered loopback mapping is eligible for the local release surface."""

    validate_rendered_compose(
        {
            "services": {
                "api": {"ports": [{"target": 8000, "published": "8000", "host_ip": "127.0.0.1"}]}
            }
        }
    )


def test_release_validation_rejects_incomplete_runtime_lock() -> None:
    """A mutable or partial dependency declaration is not a release lock."""

    with pytest.raises(ReleaseValidationError, match="runtime lock"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "docker/release-runtime-lock.json": json.dumps(
                    {"schema_version": 1, "lock_kind": "immutable_runtime_image", "python": "3.12"}
                ),
            }
        )
