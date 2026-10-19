"""Public plugin identity and explicit local-engine distribution contract."""

import pytest
from lib.client import USER_AGENT
from lib.daemon import _get_embed_command


def test_local_engine_requires_distribution_configuration(monkeypatch):
    monkeypatch.delenv("CONTEXTBASE_EMBED_PACKAGE", raising=False)
    with pytest.raises(RuntimeError, match="CONTEXTBASE_EMBED_PACKAGE"):
        _get_embed_command({})


def test_local_engine_uses_explicit_distribution_and_branded_command():
    assert _get_embed_command({"embedPackage": "approved-engine==1.2.3"}) == [
        "uvx",
        "--quiet",
        "--from",
        "approved-engine==1.2.3",
        "contextbase-embed",
    ]


def test_local_checkout_keeps_local_execution():
    assert _get_embed_command({"embedPackagePath": "/source/engine"}) == [
        "uv",
        "run",
        "--directory",
        "/source/engine",
        "contextbase-embed",
    ]


def test_user_agent_uses_product_identity():
    assert "contextbase" in USER_AGENT
    assert "hindsight" not in USER_AGENT.lower()


@pytest.mark.parametrize("bank", ["hindsight-review", "Hindsight-review", "HINDSIGHT-review"])
def test_client_preserves_public_service_error(monkeypatch: pytest.MonkeyPatch, bank: str) -> None:
    import io
    import urllib.error

    from lib.client import HindsightClient

    message = f"Access denied to bank {bank}"
    upstream = urllib.error.HTTPError("https://service.example", 403, "Forbidden", {}, io.BytesIO(message.encode()))

    def fail(*args: object, **kwargs: object) -> None:
        raise upstream

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(RuntimeError) as error:
        HindsightClient("https://service.example")._request("GET", f"/v1/default/banks/{bank}")
    assert "HTTP 403" in str(error.value)
    assert message in str(error.value)
    assert error.value.__cause__ is upstream
