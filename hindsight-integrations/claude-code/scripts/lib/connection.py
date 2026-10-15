"""Explicit remote connection for the customer plugin; never starts a local engine."""

from .client import _validate_api_url


def get_api_url(api_url: str | None) -> str:
    """Resolve the user's API Endpoint without network or process side effects."""
    if not api_url or not api_url.strip():
        raise RuntimeError(
            "API Endpoint is required. Copy it from your console and set "
            "AGENTSTRATUM_API_URL or apiUrl in ~/.agentstratum/claude-code.json."
        )
    return _validate_api_url(api_url.strip())
