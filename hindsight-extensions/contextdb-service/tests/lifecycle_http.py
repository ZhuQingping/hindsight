"""Prepare a real Bank, then read its identity from the read-only management view.

This is test setup through public HTTP, not a compatibility route: the PUT must
return the native profile and its original identity condition before GET runs.
Dedicated Bank/SDK stories inspect the PUT wire response directly.
"""

from __future__ import annotations

import unicodedata
from typing import Any
from urllib.parse import quote

import httpx


def bank_url(client: httpx.AsyncClient, bank_id: str, *, ui: bool = False) -> str:
    prefix = "/api/banks/" if ui else "/v1/default/banks/"
    return str(client.base_url.copy_with(path=prefix + quote(bank_id, safe=""), query=None, fragment=None))


async def create_workspace(
    client: httpx.AsyncClient, *, json: dict[str, Any], ui: bool = False, **kwargs: Any
) -> httpx.Response:
    # Arbitrary JSON is intentional: callers also exercise invalid payloads.
    bank_id = unicodedata.normalize("NFKC", json["name"]).strip().lower()
    headers = {"If-None-Match": "*", **kwargs.pop("headers", {})}
    response = await client.put(
        bank_url(client, bank_id, ui=ui), json={**json, "name": bank_id}, headers=headers, **kwargs
    )
    if response.status_code != 200:
        return response
    assert response.json()["bank_id"] == bank_id
    condition = response.headers["X-ContextDB-Workspace-ETag"]
    prefix = "/api/contextdb" if ui else "/ext/contextdb/v1"
    target = client.base_url.copy_with(path=f"{prefix}/workspaces/{bank_id}", query=None, fragment=None)
    detail = await client.get(
        str(target),
        headers=kwargs.get("headers", {})
        or {key: value for key, value in headers.items() if key.lower() == "authorization"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.headers["etag"] == condition
    return detail
