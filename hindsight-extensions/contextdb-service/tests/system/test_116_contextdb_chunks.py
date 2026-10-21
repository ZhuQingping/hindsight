"""Retain/recall succeeds only when the published chunk-read path works too."""

from __future__ import annotations

import secrets

import httpx
import pytest
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException, NotFoundException, UnauthorizedException
from hindsight_system_tests.payloads import consolidation, extracted, fact
from hindsight_system_tests.waiting import wait_until_settled

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("document", ["doc_part_~_1", "path/中文%20_part_~_1"])
async def test_native_chunks_read_back_with_member_read_only_and_admin_keys(
    contextdb_clients: MemberClients,
    contextdb_deployment: ContextDBDeployment,
    llm,
    document: str,
) -> None:
    clients = contextdb_clients
    text = "Alice builds Lighthouse."
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    accepted = await clients.own.aretain(
        bank_id=clients.bank_id,
        content=text,
        document_id=document,
        retain_async=True,
    )
    assert accepted.operation_id
    await wait_until_settled(clients.own, clients.bank_id)
    recalled = await clients.own.arecall(bank_id=clients.bank_id, query="Lighthouse", include_chunks=True)
    assert [item.document_id for item in recalled.results] == [document]
    listed = await clients.own.documents.list_document_chunks(clients.bank_id, document)
    assert len(listed.items) == 1
    expected = listed.items[0]
    assert expected.bank_id == clients.bank_id and expected.document_id == document
    assert recalled.chunks is not None
    assert set(recalled.chunks) == {expected.chunk_id}
    assert recalled.chunks[expected.chunk_id].text == text
    assert expected.chunk_text == text
    assert "~5F" in expected.chunk_id and "~7E" in expected.chunk_id
    admin = Hindsight(
        base_url=contextdb_deployment.server.url,
        api_key=contextdb_deployment.headers["Authorization"].removeprefix("Bearer "),
    )
    invalid = Hindsight(base_url=contextdb_deployment.server.url, api_key="invalid-test-key")
    try:
        async with httpx.AsyncClient(base_url=contextdb_deployment.server.url) as anonymous:
            assert (await anonymous.get("/v1/default/chunks/" + expected.chunk_id)).status_code == 401
        for client in [clients.own, clients.read_only, admin]:
            chunk = await client.documents.get_chunk(expected.chunk_id)
            assert chunk.model_dump() == expected.model_dump()
        with pytest.raises(ForbiddenException):
            await clients.other_bank.documents.get_chunk(expected.chunk_id)
        with pytest.raises(UnauthorizedException):
            await invalid.documents.get_chunk(expected.chunk_id)
        with pytest.raises(ForbiddenException):
            await clients.read_only.aretain(bank_id=clients.bank_id, content="Not authorized")
        missing = expected.chunk_id.rsplit("_", 1)[0] + "_999999"
        with pytest.raises(NotFoundException):
            await clients.own.documents.get_chunk(missing)
        async with httpx.AsyncClient(
            base_url=contextdb_deployment.server.url + "/ext/contextdb/v1",
            headers=contextdb_deployment.headers,
            timeout=100,
        ) as management:
            response = await management.post("/users", json={"name": "Chunk revocation " + secrets.token_hex(5)})
            assert response.status_code == 201
            user_id = response.json()["user_id"]
            response = await management.post(
                f"/users/{user_id}/keys",
                json={
                    "name": "Temporary reader",
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [{"bank_id": clients.bank_id, "permission": "read"}],
                    },
                },
            )
            assert response.status_code == 201
            issued = response.json()
            revoked = Hindsight(base_url=contextdb_deployment.server.url, api_key=issued["secret"])
            try:
                assert (await revoked.documents.get_chunk(expected.chunk_id)).chunk_text == text
                response = await management.delete(f"/users/{user_id}/keys/{issued['key_id']}")
                assert response.status_code == 204
                with pytest.raises(UnauthorizedException):
                    await revoked.documents.get_chunk(expected.chunk_id)
            finally:
                await revoked.aclose()
        # A denied call must not contaminate the next request's workspace context.
        assert (await admin.documents.get_chunk(expected.chunk_id)).chunk_text == text
    finally:
        await admin.aclose()
        await invalid.aclose()
