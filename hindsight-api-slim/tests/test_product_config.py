"""Product naming changes configuration, not resource IDs or protocol paths."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from hindsight_api.product_config import product_config


@pytest.mark.parametrize("name", ["", "AgentStratum", "bad name", "foo\n", "a/b", "元壤", "a" * 41])
def test_invalid_product_name_rejected(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv("contextdb_name", name)
    with pytest.raises(ValidationError):
        product_config()


@pytest.mark.parametrize("name", ["agentstratum", "contextdb", "a", "data-42"])
def test_runtime_api_and_mcp_names(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    from hindsight_api.api.http import create_app
    from hindsight_api.api.mcp import create_mcp_server

    monkeypatch.setenv("contextdb_name", name)
    app = create_app(MagicMock(), initialize_memory=False)
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/product-config")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"product_config_version": 1, "contextdb_name": name}
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == f"{name} HTTP API"
    assert "/v1/default/banks/{bank_id}/memories/recall" in schema["paths"]
    with patch("hindsight_api.api.mcp.load_extension", return_value=None):
        mcp = create_mcp_server(MagicMock())
    assert mcp.name == f"{name}-mcp-server"
