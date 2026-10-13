"""All management routes use the real PG repository and one authentication wrapper."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from hindsight_ext_contextdb.http import ContextDBHttpExtension
from hindsight_ext_contextdb.repository import Repository

from .test_repository import ADMIN, ready_workspace


@dataclass
class PoolHost:
    pool: asyncpg.Pool

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@dataclass
class ManagementClient:
    client: httpx.AsyncClient
    headers: dict[str, str] = field(repr=False)
    app: FastAPI


@pytest_asyncio.fixture
async def management(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ManagementClient]:
    key_id = secrets.token_hex(16)
    secret = f"ctx_ctrl_{key_id}_{secrets.token_urlsafe(32)}"
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    monkeypatch.setenv(
        "CONTEXTDB_CONTROL_KEYS",
        json.dumps([{"key_id": key_id, "sha256": hashlib.sha256(secret.encode()).hexdigest()}]),
    )
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN", raising=False)
    extension = ContextDBHttpExtension({})
    app = FastAPI()
    app.include_router(extension.get_router(PoolHost(repository.pool)), prefix="/ext")
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 23001))
    async with httpx.AsyncClient(transport=transport, base_url="http://test/ext/contextdb/v1") as client:
        yield ManagementClient(
            client, {"X-ContextDB-Control-Key": secret, "X-ContextDB-Actor-Subject": ADMIN.actor_subject}, app
        )


async def test_management_auth_precedes_invalid_body_and_never_echoes_key(management: ManagementClient) -> None:
    response = await management.client.post("/workspaces", content="not-json")
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_control_key"
    response = await management.client.post("/workspaces", content="not-json", headers=management.headers)
    assert response.status_code == 400
    assert management.headers["X-ContextDB-Control-Key"] not in response.text


@pytest.mark.parametrize("name", ["Forwarded", "X-Forwarded-For"])
@pytest.mark.parametrize("values", [[""], ["", "for=127.0.0.1"]])
async def test_control_ingress_rejects_empty_or_duplicate_forwarding_headers(
    management: ManagementClient, name: str, values: list[str]
) -> None:
    headers = list(management.headers.items()) + [(name, value) for value in values]
    response = await management.client.get("/instances/instance-test", headers=headers)
    assert response.status_code == 403
    assert response.json()["code"] == "control_network"
    assert "request_id" in response.json()
    assert response.headers["Cache-Control"] == "no-store"
    response = await management.client.get(
        "/workspaces", headers={"X-ContextDB-Control-Key": management.headers["X-ContextDB-Control-Key"]}
    )
    assert response.status_code == 400


async def test_instance_workspace_and_operation_routes(management: ManagementClient) -> None:
    client, headers = management.client, management.headers
    response = await client.post(
        "/instances", json={"instance_id": "instance-test", "name": "Test instance"}, headers=headers
    )
    assert response.status_code == 201
    assert (await client.get("/instances/instance-test", headers=headers)).status_code == 200
    response = await client.post(
        "/workspaces", json={"name": "managed"}, headers={**headers, "Idempotency-Key": "managed"}
    )
    assert response.status_code == 202
    operation = response.json()
    assert set(operation) == {"operation_id", "workspace_id", "action", "state", "attempts", "error_code", "request_id"}
    assert operation["state"] == "pending"
    detail = await client.get(f"/operations/{operation['operation_id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["workspace_id"] == operation["workspace_id"]
    assert set(detail.json()) == set(operation)
    assert (await client.get(f"/workspaces/{operation['workspace_id']}", headers=headers)).status_code == 200
    assert (await client.get("/workspaces?limit=1&offset=0", headers=headers)).json()["limit"] == 1
    assert (await client.get("/workspaces?limit=1000", headers=headers)).status_code == 400


async def test_member_key_and_workspace_update_delete_routes(
    repository: Repository, management: ManagementClient
) -> None:
    workspace = await ready_workspace(repository)
    client, headers = management.client, management.headers
    path = f"/workspaces/{workspace.workspace_id}"
    response = await client.patch(
        path, json={"name": "Renamed"}, headers={**headers, "If-Match": f'"{workspace.version}"'}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert (
        await client.patch(path, json={"name": "Conflict"}, headers={**headers, "If-Match": f'"{workspace.version}"'})
    ).status_code == 412
    response = await client.post(
        path + "/members", json={"member_name": "Member", "iam_subject": "member-login"}, headers=headers
    )
    assert response.status_code == 201
    member = response.json()
    member_path = path + f"/members/{member['member_id']}"
    assert (await client.get(path + "/members", headers=headers)).json()["total"] == 2
    assert (await client.get(member_path, headers=headers)).headers["ETag"] == '"1"'
    response = await client.post(
        member_path + "/api-keys",
        json={
            "name": "Client",
            "scopes": ["memory.read", "memory.write"],
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
        headers={**headers, "Idempotency-Key": "one-key"},
    )
    assert response.status_code == 201
    key = response.json()
    assert key["status"] == "active"
    assert key["scopes"] == ["memory.read", "memory.write"]
    assert (await repository.authenticate(key["secret"])).workspace_id == workspace.workspace_id
    listing = await client.get(member_path + "/api-keys", headers=headers)
    assert listing.json()["total"] == 1
    assert "secret" not in listing.text and "digest" not in listing.text
    revoke = member_path + f"/api-keys/{key['key_id']}/revoke"
    assert (await client.post(revoke, headers=headers)).status_code == 204
    assert (await client.post(revoke, headers=headers)).status_code == 204
    assert (
        await client.patch(member_path, json={"status": "disabled"}, headers={**headers, "If-Match": '"1"'})
    ).status_code == 200
    assert (await client.delete(member_path, headers=headers)).status_code == 204
    assert (await client.delete(member_path, headers=headers)).status_code == 204
    response = await client.delete(path, headers={**headers, "Idempotency-Key": "delete-demo"})
    assert response.status_code == 202
    assert response.json()["action"] == "delete_workspace"


async def test_business_keys_cannot_call_any_management_method(
    repository: Repository, management: ManagementClient
) -> None:
    response = await management.client.get(
        "/workspaces",
        headers={
            "X-ContextDB-Control-Key": "ctx_live_not_a_control_key",
            "X-ContextDB-Actor-Subject": "admin-one",
        },
    )
    assert response.status_code == 401


def test_management_openapi_declares_all_routes_and_enforced_headers(management: ManagementClient) -> None:
    spec = management.app.openapi()
    assert spec["components"]["securitySchemes"]["ControlPlaneKey"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-ContextDB-Control-Key",
    }
    expected_operations = {
        "registerInstance",
        "getInstance",
        "createWorkspace",
        "listWorkspaces",
        "getWorkspace",
        "updateWorkspace",
        "deleteWorkspace",
        "getManagementOperation",
        "createMember",
        "listMembers",
        "getMember",
        "updateMember",
        "deleteMember",
        "createApiKey",
        "listApiKeys",
        "revokeApiKey",
    }
    operation_ids = set()
    for path, path_item in spec["paths"].items():
        assert path.startswith("/ext/contextdb/v1/")
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "delete"}:
                continue
            operation_ids.add(operation["operationId"])
            assert operation["security"] == [{"ControlPlaneKey": []}]
            parameters = {item["name"]: item for item in operation["parameters"]}
            assert parameters["X-ContextDB-Actor-Subject"]["required"] is True
            if operation["operationId"] in {"createWorkspace", "deleteWorkspace", "createApiKey"}:
                assert parameters["Idempotency-Key"]["required"] is (operation["operationId"] != "createApiKey")
            if method == "patch":
                assert parameters["If-Match"]["required"] is True
            if operation["operationId"] in {"listWorkspaces", "listMembers", "listApiKeys"}:
                assert parameters["limit"]["schema"]["maximum"] == 100
                assert parameters["offset"]["schema"]["minimum"] == 0
            responses = operation["responses"]
            assert "422" not in responses
            assert responses["400"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
            success_codes = [code for code in responses if code.startswith("2")]
            assert len(success_codes) == 1
            response = responses[success_codes[0]]
            assert {"X-Request-ID", "Cache-Control"} <= response["headers"].keys()
            if success_codes[0] == "204":
                assert "content" not in response
            else:
                model_name = response["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
                schema = spec["components"]["schemas"][model_name]
                assert "request_id" in schema["required"]
                assert "request_id" in schema["properties"]
    assert operation_ids == expected_operations
    fields = spec["components"]["schemas"]["ManagementOperationResponse"]["properties"]
    assert not {"lease_token", "actor_subject", "instance_id", "workspace_version"} & fields.keys()


async def test_management_documented_input_errors_remain_400_and_auth_first(management: ManagementClient) -> None:
    client, headers = management.client, management.headers
    missing_idempotency = await client.post("/workspaces", headers=headers, json={"name": "Incomplete"})
    assert missing_idempotency.status_code == 400
    assert missing_idempotency.json()["code"] == "invalid_idempotency"
    missing_version = await client.patch("/workspaces/nonexistent", headers=headers, json={"name": "Incomplete"})
    assert missing_version.status_code == 400
    assert missing_version.json()["code"] == "invalid_version"
    bad_body = await client.post("/instances", headers=headers, json={"unexpected": "redacted-test-input"})
    assert bad_body.status_code == 400
    assert bad_body.json()["code"] == "invalid_request"
    assert "redacted-test-input" not in bad_body.text
    unauthenticated = await client.post(
        "/workspaces", headers={"X-ContextDB-Actor-Subject": "valid-actor"}, content="not-json"
    )
    assert unauthenticated.status_code == 401
