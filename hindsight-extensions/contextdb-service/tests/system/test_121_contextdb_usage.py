"""Usage belongs to final external hits, not reads or internal refresh searches.

Both real Worker variants use fixture-owned PG/API processes. Business operations
go through the published SDK/MCP clients; HTTP is used only for the extension's
management contract, which the native SDK intentionally does not expose.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

import httpx
import pytest
from contextbase_client import ContextBase
from contextbase_client_api.exceptions import ForbiddenException
from contextbase_client_api.models.create_knowledge_page_response import CreateKnowledgePageResponse
from contextbase_client_api.models.reflect_fact import ReflectFact
from contextbase_client_api.models.update_memory_request import UpdateMemoryRequest
from fastmcp import Client
from hindsight_system_tests import LLMStub, reflect_loop, wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact
from pydantic import BaseModel, Field

from ..lifecycle_http import bank_url, create_workspace
from .support.clients import MemberClients, workspace_condition_headers
from .support.deployment import ContextDBDeployment
from .support.knowledge import ANSWER, create_nonempty_page

pytestmark = pytest.mark.asyncio

UsageKind = Literal["memory", "knowledge_page"]


class UsageItem(BaseModel):
    object_id: str
    recall_count: int
    last_recalled_at: datetime | None


class UsageReport(BaseModel):
    bank_id: str
    object_type: UsageKind
    items: list[UsageItem]


class ObservationToolResult(BaseModel):
    observations: list[ReflectFact] = Field(default_factory=list)


def _assert_refresh_recalled(llm: LLMStub, since: int, expected_texts: set[str]) -> None:
    # Reflect shortens UUIDs to aliases in model prompts. Match the unique text
    # in actual tool results, not UUIDs or text already present in the old page.
    shown = {
        item.text
        for call in llm.calls[since:]
        for message in call.messages
        if message.get("role") == "tool"
        for item in ObservationToolResult.model_validate_json(message["content"]).observations
    }
    assert expected_texts & shown


@pytest.fixture
async def usage_page(contextdb_clients: MemberClients, llm: LLMStub) -> CreateKnowledgePageResponse:
    # Register first: refresh must search for existing evidence, not an unrelated
    # stub query that could return no hits and make a zero-count assertion vacuous.
    reflect_loop(llm, answer=ANSWER, query="Lighthouse")
    return await create_nonempty_page(contextdb_clients, llm)


async def _usage(management: httpx.AsyncClient, bank: str, kind: UsageKind, ids: list[str]) -> UsageReport:
    response = await management.get(
        f"/workspaces/{bank}/usage", params=[("object_type", kind), *(("ids", value) for value in ids)]
    )
    assert response.status_code == 200, response.text
    report = UsageReport.model_validate(response.json())
    assert report.bank_id == bank and report.object_type == kind
    return report


async def _wait_for_count(
    management: httpx.AsyncClient, bank: str, kind: UsageKind, object_id: str, expected: int
) -> UsageItem:
    deadline = time.monotonic() + 12
    while True:
        report = await _usage(management, bank, kind, [object_id])
        assert [item.object_id for item in report.items] == [object_id]
        item = report.items[0]
        assert item.recall_count <= expected, f"Duplicate counting: {item}"
        if item.recall_count == expected:
            assert (item.last_recalled_at is None) == (expected == 0)
            return item
        assert time.monotonic() < deadline, f"Usage did not reach {expected}: {item}"
        await asyncio.sleep(0.1)


async def _assert_unchanged(management: httpx.AsyncClient, bank: str, kind: UsageKind, before: UsageItem) -> None:
    # Observe for more than two regular flush intervals: checking immediately
    # after GET/reflect would miss an incorrectly enqueued asynchronous event.
    deadline = time.monotonic() + 2.2
    while time.monotonic() < deadline:
        current = await _usage(management, bank, kind, [before.object_id])
        assert current.items == [before]
        await asyncio.sleep(0.2)


async def _retain_memory(clients: MemberClients, llm: LLMStub) -> str:
    llm.on_step("extract_facts", contains="UsageSentinel").returns(
        extracted(fact("Alice builds UsageSentinel", who="Alice", entities=["Alice", "UsageSentinel"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    accepted = await clients.own.aretain(
        bank_id=clients.bank_id,
        content="Alice builds UsageSentinel.",
        document_id="usage-sentinel",
        retain_async=True,
    )
    assert accepted.operation_id
    await wait_until_settled(clients.own, clients.bank_id)
    listed = await clients.own.memory.list_memories(clients.bank_id, document_id="usage-sentinel", limit=100)
    assert len(listed.items) == 1
    return listed.items[0].id


async def test_final_memory_hits_count_once_over_rest_and_both_mcp_modes(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    object_id = await _retain_memory(clients, llm)
    before_write = await clients.own.memory.list_memories(clients.bank_id, document_id="usage-sentinel", limit=100)
    assert before_write.items[0].updated_at is not None
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=20
    ) as management:
        zero = await _wait_for_count(management, clients.bank_id, "memory", object_id, 0)
        assert zero.last_recalled_at is None
        start = datetime.now(timezone.utc)
        result = await clients.own.arecall(bank_id=clients.bank_id, query="UsageSentinel", include_chunks=True)
        assert [item.id for item in result.results] == [object_id]
        first = await _wait_for_count(management, clients.bank_id, "memory", object_id, 1)
        assert first.last_recalled_at is not None and first.last_recalled_at >= start
        result = await clients.read_only.arecall(bank_id=clients.bank_id, query="UsageSentinel")
        assert [item.id for item in result.results] == [object_id]
        second = await _wait_for_count(management, clients.bank_id, "memory", object_id, 2)
        assert second.last_recalled_at is not None and second.last_recalled_at >= first.last_recalled_at
        async with Client(f"{deployment.server.url}/mcp/{clients.bank_id}/", auth=clients.own_key) as mcp:
            hit = await mcp.call_tool("recall", {"query": "UsageSentinel"})
            assert not hit.is_error
        await _wait_for_count(management, clients.bank_id, "memory", object_id, 3)
        async with Client(f"{deployment.server.url}/mcp/", auth=clients.read_only_key) as mcp:
            hit = await mcp.call_tool("recall", {"bank_id": clients.bank_id, "query": "UsageSentinel"})
            assert not hit.is_error
        await _wait_for_count(management, clients.bank_id, "memory", object_id, 4)
        admin = ContextBase(
            base_url=deployment.server.url,
            api_key=deployment.headers["Authorization"].removeprefix("Bearer "),
        )
        try:
            assert [
                item.id for item in (await admin.arecall(bank_id=clients.bank_id, query="UsageSentinel")).results
            ] == [object_id]
        finally:
            await admin.aclose()
        counted = await _wait_for_count(management, clients.bank_id, "memory", object_id, 5)
        # Returning the same memory in chunks/source references must not double
        # count, and aggregation must not stamp its content update watermark.
        after_write = await clients.own.memory.list_memories(clients.bank_id, document_id="usage-sentinel", limit=100)
        assert before_write.items[0].updated_at == after_write.items[0].updated_at
        await clients.own.memory.get_memory(clients.bank_id, object_id)
        await clients.own.memory.list_memories(clients.bank_id, limit=100)
        reflect_loop(llm, answer="Alice builds UsageSentinel.", query="UsageSentinel")
        reflected = await clients.read_only.areflect(
            bank_id=clients.bank_id, query="What does Alice build?", include_facts=True
        )
        assert reflected.text == "Alice builds UsageSentinel."
        assert reflected.based_on is not None and reflected.based_on.memories
        assert object_id in {item.id for item in reflected.based_on.memories}
        await _assert_unchanged(management, clients.bank_id, "memory", counted)


async def test_usage_follows_content_read_permissions_and_reads_do_not_count(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    object_id = await _retain_memory(clients, llm)
    path = f"/workspaces/{clients.bank_id}/usage"
    params = {"object_type": "memory", "ids": object_id}
    async with (
        httpx.AsyncClient(base_url=deployment.server.url + "/ext/contextdb/v1", timeout=20) as request,
        httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=20
        ) as management,
    ):
        assert (await request.get(path, params=params)).status_code == 401
        for key in (clients.own_key, clients.read_only_key):
            allowed = await request.get(path, params=params, headers={"Authorization": "Bearer " + key})
            assert allowed.status_code == 200
            assert allowed.json()["items"][0]["recall_count"] == 0
        denied = await request.get(path, params=params, headers={"Authorization": "Bearer " + clients.other_key})
        assert denied.status_code == 403
        with pytest.raises(ForbiddenException):
            await clients.other_bank.arecall(bank_id=clients.bank_id, query="UsageSentinel")
        assert (await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="UsageSentinel")).results == []
        assert (await _usage(management, clients.other_bank_id, "memory", [object_id])).items == []
        before = await _wait_for_count(management, clients.bank_id, "memory", object_id, 0)
        invalid = ContextBase(base_url=deployment.server.url, api_key="invalid-usage-story-key")
        try:
            from contextbase_client_api.exceptions import UnauthorizedException

            with pytest.raises(UnauthorizedException):
                await invalid.arecall(bank_id=clients.bank_id, query="UsageSentinel")
        finally:
            await invalid.aclose()
        await _assert_unchanged(management, clients.bank_id, "memory", before)
        repeated = await _usage(management, clients.bank_id, "memory", [object_id, object_id])
        assert repeated.items == [before]
        oversized = await management.get(
            path,
            params=[("object_type", "memory"), *(("ids", str(uuid4())) for _ in range(101))],
        )
        assert oversized.status_code in {400, 422}, oversized.text


async def test_knowledge_search_counts_pages_but_reads_and_refreshes_do_not(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    usage_page: CreateKnowledgePageResponse,
    llm: LLMStub,
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    page_id = usage_page.page_id
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=20
    ) as management:
        await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 0)
        evidence = await clients.own.memory.list_memories(clients.bank_id, limit=100)
        assert evidence.items
        for item in (await _usage(management, clients.bank_id, "memory", [item.id for item in evidence.items])).items:
            assert item.recall_count == 0 and item.last_recalled_at is None
        memory_before: list[UsageItem] = []
        observation_texts: set[str] = set()
        for kind in ["world", "observation"]:
            recalled = await clients.read_only.arecall(bank_id=clients.bank_id, query="Lighthouse", types=[kind])
            assert recalled.results
            memory_before.extend(
                [await _wait_for_count(management, clients.bank_id, "memory", item.id, 1) for item in recalled.results]
            )
            if kind == "observation":
                observation_texts.update(item.text for item in recalled.results)
        matches = await clients.knowledge_reader.asearch_knowledge_base(clients.bank_id, "Lighthouse")
        assert [item.id for item in matches.results] == [page_id]
        await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 1)
        async with Client(f"{deployment.server.url}/mcp/{clients.bank_id}/", auth=clients.knowledge_reader_key) as mcp:
            result = await mcp.call_tool("search_knowledge_base", {"query": "Lighthouse"})
            assert not result.is_error
            fetched = await mcp.call_tool("get_knowledge_page", {"page_id": page_id})
            assert not fetched.is_error
        await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 2)
        async with Client(f"{deployment.server.url}/mcp/", auth=clients.knowledge_reader_key) as mcp:
            result = await mcp.call_tool("search_knowledge_base", {"bank_id": clients.bank_id, "query": "Lighthouse"})
            assert not result.is_error
        counted = await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 3)
        for key in (clients.own_key, clients.knowledge_reader_key):
            response = await management.get(
                f"/workspaces/{clients.bank_id}/usage",
                params={"object_type": "knowledge_page", "ids": page_id},
                headers={"Authorization": "Bearer " + key},
            )
            assert response.status_code == 200
            assert response.json()["items"][0]["recall_count"] == 3
        await clients.knowledge_reader.aget_knowledge_page(clients.bank_id, page_id)
        await clients.knowledge_reader.aget_knowledge_base_tree(clients.bank_id)
        await clients.knowledge_reader.aget_mental_model(clients.bank_id, usage_page.mental_model_id)
        model_before = await clients.own.aget_mental_model(clients.bank_id, usage_page.mental_model_id)
        previous_calls = len(llm.calls)
        await clients.own.arefresh_mental_model(clients.bank_id, usage_page.mental_model_id)
        await wait_until_settled(clients.own, clients.bank_id)
        model_after = await clients.own.aget_mental_model(clients.bank_id, usage_page.mental_model_id)
        assert model_after.last_refreshed_at != model_before.last_refreshed_at
        _assert_refresh_recalled(llm, previous_calls, observation_texts)
        await _assert_unchanged(management, clients.bank_id, "knowledge_page", counted)
        for item in memory_before:
            await _assert_unchanged(management, clients.bank_id, "memory", item)
        assert (await _usage(management, clients.bank_id, "knowledge_page", [usage_page.mental_model_id])).items == []
        await clients.own.adelete_knowledge_node(clients.bank_id, page_id)
        assert (await _usage(management, clients.bank_id, "knowledge_page", [page_id])).items == []


async def test_consolidation_and_automatic_page_refresh_preserve_existing_usage(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    usage_page: CreateKnowledgePageResponse,
    llm: LLMStub,
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=20
    ) as management:
        memory_before: list[UsageItem] = []
        observation_ids: set[str] = set()
        observation_texts: set[str] = set()
        for kind in ["world", "observation"]:
            recalled = await clients.read_only.arecall(bank_id=clients.bank_id, query="Lighthouse", types=[kind])
            assert recalled.results
            for item in recalled.results:
                memory_before.append(await _wait_for_count(management, clients.bank_id, "memory", item.id, 1))
                if kind == "observation":
                    observation_ids.add(item.id)
                    observation_texts.add(item.text)
        found = await clients.knowledge_reader.asearch_knowledge_base(clients.bank_id, "Lighthouse")
        assert [item.id for item in found.results] == [usage_page.page_id]
        page_before = await _wait_for_count(management, clients.bank_id, "knowledge_page", usage_page.page_id, 1)
        old_refreshes = {
            item.operation_id
            for item in (
                await clients.own.operations.list_operations(clients.bank_id, type="refresh_mental_model", limit=100)
            ).operations
        }
        previous_prompts = len(llm.prompts_for("consolidate"))
        previous_calls = len(llm.calls)
        llm.on_step("extract_facts", contains="Bob").returns(
            extracted(fact("Bob joins Lighthouse", who="Bob", entities=["Bob", "Lighthouse"]))
        )
        retained = await clients.own.aretain(
            bank_id=clients.bank_id, content="Bob joins Lighthouse.", document_id="bob-usage", retain_async=True
        )
        assert retained.operation_id
        await wait_until_settled(clients.own, clients.bank_id)
        # Prove consolidation actually recalled an existing observation, and its
        # resulting write scheduled and completed a real background page refresh.
        prompts = llm.prompts_for("consolidate")[previous_prompts:]
        assert any(object_id in prompt for prompt in prompts for object_id in observation_ids)
        refreshed = [
            item
            for item in (
                await clients.own.operations.list_operations(clients.bank_id, type="refresh_mental_model", limit=100)
            ).operations
            if item.operation_id not in old_refreshes
        ]
        assert refreshed and all(item.status == "completed" for item in refreshed)
        _assert_refresh_recalled(llm, previous_calls, observation_texts)
        await _assert_unchanged(management, clients.bank_id, "knowledge_page", page_before)
        for item in memory_before:
            await _assert_unchanged(management, clients.bank_id, "memory", item)


async def test_invalidating_then_restoring_same_memory_preserves_usage(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    object_id = await _retain_memory(clients, llm)
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=20
    ) as management:
        assert [
            item.id for item in (await clients.own.arecall(bank_id=clients.bank_id, query="UsageSentinel")).results
        ] == [object_id]
        counted = await _wait_for_count(management, clients.bank_id, "memory", object_id, 1)
        await clients.own.memory.update_memory(clients.bank_id, object_id, UpdateMemoryRequest(state="invalidated"))
        await wait_until_settled(clients.own, clients.bank_id)
        assert (await clients.own.arecall(bank_id=clients.bank_id, query="UsageSentinel")).results == []
        await _assert_unchanged(management, clients.bank_id, "memory", counted)
        await clients.own.memory.update_memory(clients.bank_id, object_id, UpdateMemoryRequest(state="valid"))
        await wait_until_settled(clients.own, clients.bank_id)
        assert [
            item.id
            for item in (await clients.read_only.arecall(bank_id=clients.bank_id, query="UsageSentinel")).results
        ] == [object_id]
        await _wait_for_count(management, clients.bank_id, "memory", object_id, 2)


async def test_recreated_workspace_does_not_inherit_old_usage(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    object_id = await _retain_memory(clients, llm)
    bank = clients.bank_id
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
    ) as management:
        await clients.own.arecall(bank_id=bank, query="UsageSentinel")
        await _wait_for_count(management, bank, "memory", object_id, 1)
        original = (await management.get(f"/workspaces/{bank}")).json()
        deleted = await management.delete(
            bank_url(management, bank), headers=await workspace_condition_headers(management, f"/workspaces/{bank}")
        )
        assert deleted.status_code == 200, deleted.text
        assert (
            await management.get(f"/workspaces/{bank}/usage", params={"object_type": "memory", "ids": object_id})
        ).status_code == 403
        replacement = await create_workspace(management, json={"name": bank})
        assert replacement.status_code == 200, replacement.text
        assert replacement.json()["workspace_id"] != original["workspace_id"]
        replaced = await _usage(management, bank, "memory", [object_id])
        assert replaced.items == []
        with pytest.raises(ForbiddenException):
            await clients.own.arecall(bank_id=bank, query="UsageSentinel")
        admin = ContextBase(
            base_url=deployment.server.url,
            api_key=deployment.headers["Authorization"].removeprefix("Bearer "),
        )
        try:
            assert (await admin.arecall(bank_id=bank, query="UsageSentinel")).results == []
        finally:
            await admin.aclose()
        assert (await _usage(management, bank, "memory", [object_id])).items == []
