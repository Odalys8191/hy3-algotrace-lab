from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from hy3_algotrace.release_validation import (
    ReleaseValidationError,
    _runtime_lock_hash,
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


def test_release_validation_rejects_secret_suffixed_to_a_placeholder_prefix() -> None:
    """A marker must be an exact placeholder, not a prefix that hides a credential."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": "api_key=YOUR_API_KEY_live-secret-suffix\n",
            }
        )


def test_release_validation_rejects_secret_after_environment_expansion() -> None:
    """An environment placeholder is safe only when it is the entire assigned value."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": "api_key=${HY3_API_KEY}sk-proj-appended-secret\n",
            }
        )


@pytest.mark.parametrize(
    "assignment",
    (
        "api_key=${HY3_API_KEY}",
        "api_key=${HY3_API_KEY:-YOUR_HY3_API_KEY}",
        "api_key=${HY3_API_KEY:?Set the authorised Hy3 credential locally.}",
        "token=${{ github.token }}",
    ),
)
def test_release_validation_accepts_only_complete_runtime_expressions(assignment: str) -> None:
    """Nonliteral CI/Compose expressions are safe only as a complete assigned value."""

    report = validate_release_files(
        {
            "README.md": "个人活动实战作品，非腾讯官方发布\n",
            "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
            "notes.py": f"{assignment}\n",
        }
    )

    assert report.secret_findings == ()


@pytest.mark.parametrize(
    "assignment",
    (
        "api_key=${HY3_API_KEY}sk-proj-appended-secret",
        "api_key=${HY3_API_KEY:-YOUR_HY3_API_KEY}sk-proj-appended-secret",
        "api_key=${HY3_API_KEY:-sk-proj-default-secret}",
        "api_key=${HY3_API_KEY:?Set the authorised credential locally.}sk-proj-appended-secret",
        "token=${{ github.token }}sk-proj-appended-secret",
    ),
)
def test_release_validation_rejects_secret_after_complete_runtime_expression(
    assignment: str,
) -> None:
    """A complete expression cannot be followed by a real secret."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": f"{assignment}\n",
            }
        )


@pytest.mark.parametrize(
    "assignment",
    (
        "api_key=${HY3_API_KEY:?sk-proj-message-secret}",
        "api_key=${HY3_API_KEY:?random-credential-message}",
        "api_key=<YOUR_API_KEY><credential-suffix>",
        "api_key=YOUR_CREDENTIAL_API_KEY",
    ),
)
def test_release_validation_rejects_credential_disguised_as_a_placeholder(
    assignment: str,
) -> None:
    """Only exact, repository-approved placeholder forms may suppress secret findings."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": f"{assignment}\n",
            }
        )


@pytest.mark.parametrize(
    "assignment",
    (
        'api_key=os.getenv("HY3_API_KEY")',
        'api_key=os.environ.get("HY3_API_KEY", "")',
        'api_key=os.environ["HY3_API_KEY"]',
        "api_key=field(repr=False)",
    ),
)
def test_release_validation_accepts_only_whole_safe_secret_access_expressions(
    assignment: str,
) -> None:
    """Source accessors may be nonliteral only as exact safe expressions."""

    report = validate_release_files(
        {
            "README.md": "个人活动实战作品，非腾讯官方发布\n",
            "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
            "notes.py": f"{assignment}\n",
        }
    )

    assert report.secret_findings == ()


@pytest.mark.parametrize(
    "assignment",
    (
        'api_key=os.getenv("HY3_API_KEY") + "sk-proj-appended-secret"',
        'api_key=os.environ.get("HY3_API_KEY", "sk-proj-default-secret")',
        'api_key=field(repr=False) + "sk-proj-appended-secret"',
    ),
)
def test_release_validation_rejects_secret_accessor_expression_composition(
    assignment: str,
) -> None:
    """An accessor prefix cannot mask a literal appended or supplied as a default."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": f"{assignment}\n",
            }
        )


def test_gitleaks_config_extends_defaults_with_anchored_placeholder_allowlist() -> None:
    """The custom allowlist supplements official rules and cannot match a longer secret."""

    config = tomllib.loads((REPOSITORY_ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))

    assert config["extend"]["useDefault"] is True
    allowlist = config["allowlist"]
    assert allowlist["regexTarget"] == "match"
    assert all(
        expression.startswith("^") and expression.endswith("$")
        for expression in allowlist["regexes"]
    )


def test_release_validation_fixture_allowlist_requires_exact_path_identifier_and_value() -> None:
    """The sole fixture is pinned, so a changed secret cannot hide behind its name."""

    safe_files = {
        "README.md": "个人活动实战作品，非腾讯官方发布\n",
        "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
        "tests/test_run_service.py": 'raw_secret = "background-secret-HY3_API_KEY"\n',
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

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                **safe_files,
                "tests/test_run_service.py": 'raw_secret = "changed-fixture-value"\n',
            }
        )


@pytest.mark.parametrize(
    "assignment",
    (
        "api_key=live-value-not-a-placeholder",
        "token=live-value-not-a-placeholder",
        "secret=live-value-not-a-placeholder",
        "password=live-value-not-a-placeholder",
        "private_key=live-value-not-a-placeholder",
        "credential=live-value-not-a-placeholder",
    ),
)
def test_release_validation_rejects_lowercase_bare_secret_names(assignment: str) -> None:
    """Lowercase bare names cannot bypass the checked-in secret scanner."""

    with pytest.raises(ReleaseValidationError, match="secret-like value"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "notes.py": assignment + "\n",
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


@pytest.mark.parametrize(
    "distribution",
    ("pip", "watchdog", "pathspec", "pluggy", "trove-classifiers"),
)
def test_release_validation_requires_every_release_runtime_closure_distribution(
    distribution: str,
) -> None:
    """A recomputed hash cannot turn a partial runtime closure into a valid release lock."""

    lock = json.loads((REPOSITORY_ROOT / "docker/release-runtime-lock.json").read_text())
    del lock["distributions"][distribution]
    lock["content_sha256"] = _runtime_lock_hash(lock)

    with pytest.raises(ReleaseValidationError, match="runtime lock"):
        validate_release_files(
            {
                "README.md": "个人活动实战作品，非腾讯官方发布\n",
                "compose.yaml": 'services:\n  api:\n    ports: ["127.0.0.1:8000:8000"]\n',
                "docker/release-runtime-lock.json": json.dumps(lock),
            }
        )
