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


def test_mcp_failure_preserves_public_service_error(monkeypatch):
    import asyncio
    import importlib.util
    import io
    import urllib.error
    from pathlib import Path

    from lib import config

    monkeypatch.setattr(
        config,
        "load_config",
        lambda: {"enableKnowledgeTools": True, "bankId": "b", "apiUrl": "https://service.example"},
    )
    script = Path(__file__).parent.parent / "scripts" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location("brand_test_mcp_server", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fail(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://service.example", 403, "error", {}, io.BytesIO(b"Access denied to bank hindsight-review")
        )

    monkeypatch.setattr("urllib.request.urlopen", fail)
    with pytest.raises(Exception) as error:
        asyncio.run(module.mcp.call_tool("agent_knowledge_list_pages", {}))
    assert "HTTP 403" in str(error.value)
    assert "Access denied to bank hindsight-review" in str(error.value)
