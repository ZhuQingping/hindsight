"""Unit tests for ContextBase-Superagent client resolution."""

from __future__ import annotations
import pytest

from unittest.mock import MagicMock, patch


from contextbase_superagent import configure, reset_config
from contextbase_superagent._client import resolve_hindsight_client


class TestResolveContextBaseClient:
    def setup_method(self) -> None:
        reset_config()

    def teardown_method(self) -> None:
        reset_config()

    def test_returns_explicit_client(self) -> None:
        client = MagicMock()
        result = resolve_hindsight_client(client, None, None)
        assert result is client

    def test_creates_client_from_args(self) -> None:
        with patch("contextbase_superagent._client.Hindsight") as mock_cls:
            mock_cls.return_value = MagicMock()
            resolve_hindsight_client(None, "http://localhost:8888", "test-key")
            mock_cls.assert_called_once()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://localhost:8888"
            assert call_kwargs["api_key"] == "test-key"
            assert "contextbase-superagent" in call_kwargs["user_agent"]

    def test_creates_client_from_global_config(self) -> None:
        configure(contextbase_api_url="http://config:8888", api_key="config-key")
        with patch("contextbase_superagent._client.Hindsight") as mock_cls:
            mock_cls.return_value = MagicMock()
            resolve_hindsight_client(None, None, None)
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://config:8888"
            assert call_kwargs["api_key"] == "config-key"

    def test_creates_client_without_api_key(self) -> None:
        with patch("contextbase_superagent._client.Hindsight") as mock_cls:
            mock_cls.return_value = MagicMock()
            resolve_hindsight_client(None, "http://localhost:8888", None)
            call_kwargs = mock_cls.call_args.kwargs
            assert "api_key" not in call_kwargs

    def test_requires_explicit_endpoint_url(self) -> None:
        """A missing URL must fail before the SDK can select an endpoint."""
        with pytest.raises(Exception, match="API URL|URL configured"):
            resolve_hindsight_client(None, None, None)

    def test_explicit_args_override_config(self) -> None:
        configure(contextbase_api_url="http://config:8888", api_key="config-key")
        with patch("contextbase_superagent._client.Hindsight") as mock_cls:
            mock_cls.return_value = MagicMock()
            resolve_hindsight_client(None, "http://explicit:9999", "explicit-key")
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["base_url"] == "http://explicit:9999"
            assert call_kwargs["api_key"] == "explicit-key"
