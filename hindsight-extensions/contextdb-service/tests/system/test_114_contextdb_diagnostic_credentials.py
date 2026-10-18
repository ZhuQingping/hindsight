"""Synthetic webhook diagnostics cannot disclose operator credentials to apps."""

from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass, field

import asyncpg
import httpx
import pytest
from fastmcp import Client
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio
SENTINEL = "synthetic-operator-credential-for-regression-only"


@dataclass(frozen=True)
class DiagnosticFixture:
    bank_id: str
    operation_id: str
    keys: list[str] = field(repr=False)


@pytest.fixture
async def sensitive_operation(contextdb_deployment: ContextDBDeployment) -> DiagnosticFixture:
    deployment = contextdb_deployment
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
    ) as management:
        response = await management.post(
            "/workspaces",
            json={"name": "diagnostics_" + secrets.token_hex(5)},
        )
        assert response.status_code == 201, response.text

        bank = response.json()["bank_id"]
        assert re.fullmatch(r"[a-z][a-z0-9_]{0,53}", bank)
        response = await management.post("/users", json={"name": "Diagnostic application"})
        assert response.status_code == 201, response.text
        uid = response.json()["user_id"]
        keys = []
        for permission in ("read", "read_write"):
            response = await management.post(
                f"/users/{uid}/keys",
                json={
                    "name": permission,
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [{"bank_id": bank, "permission": permission}],
                    },
                },
            )
            assert response.status_code == 201, response.text
            keys.append(response.json()["secret"])
    operation = uuid.uuid4()
    # Fixture-only SQL creates a completed external-delivery response that the
    # public API cannot seed without contacting a webhook receiver. Assertions
    # below use only SDK/MCP; no memory state is inspected or fabricated.
    connection = await asyncpg.connect(deployment.database_url)
    try:
        await connection.execute(
            f'INSERT INTO "ctxdb_ws_{bank}".async_operations '
            "(operation_id,bank_id,operation_type,status,task_payload,result_metadata,error_message) "
            "VALUES($1,$2,'webhook_delivery','completed',$3::jsonb,$4::jsonb,$5)",
            operation,
            bank,
            json.dumps(
                {
                    "type": "webhook_delivery",
                    "secret": SENTINEL,
                    "http_config": {"headers": {"Authorization": "Bearer " + SENTINEL}},
                }
            ),
            json.dumps({"last_response_body": SENTINEL}),
            SENTINEL,
        )
    finally:
        await connection.close()
    return DiagnosticFixture(bank, str(operation), keys)


async def test_native_task_credentials_are_admin_only(
    contextdb_deployment: ContextDBDeployment, sensitive_operation: DiagnosticFixture
) -> None:
    deployment = contextdb_deployment
    bank, operation = sensitive_operation.bank_id, sensitive_operation.operation_id
    administrator = Hindsight(
        base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
    )
    try:
        visible = await administrator.operations.get_operation_status(bank, operation, include_payload=True)
        assert visible.task_payload["secret"] == SENTINEL
        assert visible.result_metadata["last_response_body"] == SENTINEL
        for key in sensitive_operation.keys:
            client = Hindsight(base_url=deployment.server.url, api_key=key)
            try:
                with pytest.raises(ForbiddenException):
                    await client.operations.get_operation_status(bank, operation, include_payload=True)
                status = await client.operations.get_operation_status(bank, operation)
                assert status.status == "completed"
                assert SENTINEL not in status.model_dump_json()
                operations = await client.operations.list_operations(bank, limit=100)
                assert operation in {item.operation_id for item in operations.operations}
                assert SENTINEL not in operations.model_dump_json()
                async with Client(deployment.server.url + f"/mcp/{bank}/", auth=key) as mcp:
                    detail = await mcp.call_tool("get_operation", {"operation_id": operation})
                    assert not detail.is_error
                    assert all(SENTINEL not in block.model_dump_json() for block in detail.content)
                    assert SENTINEL not in json.dumps(detail.structured_content)
                    listed = await mcp.call_tool("list_operations", {})
                    assert not listed.is_error
                    assert all(SENTINEL not in block.model_dump_json() for block in listed.content)
                    assert SENTINEL not in json.dumps(listed.structured_content)
            finally:
                await client.aclose()
    finally:
        await administrator.aclose()


