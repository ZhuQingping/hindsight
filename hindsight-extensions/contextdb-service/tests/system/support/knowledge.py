"""Prepare a real page through the published SDK and model stub rules."""

from __future__ import annotations

from hindsight_client_api.models.create_knowledge_page_response import (
    CreateKnowledgePageResponse,
)
from hindsight_system_tests import LLMStub, reflect_loop, wait_until_settled
from hindsight_system_tests.payloads import extracted, fact, observes

from .clients import MemberClients

ANSWER = "Alice builds Lighthouse."


async def create_nonempty_page(contextdb_clients: MemberClients, llm: LLMStub) -> CreateKnowledgePageResponse:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains=ANSWER).returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    # Specific later observation first: returning Alice's unchanged observation
    # for Bob is deduplicated by core and legitimately schedules no refresh.
    llm.on_step("consolidate", contains="Bob joins Lighthouse").answers_with(observes("Bob joins Lighthouse"))
    llm.on_step("consolidate").answers_with(observes("Alice builds Lighthouse"))
    reflect_loop(llm, answer=ANSWER)
    retained = await clients.own.aretain(
        bank_id=clients.bank_id, content=ANSWER, retain_async=True, document_id="lighthouse"
    )
    assert retained.operation_id is not None
    await wait_until_settled(clients.own, clients.bank_id)
    created = await clients.own.acreate_knowledge_page(
        clients.bank_id, name="Lighthouse team", source_query="What does Alice build?", trigger={"mode": "full"}
    )
    await wait_until_settled(clients.own, clients.bank_id)
    operation = await clients.own.operations.get_operation_status(clients.bank_id, created.operation_id)
    assert operation.status == "completed"
    return created
