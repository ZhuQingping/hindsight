"""Validate that the example config files parse correctly and have the expected structure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

INTEGRATION_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def manifest() -> dict:
    path = INTEGRATION_DIR / "manifest.example.yaml"
    return yaml.safe_load(path.read_text())


@pytest.fixture
def mcp_config() -> dict:
    path = INTEGRATION_DIR / "mcp_config.example.json"
    return json.loads(path.read_text())


class TestManifestYAML:
    def test_parses_without_error(self, manifest: dict) -> None:
        assert isinstance(manifest, dict)

    def test_has_tools_section(self, manifest: dict) -> None:
        assert "tools" in manifest
        assert "mcp_servers" in manifest["tools"]

    def test_mcp_server_entry_structure(self, manifest: dict) -> None:
        servers = manifest["tools"]["mcp_servers"]
        assert len(servers) >= 1

        contextbase = servers[0]
        assert contextbase["name"] == "contextbase"
        assert "endpoint" in contextbase
        assert "description" in contextbase

    def test_endpoint_is_https(self, manifest: dict) -> None:
        endpoint = manifest["tools"]["mcp_servers"][0]["endpoint"]
        assert endpoint.startswith("https://")

    def test_description_mentions_recall_and_retain(self, manifest: dict) -> None:
        desc = manifest["tools"]["mcp_servers"][0]["description"]
        assert "recall" in desc
        assert "retain" in desc

    def test_endpoint_path_is_mcp(self, manifest: dict) -> None:
        endpoint = manifest["tools"]["mcp_servers"][0]["endpoint"]
        assert endpoint.endswith("/mcp")


class TestMCPConfigJSON:
    def test_parses_without_error(self, mcp_config: dict) -> None:
        assert isinstance(mcp_config, dict)

    def test_has_mcp_servers_section(self, mcp_config: dict) -> None:
        assert "mcpServers" in mcp_config

    def test_contextbase_server_entry(self, mcp_config: dict) -> None:
        contextbase = mcp_config["mcpServers"]["contextbase"]
        assert "serverUrl" in contextbase
        assert "headers" in contextbase

    def test_server_url_is_https(self, mcp_config: dict) -> None:
        url = mcp_config["mcpServers"]["contextbase"]["serverUrl"]
        assert url.startswith("https://")

    def test_auth_header_present(self, mcp_config: dict) -> None:
        headers = mcp_config["mcpServers"]["contextbase"]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_no_real_credentials(self, mcp_config: dict) -> None:
        token = mcp_config["mcpServers"]["contextbase"]["headers"]["Authorization"]
        assert "YOUR_CONTEXTBASE_API_KEY" in token


class TestReadme:
    def test_readme_exists(self) -> None:
        readme = INTEGRATION_DIR / "README.md"
        assert readme.exists()

    def test_readme_mentions_cloud(self) -> None:
        content = (INTEGRATION_DIR / "README.md").read_text()
        assert "ContextBase remote service" in content
        assert "ContextBase source" in content

    def test_readme_mentions_both_config_files(self) -> None:
        content = (INTEGRATION_DIR / "README.md").read_text()
        assert "manifest.example.yaml" in content
        assert "mcp_config.example.json" in content
