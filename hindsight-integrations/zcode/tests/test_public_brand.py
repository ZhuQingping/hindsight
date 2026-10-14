"""Public plugin identity and explicit local-engine distribution contract."""

import pytest
from lib.daemon import _get_embed_command
from lib.client import USER_AGENT


def test_local_engine_requires_distribution_configuration(monkeypatch):
    monkeypatch.delenv("AGENTSTRATUM_EMBED_PACKAGE", raising=False)
    with pytest.raises(RuntimeError, match="AGENTSTRATUM_EMBED_PACKAGE"):
        _get_embed_command({})


def test_local_engine_uses_explicit_distribution_and_branded_command():
    assert _get_embed_command({"embedPackage": "approved-engine==1.2.3"}) == [
        "uvx",
        "--quiet",
        "--from",
        "approved-engine==1.2.3",
        "agentstratum-embed",
    ]


def test_local_checkout_keeps_local_execution():
    assert _get_embed_command({"embedPackagePath": "/source/engine"}) == [
        "uv",
        "run",
        "--directory",
        "/source/engine",
        "agentstratum-embed",
    ]


def test_user_agent_uses_product_identity():
    assert "agentstratum" in USER_AGENT
    assert "hindsight" not in USER_AGENT.lower()


def test_engine_diagnostic_omits_internal_package_names():
    from lib.daemon import _diagnostic

    assert "hindsight" not in _diagnostic("Could not install Hindsight-embed").lower()
    assert _diagnostic("Connection refused") == "Connection refused"
