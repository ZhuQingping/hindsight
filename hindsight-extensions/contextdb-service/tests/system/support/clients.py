"""Published-client preparation and cleanup over management HTTP."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field

import httpx
from hindsight_client import Hindsight

from .deployment import ContextDBDeployment


@dataclass
class MemberClients:
    own: Hindsight
    same_bank: Hindsight
    other_bank: Hindsight
    read_only: Hindsight
    knowledge_reader: Hindsight
    bank_id: str
    other_bank_id: str
    own_key: str = field(repr=False)
    other_key: str = field(repr=False)
    read_only_key: str = field(repr=False)
    knowledge_reader_key: str = field(repr=False)


async def workspace_condition_headers(management: httpx.AsyncClient, path: str) -> dict[str, str]:
    """Read the current object identity and version before deleting it."""
    snapshot = await management.get(path)
    assert snapshot.status_code == 200, snapshot.text
    return {"If-Match": snapshot.headers["etag"]}


@asynccontextmanager
async def clients_owner(contextdb_deployment: ContextDBDeployment) -> AsyncIterator[MemberClients]:
    base = contextdb_deployment.server.url
    async with (
        AsyncExitStack() as resources,
        httpx.AsyncClient(
            base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
        ) as management,
    ):

        async def create_workspace(name: str) -> str:
            response = await management.post(
                "/workspaces",
                json={"name": name.lower().replace(" ", "_") + "_" + secrets.token_hex(4)},
            )
            assert response.status_code == 201, response.text
            workspace = response.json()
            assert workspace["state"] == "active"
            assert "operation_id" not in workspace
            return workspace["bank_id"]

        bank_id = await create_workspace("Bank one")
        other_bank_id = await create_workspace("Bank two")

        async def member_key(bank: str, name: str, permission: str = "read_write") -> str:
            response = await management.post("/users", json={"name": name + " " + secrets.token_hex(5)})
            assert response.status_code == 201, response.text
            user_id = response.json()["user_id"]
            response = await management.post(
                f"/users/{user_id}/keys",
                json={
                    "name": "Story client",
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [{"bank_id": workspace_id, "permission": permission} for workspace_id in [bank]],
                    },
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["secret"]

        def client_for(key: str) -> Hindsight:
            client = Hindsight(base_url=base, api_key=key)
            resources.push_async_callback(client.aclose)
            return client

        own_key = await member_key(bank_id, "Alice")
        own = client_for(own_key)
        same = client_for(await member_key(bank_id, "Bob"))
        other_key = await member_key(other_bank_id, "Carol")
        other = client_for(other_key)
        read_only_key = await member_key(bank_id, "Reader", "read")
        read_only = client_for(read_only_key)
        knowledge_reader_key = await member_key(bank_id, "Knowledge reader", "read")
        knowledge_reader = client_for(knowledge_reader_key)
        yield MemberClients(
            own,
            same,
            other,
            read_only,
            knowledge_reader,
            bank_id,
            other_bank_id,
            own_key,
            other_key,
            read_only_key,
            knowledge_reader_key,
        )
