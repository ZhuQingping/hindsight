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

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import ContextDBDeployment
from .test_110_contextdb_tenant_admin import operation_done

contextdb_deployment = service_story.contextdb_deployment
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
            headers={"Idempotency-Key": secrets.token_hex(16)},
        )
        assert response.status_code == 202, response.text
        await operation_done(management, response.json())
        bank = await service_story.operation_bank_id(management, response.json()["workspace_id"])
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
