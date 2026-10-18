"""Provisioning a server-owned model must not deadlock its creating workspace."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from hindsight_system_tests import reflect_loop, wait_until_settled

from .support.clients import clients_owner
from .support.deployment import ContextDBDeployment, DeploymentOptions, deployment_owner

pytestmark = pytest.mark.asyncio

TEMPLATE = {
    "version": "1",
    "mental_models": [
        {"id": "default-environment", "name": "Environment", "source_query": "Describe the environment."}
    ],
}
ANSWER = "This workspace has a server-owned environment model."


@pytest.fixture(params=["embedded-worker", "standalone-worker"])
def template_deployment(request, stub_server, tmp_path_factory, llm) -> Iterator[ContextDBDeployment]:
    reflect_loop(llm, answer=ANSWER)
    # Reuse the same unique-PG fixture owner; only this test's server receives
    # the optional template. It does not change a global/dev deployment setting.
    options = DeploymentOptions(worker_mode=request.param, default_template=json.dumps(TEMPLATE))
    with deployment_owner(options, stub_server.url, tmp_path_factory.mktemp("contextdb-template")) as deployment:
        yield deployment


async def test_default_template_refresh_works_after_synchronous_workspace_creation(template_deployment) -> None:
    async with clients_owner(template_deployment) as clients:
        for client, bank in ((clients.own, clients.bank_id), (clients.other_bank, clients.other_bank_id)):
            await wait_until_settled(client, bank)
            operations = await client.operations.list_operations(bank, limit=100)
            refreshes = [op for op in operations.operations if op.task_type == "refresh_mental_model"]
            assert refreshes and all(op.status == "completed" for op in refreshes)
            model = await client.aget_mental_model(bank, "default-environment")
            assert model.name == "Environment"
            assert model.source_query == "Describe the environment."
            # Native Hindsight deliberately skips the LLM for an empty Bank.
            # A completed real refresh operation, not invented content, proves
            # the initialization queue and subsequent Worker handoff worked.
            assert model.content == ""
