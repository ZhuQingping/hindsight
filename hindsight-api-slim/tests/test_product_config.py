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


def test_default_display_and_legacy_wire_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    from hindsight_api.api.http import create_app
    from hindsight_api.product_config import display_config

    monkeypatch.delenv("contextdb_name", raising=False)
    monkeypatch.delenv("product_display_name", raising=False)
    assert display_config().display_name == "ContextBase"
    assert product_config().model_dump() == {"product_config_version": 1, "contextdb_name": "contextbase"}
    app = create_app(MagicMock(), initialize_memory=False)
    client = TestClient(app)
    assert client.get("/product-config").json() == product_config().model_dump()
    assert client.get("/product-config").headers["x-product-display-name"] == "ContextBase"
    response = client.get("/product-config/v2")
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "product_config_version": 2,
        "contextdb_name": "contextbase",
        "display_name": "ContextBase",
    }
    assert app.openapi()["info"]["title"] == "ContextBase HTTP API"


@pytest.mark.parametrize("display", ["ContextBase", "Atlas Grove", "A", "Brand-42"])
def test_display_override_does_not_change_identity(monkeypatch: pytest.MonkeyPatch, display: str) -> None:
    from hindsight_api import brand
    from hindsight_api.product_config import display_config

    monkeypatch.setenv("contextdb_name", "legacy-deployment")
    monkeypatch.setenv("product_display_name", display)
    assert display_config().display_name == display
    assert product_config().contextdb_name == "legacy-deployment"
    assert brand.api_title() == f"{display} HTTP API"
    assert brand.mcp_server_name() == f"{display}-mcp-server"
    assert brand.WEBHOOK_EVENT_HEADER == "X-Agentstratum-Event"
    assert brand.service_name("worker") == "legacy-deployment-worker"


@pytest.mark.parametrize("display", ["", " leading", "trailing ", "a\n", "a\r\nb", "a/b", "<script>", "元壤", "a" * 81])
def test_invalid_display_fails_closed(monkeypatch: pytest.MonkeyPatch, display: str) -> None:
    from hindsight_api.product_config import display_config

    monkeypatch.setenv("product_display_name", display)
    with pytest.raises(ValidationError):
        display_config()


def test_strict_versions_and_secret_rejection() -> None:
    from hindsight_api.product_config import DisplayConfig, ProductConfig

    for value in [
        {"product_config_version": 2, "contextdb_name": "a"},
        {"contextdb_name": "a", "display_name": "ContextBase"},
        {"contextdb_name": "a", "api_key": "must-not-leak"},
    ]:
        with pytest.raises(ValidationError):
            ProductConfig.model_validate(value)
    with pytest.raises(ValidationError):
        DisplayConfig.model_validate({"product_config_version": 1, "contextdb_name": "a", "display_name": "A"})
