"""Valid asyncpg URI query passwords must not appear in API or Worker logs."""

import pytest

from hindsight_api.utils import mask_network_location


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://operator:log-password-sentinel@127.0.0.1:5432/memory",
        "postgresql://operator@127.0.0.1:5432/memory?password=log-password-sentinel",
        "postgresql://127.0.0.1:5432/memory?password=log-password-sentinel&sslmode=require",
        "postgresql://operator:other@127.0.0.1:5432/memory?password=log-password-sentinel#fragment-sentinel",
    ],
)
def test_log_redaction_drops_uri_credentials_and_preserves_target(url):
    masked = mask_network_location(url)
    assert "log-password-sentinel" not in masked
    assert "fragment-sentinel" not in masked
    assert "127.0.0.1:5432/memory" in masked
    assert "?" not in masked and "#" not in masked
    assert "password=" in url or "log-password-sentinel@" in url
