"""Periodic native maintenance recovers real work with no public business tables."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest
from contextbase_client import ContextBase
from hindsight_system_tests import LLMStub, reflect_loop, wait_until_settled
from hindsight_system_tests.payloads import extracted, fact, observes
from hindsight_system_tests.server import StubServer

from .support.clients import clients_owner
from .support.deployment import ContextDBDeployment, DeploymentOptions, deployment_owner

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="session", params=["embedded-worker", "standalone-worker"])
def maintenance_deployment(
    request: pytest.FixtureRequest, stub_server: StubServer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[ContextDBDeployment]:
    with deployment_owner(
        DeploymentOptions(worker_mode=request.param, maintenance_probe=True),
        stub_server.url,
        tmp_path_factory.mktemp("contextdb-maintenance"),
    ) as deployment:
        yield deployment


async def test_reconcile_and_cron_refresh_execute_on_native_ticker(
    maintenance_deployment: ContextDBDeployment, llm: LLMStub
) -> None:
    deployment = maintenance_deployment
    admin = ContextBase(
        base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
    )
    answer = "Alice builds MaintenanceSentinel."
    llm.on_step("extract_facts", contains="continues").returns(
        extracted(fact("Alice improves MaintenanceSentinel", who="Alice", entities=["Alice", "MaintenanceSentinel"]))
    )
    llm.on_step("extract_facts", contains="MaintenanceSentinel").returns(
        extracted(fact("Alice builds MaintenanceSentinel", who="Alice", entities=["Alice", "MaintenanceSentinel"]))
    )
    llm.on_step("consolidate").answers_with(observes(answer))
    reflect_loop(llm, answer=answer)
    try:
        async with clients_owner(deployment) as clients:
            bank = clients.bank_id
            # Public fault setup creates eligible-but-unscheduled facts; the
            # test then ENABLES auto consolidation and waits for actual execution.
            await admin.aupdate_bank_config(bank, enable_auto_consolidation=False)
            retained = await clients.own.aretain(bank_id=bank, content=answer, retain_async=True)
            assert retained.operation_id
            await wait_until_settled(clients.own, bank)
            assert not [
                m
                for m in (await clients.own.memory.list_memories(bank, limit=100)).items
                if m.fact_type == "observation"
            ]
            await admin.aupdate_bank_config(bank, enable_auto_consolidation=True)
            model = await clients.own.mental_models.create_mental_model(
                bank,
                {
                    "name": "Maintenance probe",
                    "source_query": "What does Alice build?",
                    "trigger": {"refresh_cron": "* * * * *", "refresh_after_consolidation": False},
                },
            )
            await wait_until_settled(clients.own, bank)
            initial = await clients.own.mental_models.get_mental_model(bank, model.mental_model_id, detail="full")
            # A second real write makes a freshly initialized model stale; no
            # manual consolidation/refresh endpoint is used after this point.
            await admin.aupdate_bank_config(bank, enable_auto_consolidation=False)
            await clients.own.aretain(bank_id=bank, content=answer + " She continues today.", retain_async=True)
            await wait_until_settled(clients.own, bank)
            await admin.aupdate_bank_config(bank, enable_auto_consolidation=True)
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                memories = (await clients.own.memory.list_memories(bank, limit=100)).items
                current = await clients.own.mental_models.get_mental_model(bank, model.mental_model_id, detail="full")
                if (
                    any(m.fact_type == "observation" for m in memories)
                    and current.last_refreshed_at != initial.last_refreshed_at
                    and not current.is_stale
                ):
                    break
                await asyncio.sleep(0.5)
            else:
                pytest.fail("Native periodic reconcile/cron did not complete within 150 seconds")
            assert current.content.strip() == answer
            # Remove the schedule before model stub rules reset, after accepted
            # work has completed. This does not stop any production service.
            await clients.own.mental_models.update_mental_model(
                bank, model.mental_model_id, {"trigger": {"refresh_cron": None, "refresh_after_consolidation": False}}
            )
            await wait_until_settled(clients.own, bank)
            for process in [deployment.server, deployment.worker]:
                if process is not None:
                    logs = process.logs()
                    assert "Consolidation reconcile discovery failed" not in logs
                    assert "Scheduled mental model refresh discovery failed" not in logs
    finally:
        await admin.aclose()
