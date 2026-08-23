from __future__ import annotations

from pathlib import Path

import pytest

from hy3_algotrace.release_validation import (
    ReleaseValidationError,
    validate_release_files,
    validate_release_tree,
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
