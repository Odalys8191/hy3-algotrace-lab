from __future__ import annotations

import pytest

from hy3_algotrace.demo_cli import DemoConfigurationError, validate_local_demo_url


@pytest.mark.parametrize(
    "url",
    (
        "https://127.0.0.1:8000",
        "http://evil.example@127.0.0.1:8000",
        "http://127.0.0.1:8000/",
        "http://127.0.0.1:8000/?redirect=evil.example",
        "http://127.0.0.1:8000/#fragment",
        "http://localhost:8000/path",
        "http://127.0.0.1",
        "http://127.0.0.1:99999",
    ),
)
def test_demo_url_guard_rejects_any_noncanonical_local_api_url(url: str) -> None:
    """The demo must not be tricked by userinfo, paths, or an implicit port."""

    with pytest.raises(DemoConfigurationError):
        validate_local_demo_url(url)


def test_demo_url_guard_allows_exact_loopback_http_endpoint() -> None:
    """The documented local API URL remains usable."""

    assert validate_local_demo_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"
