"""Mutable credentials deliberately retain an established MCP session."""

from collections.abc import Generator

import httpx


class MutableBearer(httpx.Auth):
    """Change only the credential, retaining the established MCP session ID."""

    def __init__(self, credential: str) -> None:
        self.credential = credential

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self.credential}"
        yield request
