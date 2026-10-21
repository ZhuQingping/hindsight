"""Native appends complete before the administrator deletes an idle workspace."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


async def test_concurrent_appends_complete_before_administrator_deletes_workspace(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm
) -> None:
    client, bank = contextdb_clients.own, contextdb_clients.bank_id
    llm.on_step("extract_facts").returns(extracted())
    llm.on_step("consolidate").returns(consolidation())
    document_id = "session-burst"
    first = "Alice opened the session."
    queued = [f"Queued turn {i}." for i in range(6)]
    synchronous = [f"Sync turn {i}." for i in range(12)]
    await client.aretain(bank_id=bank, content=first, document_id=document_id)
    await wait_until_settled(client, bank)

    async def append(turn: str, asynchronous: bool):
        return await client.aretain(
            bank_id=bank,
            content=turn,
            document_id=document_id,
            update_mode="append",
            retain_async=asynchronous,
        )

    outcomes = await asyncio.gather(
        *(append(turn, True) for turn in queued),
        *(append(turn, False) for turn in synchronous),
        return_exceptions=True,
    )
    await wait_until_settled(client, bank)
    for response in outcomes[: len(queued)]:
        assert not isinstance(response, BaseException), response
        status = await client.operations.get_operation_status(bank, response.operation_id)
        assert status.status == "completed", status
    document = await client.documents.get_document(bank, document_id)
    expected = [
        first,
        *queued,
        *[turn for turn, result in zip(synchronous, outcomes[len(queued) :]) if not isinstance(result, BaseException)],
    ]
    assert sorted((document.original_text or "").split("\n")) == sorted(expected)

    # Stop issuing writes and wait for native tasks before management deletion.
    # The extension intentionally provides no global request-drain guarantee.
    async with httpx.AsyncClient(
        base_url=contextdb_deployment.server.url + "/ext/contextdb/v1",
        headers=contextdb_deployment.headers,
        timeout=30,
    ) as management:
        snapshot = await management.get("/workspaces/" + bank)
        assert snapshot.status_code == 200
        deletion = await management.delete(
            "/workspaces/" + bank,
            headers={"If-Match": snapshot.headers["etag"]},
        )
        assert deletion.status_code == 204, deletion.text

        assert (await management.get("/workspaces/" + bank)).status_code == 404
