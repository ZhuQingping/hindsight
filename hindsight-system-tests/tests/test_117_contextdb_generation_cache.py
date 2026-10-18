"""A reused readable address never reuses the old Worker's mission/config.

Exercise real API/Worker processes through the published SDK. A long native
cache TTL makes the assertion independent of how quickly provisioning runs.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from types import SimpleNamespace

import httpx
import pytest
from hindsight_client import Hindsight

from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact

from .test_100_contextdb_service import ContextDBDeployment, contextdb_deployment
from .test_110_contextdb_tenant_admin import operation_done


@pytest.fixture(params=["embedded-worker", "standalone-worker"])
def cache_deployment(request, stub_server, tmp_path_factory) -> Iterator[ContextDBDeployment]:
    config = SimpleNamespace(param=request.param, contextdb_bank_info_ttl=3600)
    owner = contextdb_deployment.__wrapped__(config, stub_server, tmp_path_factory)
    try:
        yield next(owner)
    finally:
        owner.close()


@pytest.mark.asyncio
async def test_same_name_recreation_drops_process_local_old_generation_config(cache_deployment, llm):
    base = cache_deployment.server.url
    bank = "cache_" + secrets.token_hex(5)
    marker = "OldGenerationMission_" + secrets.token_hex(5)
    sdk = Hindsight(base_url=base, api_key=cache_deployment.headers["Authorization"].removeprefix("Bearer "))
    llm.on_step("extract_facts", contains="AlphaCacheGeneration").returns(
        extracted(fact("Alice builds AlphaCacheGeneration", who="Alice", entities=["Alice", "AlphaCacheGeneration"]))
    )
    llm.on_step("extract_facts", contains="BetaCacheGeneration").returns(
        extracted(fact("Bob builds BetaCacheGeneration", who="Bob", entities=["Bob", "BetaCacheGeneration"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=cache_deployment.headers, timeout=100
    ) as management:

        async def create():
            response = await management.post(
                "/workspaces", json={"name": bank}, headers={"Idempotency-Key": secrets.token_hex(12)}
            )
            assert response.status_code == 202, response.text
            await operation_done(management, response.json())
            return response.json()["workspace_id"]

        async def delete():
            snapshot = await management.get("/workspaces/" + bank)
            response = await management.delete(
                "/workspaces/" + bank,
                headers={"Idempotency-Key": secrets.token_hex(12), "If-Match": snapshot.headers["etag"]},
            )
            assert response.status_code == 202, response.text
            await operation_done(management, response.json())

        try:
            original = await create()
            await sdk.banks.update_bank_config(bank, {"updates": {"retain_mission": marker}})
            await sdk.aretain(bank_id=bank, content="Alice builds AlphaCacheGeneration.", retain_async=True)
            await wait_until_settled(sdk, bank)
            old_calls = [call for call in llm.calls if "AlphaCacheGeneration." in call.all_text]
            assert old_calls and any(marker in call.all_text for call in old_calls)
            await delete()
            replacement = await create()
            assert replacement != original
            start = len(llm.calls)
            await sdk.aretain(bank_id=bank, content="Bob builds BetaCacheGeneration.", retain_async=True)
            await wait_until_settled(sdk, bank)
            new_calls = [call for call in llm.calls[start:] if "BetaCacheGeneration." in call.all_text]
            assert new_calls and all(marker not in call.all_text for call in new_calls)
            assert (await sdk.banks.get_bank_config(bank)).overrides == {}
            await delete()
        finally:
            await sdk.aclose()
