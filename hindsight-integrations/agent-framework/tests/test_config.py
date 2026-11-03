"""Client resolution: cloud default + env/config overrides."""

from unittest.mock import MagicMock, patch

import pytest
from contextbase_agent_framework._client import resolve_client
from contextbase_agent_framework.config import (
    DEFAULT_CONTEXTBASE_API_URL,
    configure,
    reset_config,
)


def test_resolve_requires_explicit_endpoint_when_nothing_supplied(monkeypatch):
    """A missing URL must fail before the SDK can select an endpoint."""
    with pytest.raises(Exception, match="API URL|URL configured"):
        resolve_client(None, None, None)


def test_resolve_honors_env_key(monkeypatch):
    monkeypatch.setenv("CONTEXTBASE_API_KEY", "env-key")
    reset_config()
    with patch("contextbase_agent_framework._client.ContextBase") as mock_cls:
        mock_cls.return_value = MagicMock()
        resolve_client(None, "http://localhost:8888", None)
        assert mock_cls.call_args.kwargs["api_key"] == "env-key"
    reset_config()


def test_resolve_uses_configured_url(monkeypatch):
    monkeypatch.delenv("CONTEXTBASE_API_KEY", raising=False)
    configure(contextbase_api_url="http://localhost:8888", api_key="cfg-key")
    with patch("contextbase_agent_framework._client.ContextBase") as mock_cls:
        mock_cls.return_value = MagicMock()
        resolve_client(None, None, None)
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://localhost:8888"
        assert kwargs["api_key"] == "cfg-key"
    reset_config()


def test_explicit_args_win(monkeypatch):
    configure(contextbase_api_url="http://configured", api_key="cfg")
    with patch("contextbase_agent_framework._client.ContextBase") as mock_cls:
        mock_cls.return_value = MagicMock()
        resolve_client(None, "http://explicit", "explicit-key")
        kwargs = mock_cls.call_args.kwargs
        assert kwargs["base_url"] == "http://explicit"
        assert kwargs["api_key"] == "explicit-key"
    reset_config()
