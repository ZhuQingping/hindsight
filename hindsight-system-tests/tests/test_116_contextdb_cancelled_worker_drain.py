"""A cooperative native cancellation cannot release the old schema generation."""

from __future__ import annotations

import asyncio
import secrets

import httpx
import pytest
from hindsight_client import Hindsight

from hindsight_system_tests.payloads import consolidation, extracted, fact

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import ContextDBDeployment, MemberClients
from .test_110_contextdb_tenant_admin import operation_done

contextdb_deployment = service_story.contextdb_deployment
contextdb_clients = service_story.contextdb_clients
pytestmark = pytest.mark.asyncio


async def test_cancelled_running_retain_still_blocks_delete_and_name_reuse(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    bank = clients.bank_id
    llm.on_step("extract_facts", contains="CancelledGenerationSentinel").returns(
        extracted(fact("Alice builds CancelledGenerationSentinel", who="Alice"))
    )
    llm.on_step("consolidate").returns(consolidation())
    async with httpx.AsyncClient(base_url=deployment.server.url, headers=deployment.headers, timeout=30) as raw:
        path = "/ext/contextdb/v1/workspaces/" + bank
        snapshot = await raw.get(path)
        old_uuid = snapshot.json()["workspace_id"]
        async with llm.hold("extract_facts") as held:
            accepted = await clients.own.aretain(
                bank_id=bank, content="Alice builds CancelledGenerationSentinel.", retain_async=True
            )
            assert accepted.operation_id is not None
            await held.reached()
            # Cancel every processing child as well as its parent: the native
            # terminal-row count alone now cannot prove any executor has left.
            listing = await raw.get(
                f"/v1/default/banks/{bank}/operations", params={"status": "processing", "limit": 100}
            )
            assert listing.status_code == 200, listing.text
            processing = listing.json()["operations"]
            assert processing
            for operation in processing:
                cancelled = await raw.delete(f"/v1/default/banks/{bank}/operations/{operation['operation_id']}")
                assert cancelled.status_code == 200, cancelled.text
            deletion = await raw.delete(
                path,
                headers={"Idempotency-Key": secrets.token_hex(12), "If-Match": snapshot.headers["etag"]},
            )
            assert deletion.status_code == 202, deletion.text
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                progress = await raw.get("/ext/contextdb/v1/operations/" + deletion.json()["operation_id"])
                value = progress.json()
                assert value["state"] not in {"succeeded", "failed"}, value
                if value["error_code"] == "waiting_for_admissions":
                    break
                assert asyncio.get_running_loop().time() < deadline, value
                await asyncio.sleep(0.1)
            occupied = await raw.post(
                "/ext/contextdb/v1/workspaces",
                json={"name": bank},
                headers={"Idempotency-Key": secrets.token_hex(12)},
            )
            assert occupied.status_code == 409, occupied.text
            assert (await raw.get(path)).json()["workspace_id"] == old_uuid
            held.release()
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=30
        ) as management:
            await operation_done(management, deletion.json())
            replacement = await management.post(
                "/workspaces", json={"name": bank}, headers={"Idempotency-Key": secrets.token_hex(12)}
            )
            assert replacement.status_code == 202, replacement.text
            await operation_done(management, replacement.json())
            new = (await management.get("/workspaces/" + bank)).json()
            assert new["workspace_id"] != old_uuid and new["bank_id"] == bank
        admin = Hindsight(
            base_url=deployment.server.url,
            api_key=deployment.headers["Authorization"].removeprefix("Bearer "),
        )
        try:
            assert (await admin.arecall(bank_id=bank, query="CancelledGenerationSentinel")).results == []
        finally:
            await admin.aclose()
