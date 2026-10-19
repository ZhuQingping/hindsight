"""Deployment display names do not rewrite fixed installation/protocol identity."""

import pytest

from hindsight_api import brand


@pytest.mark.parametrize("name", ["contextbase", "contextdb"])
def test_runtime_and_protocol_identity_have_distinct_authority(monkeypatch, name):
    monkeypatch.setenv("contextdb_name", name)
    assert brand.api_title() == f"{name} HTTP API"
    assert brand.mcp_server_name() == f"{name}-mcp-server"
    assert brand.service_name("api") == f"{name}-api"
    assert brand.service_name("worker") == f"{name}-worker"
    assert brand.PRODUCT_NAME == "contextbase"
    assert brand.WEBHOOK_EVENT_HEADER == "X-ContextBase-Event"
    assert brand.RERANKER_BANK_HEADER == "X-ContextBase-Bank-Id"


@pytest.mark.parametrize("name", ["contextbase", "contextdb"])
def test_actual_api_startup_display_uses_deployment_name(monkeypatch, capsys, name):
    import re

    from hindsight_api.banner import print_banner, print_startup_info

    monkeypatch.setenv("contextdb_name", name)
    print_banner()
    print_startup_info("127.0.0.1", 8888, "postgresql://fixture@localhost/demo", "none", "none", "none", "none")
    output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
    assert f"{name}: Agent Memory" in output
    assert f"Starting {name} API" in output
    assert brand.PRODUCT_NAME == "contextbase"


@pytest.mark.parametrize("name", ["ContextBase", "Atlas Grove"])
def test_display_only_override_keeps_default_telemetry_identity(monkeypatch, name):
    monkeypatch.delenv("contextdb_name", raising=False)
    monkeypatch.setenv("product_display_name", name)
    assert brand.service_name("api") == "contextbase-api"
    assert brand.service_name("worker") == "contextbase-worker"
    assert brand.api_title() == f"{name} HTTP API"
    assert brand.mcp_server_name() == f"{name}-mcp-server"