async def test_business_bank_config_hides_overrides_without_rejecting_reads(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    """A real member reads empty config projections; the Admin retains settings."""
    deployment = contextdb_deployment
    clients = contextdb_clients
    bank = clients.bank_id
    administrator = Hindsight(
        base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
    )
    try:
        before = await clients.read_only.aget_bank_config(bank)
        assert before == {"bank_id": bank, "config": {}, "overrides": {}}
        changed = await administrator.aupdate_bank_config(bank, retain_chunk_size=1800)
        assert changed["config"]["retain_chunk_size"] == 1800
        assert changed["overrides"] == {"retain_chunk_size": 1800}

        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
        ) as management:
            created = await management.post("/users", json={"name": "Config reader " + secrets.token_hex(6)})
            assert created.status_code == 201, created.text
            user_id = created.json()["user_id"]
            issued = await management.post(
                f"/users/{user_id}/keys",
                json={"name": "All-space config reader", "authorization": {"mode": "all", "permission": "read"}},
            )
            assert issued.status_code == 201, issued.text
        all_reader = Hindsight(base_url=deployment.server.url, api_key=issued.json()["secret"])
        try:
            for reader in (clients.read_only, clients.own, all_reader):
                # The published client must still succeed: this is field filtering,
                # not an administrator-only replacement for the GET operation.
                state = await reader.aget_bank_config(bank)
                assert state == {"bank_id": bank, "config": {}, "overrides": {}}
                generated = await reader.banks.get_bank_config(bank)
                assert generated.config == {} and generated.overrides == {}
        finally:
            await all_reader.aclose()
        with pytest.raises(ForbiddenException):
            await clients.other_bank.banks.get_bank_config(bank)
        for key in (clients.read_only_key, clients.own_key):
            async with Client(deployment.server.url + f"/mcp/{bank}/", auth=key) as mcp:
                tools = {tool.name for tool in await mcp.list_tools()}
                assert "get_bank" in tools
                assert {"create_bank", "delete_bank", "update_bank"}.isdisjoint(tools)
                profile = await mcp.call_tool("get_bank", {})
                assert not profile.is_error
        visible = await administrator.aget_bank_config(bank)
        assert visible["config"]["retain_chunk_size"] == 1800
        assert visible["overrides"] == {"retain_chunk_size": 1800}
        reset = await administrator.areset_bank_config(bank)
        assert reset["overrides"] == {}
        assert await clients.read_only.aget_bank_config(bank) == {"bank_id": bank, "config": {}, "overrides": {}}
    finally:
        await administrator.aclose()


async def test_business_keys_cannot_read_hidden_settings_through_prompt_preview(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    from hindsight_client_api.models.prompt_preview_request import PromptPreviewRequest

    deployment, clients = contextdb_deployment, contextdb_clients
    admin = Hindsight(
        base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
    )
    try:
        await admin.aupdate_bank_config(clients.bank_id, retain_chunk_size=1877)
        preview = await admin.banks.preview_prompt(clients.bank_id, PromptPreviewRequest(operation="retain"))
        assert preview.run_settings is not None
        assert {item.var_field: item.value for item in preview.run_settings}["retain_chunk_size"] == "1877"
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
        ) as management:
            created = await management.post("/users", json={"name": "Preview reader " + secrets.token_hex(5)})
            assert created.status_code == 201
            keys = []
            for permission in ("read", "read_write"):
                issued = await management.post(
                    f"/users/{created.json()['user_id']}/keys",
                    json={"name": permission, "authorization": {"mode": "all", "permission": permission}},
                )
                assert issued.status_code == 201
                keys.append(issued.json()["secret"])
        for credential in (clients.own_key, clients.read_only_key, *keys):
            reader = Hindsight(base_url=deployment.server.url, api_key=credential)
            try:
                assert await reader.aget_bank_config(clients.bank_id) == {
                    "bank_id": clients.bank_id,
                    "config": {},
                    "overrides": {},
                }
                with pytest.raises(ForbiddenException):
                    await reader.banks.preview_prompt(clients.bank_id, PromptPreviewRequest(operation="retain"))
                assert await reader.arecall(clients.bank_id, "Preview did not change memory") is not None
            finally:
                await reader.aclose()
    finally:
        await admin.aclose()
