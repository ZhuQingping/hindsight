"""All management routes share operator Bearer authentication and real PG metadata."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.http import ContextDBHttpExtension
from hindsight_ext_contextdb.repository import Repository

from .test_repository import (
    ADMIN_SECRET,
    admin_actor,
    key_input,
    ready_workspace,
    space_user,
)


@dataclass
class PoolHost:
    pool: asyncpg.Pool
    tenant_extension: object | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@dataclass
class ManagementClient:
    client: httpx.AsyncClient
    headers: dict[str, str] = field(repr=False)
    app: FastAPI
    admin_headers: dict[str, str] = field(repr=False)


@pytest_asyncio.fixture
async def management(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[ManagementClient]:
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN", raising=False)
    extension = ContextDBHttpExtension({})
    app = FastAPI()
    app.include_router(extension.get_router(cast(MemoryEngine, PoolHost(repository.pool))), prefix="/ext")
    transport = httpx.ASGITransport(app=app, client=("192.0.2.10", 23001))
    headers = {"Authorization": f"Bearer {ADMIN_SECRET}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test/ext/contextdb/v1") as client:
        yield ManagementClient(client, headers, app, headers)


async def test_auth_precedes_body_validation_and_errors_hide_credentials(management):
    response = await management.client.post("/workspaces", content="not-json")
    assert response.status_code == 401 and response.json()["code"] == "invalid_key"
    response = await management.client.post("/workspaces", content="not-json", headers=management.headers)
    assert response.status_code == 400
    assert ADMIN_SECRET not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


async def test_workspace_lifecycle_and_operations_use_same_admin_bearer(repository, management):
    client, headers = management.client, management.headers
    response = await client.post(
        "/workspaces", json={"name": "Managed"}, headers={**headers, "Idempotency-Key": "managed"}
    )
    assert response.status_code == 202
    op = response.json()
    assert response.headers["Location"] == "/ext/contextdb/v1/operations/" + op["operation_id"]
    assert set(op) == {"operation_id", "workspace_id", "action", "state", "error_code"}
    assert (
        await client.post("/workspaces", json={"name": "Managed"}, headers={**headers, "Idempotency-Key": "managed"})
    ).json()["operation_id"] == op["operation_id"]
    assert (await client.get("/operations/" + op["operation_id"], headers=headers)).status_code == 200
    assert (await client.get("/workspaces/managed", headers=headers)).status_code == 200
    assert (await client.get("/workspaces?q=managed", headers=headers)).json()["total"] == 1
    assert (await client.get("/workspaces?q=missing", headers=headers)).json()["total"] == 0
    claimed = await repository.claim_operation()
    await repository.complete_operation(claimed)
    deletion = await client.delete(
        "/workspaces/managed", headers={**headers, "Idempotency-Key": "delete", "If-Match": f'"{op["workspace_id"]}:2"'}
    )
    assert deletion.status_code == 202
    assert deletion.json()["action"] == "delete_workspace"


async def test_user_key_crud_and_etag_without_user_authorization(repository, management):
    space = await ready_workspace(repository)
    client, headers = management.client, management.headers
    response = await client.post("/users", json={"name": "App"}, headers=headers)
    assert response.status_code == 201
    user = response.json()
    path = "/users/" + user["user_id"]
    assert not {"role", "workspace_ids", "workspace_access", "instance_id"} & user.keys()
    assert response.headers["ETag"] == '"1"'
    assert (await client.get("/users?q=App", headers=headers)).json()["total"] == 1
    created = await client.post(
        path + "/keys",
        json={
            "name": "Client",
            "authorization": {
                "mode": "selected",
                "workspaces": [{"bank_id": space.bank_id, "permission": "read"}],
            },
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    key = created.json()
    keypath = path + "/keys/" + key["key_id"]
    listing = await client.get(path + "/keys?q=Client", headers=headers)
    assert listing.json()["total"] == 1 and "secret" not in listing.text and "digest" not in listing.text
    change = await client.patch(
        keypath,
        json={"authorization": {"mode": "all", "permission": "read_write"}},
        headers={**headers, "If-Match": '"1"'},
    )
    assert change.status_code == 200 and change.json()["version"] == 2
    assert (await repository.authenticate(key["secret"], space.bank_id)).permission.value == "read_write"
    stale = await client.patch(
        keypath,
        json={
            "authorization": {
                "mode": "selected",
                "workspaces": [{"bank_id": space.bank_id, "permission": "read_write"}],
            }
        },
        headers={**headers, "If-Match": '"1"'},
    )
    assert stale.status_code == 412
    assert (
        await client.patch(path, json={"status": "disabled"}, headers={**headers, "If-Match": '"1"'})
    ).status_code == 200
    assert (await client.delete(keypath, headers=headers)).status_code == 204
    assert (await client.delete(path, headers=headers)).status_code == 204
    assert (await client.get("/users", headers=headers)).json()["total"] == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/admin/identity"),
        ("GET", "/workspaces"),
        ("POST", "/workspaces"),
        ("GET", "/workspaces/" + "a" * 32),
        ("DELETE", "/workspaces/" + "a" * 32),
        ("GET", "/operations/" + "a" * 32),
        ("GET", "/users"),
        ("POST", "/users"),
        ("PATCH", "/users/" + "a" * 32),
        ("DELETE", "/users/" + "a" * 32),
        ("GET", "/users/" + "a" * 32 + "/keys"),
        ("POST", "/users/" + "a" * 32 + "/keys"),
        ("PATCH", "/users/" + "a" * 32 + "/keys/" + "b" * 32),
        ("DELETE", "/users/" + "a" * 32 + "/keys/" + "b" * 32),
    ],
)
async def test_business_keys_cannot_call_any_management_method(repository, management, method, path):
    space = await ready_workspace(repository)
    user = await space_user(repository, space.workspace_id)
    key = await repository.create_key(await admin_actor(repository), user.user_id, key_input(space.bank_id), "key")
    response = await management.client.request(
        method, path, headers={"Authorization": f"Bearer {key.secret}"}, content="invalid-json"
    )
    assert response.status_code == 403
    assert response.json()["code"] == "admin_required"


@pytest.mark.parametrize("path", ["/instances", "/instances/instance-test", "/instances/instance-test/admin-keys"])
async def test_removed_instance_interfaces_are_absent(management, path):
    assert (await management.client.post(path, headers=management.headers)).status_code == 404


async def test_missing_preconditions_and_legacy_fields_fail_safely(management):
    client, headers = management.client, management.headers
    response = await client.post("/workspaces", json={"name": "A"}, headers=headers)
    assert response.status_code == 400 and response.json()["code"] == "invalid_idempotency"
    response = await client.patch("/users/" + "a" * 32, json={"name": "A"}, headers=headers)
    assert response.status_code == 400 and response.json()["code"] == "invalid_version"
    response = await client.post("/users", json={"name": "A", "workspace_ids": []}, headers=headers)
    assert response.status_code == 400
    assert (await client.get("/users/nonexistent", headers=headers)).status_code == 405
    response = await client.post("/users", json={"name": "A"}, headers={"X-ContextDB-Control-Key": ADMIN_SECRET})
    assert response.status_code == 401


def test_management_openapi_declares_only_fourteen_operations(management):
    spec = management.app.openapi()
    assert sum(len(path) for path in spec["paths"].values()) == 14
    assert set(spec["components"]["securitySchemes"]) == {"AdministratorKey"}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation["security"] == [{"AdministratorKey": []}]
            assert "422" not in operation["responses"]
            if method == "get" and path.endswith(("/workspaces", "/users", "/keys")):
                assert {"q", "limit", "offset"} == {x["name"] for x in operation["parameters"] if x["in"] == "query"}
    fields = spec["components"]["schemas"]["ManagementOperationResponse"]["properties"]
    assert not {"attempts", "lease_token", "actor_subject", "instance_id"} & fields.keys()


@pytest.mark.parametrize("value", ["", "spaces forbidden", "bad/slash", "a" * 129, "é"])
async def test_idempotency_ascii_contract(management, value):
    # HTTP transport requires Latin-1 header bytes for non-ASCII test values.
    response = await management.client.post(
        "/workspaces",
        json={"name": "header_test"},
        headers={**management.headers, "Idempotency-Key": value.encode("latin-1")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_idempotency"


@pytest.mark.parametrize("value", ['"0"', '"01"', '"-1"', '"١"', "*", "1", '"' + "1" * 23 + '"'])
async def test_version_requires_quoted_positive_ascii(management, value):
    response = await management.client.patch(
        "/users/" + "a" * 32,
        json={"name": "header_test"},
        headers={**management.headers, "If-Match": value.encode("utf-8")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_version"


@pytest.mark.parametrize("path", ["/operations/not-an-id", "/users/ABC/keys"])
async def test_resource_ids_have_one_format(management, path):
    response = await management.client.get(path, headers=management.headers)
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_id"


async def test_validation_hints_never_echo_inputs_or_unknown_field_names(management):
    response = await management.client.post(
        "/users", json={"name": "x" * 65, "secret-sentinel-field": "secret-sentinel-value"}, headers=management.headers
    )
    assert response.status_code == 400
    body = response.json()
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert {"field": "body.name", "reason": "invalid"} in body["fields"]
    assert "secret-sentinel" not in response.text
    assert "input" not in response.text


async def test_key_name_edit_preserves_mixed_authorization_and_secret(repository, management):
    first = await ready_workspace(repository, "Read")
    second = await ready_workspace(repository, "Write")
    user = await space_user(repository, first.workspace_id)
    path = f"/users/{user.user_id}/keys"
    body = {
        "name": "Mixed",
        "authorization": {
            "mode": "selected",
            "workspaces": [
                {"bank_id": first.bank_id, "permission": "read"},
                {"bank_id": second.bank_id},
            ],
        },
    }
    created = await management.client.post(path, json=body, headers=management.headers)
    assert created.status_code == 201
    key = created.json()
    assert key["display_key"] == "ctx_live_***" + key["secret"][-6:]
    assert not {"access_mode", "workspace_ids", "permission", "revoked_at", "status"} & key.keys()
    keypath = path + "/" + key["key_id"]
    changed = await management.client.patch(
        keypath, json={"name": "Renamed"}, headers={**management.headers, "If-Match": '"1"'}
    )
    assert changed.status_code == 200
    assert changed.json()["authorization"] == key["authorization"]
    assert changed.json()["display_key"] == key["display_key"]
    assert "secret" not in changed.json()
    assert (await repository.authenticate(key["secret"], first.bank_id)).permission.value == "read"
    assert (await repository.authenticate(key["secret"], second.bank_id)).permission.value == "read_write"
    incomplete = await management.client.patch(
        keypath,
        json={"authorization": {"mode": "all"}},
        headers={**management.headers, "If-Match": changed.headers["ETag"]},
    )
    assert incomplete.status_code == 400
    assert (await management.client.delete(keypath, headers=management.headers)).status_code == 204
    assert (await management.client.delete(keypath, headers=management.headers)).status_code == 204
    page = (await management.client.get(path + "?limit=1&offset=0", headers=management.headers)).json()
    assert page["total"] == 0 and page["items"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": "Legacy", "access_mode": "all", "permission": "read"},
        {"name": "Mixed", "workspace_ids": [], "authorization": {"mode": "all"}},
        {"name": "Ambiguous", "authorization": {"mode": "all", "workspaces": []}},
    ],
)
async def test_one_authorization_contract_rejects_legacy_or_mixed_fields(repository, management, body):
    workspace = await ready_workspace(repository)
    user = await space_user(repository, workspace.workspace_id)
    response = await management.client.post(f"/users/{user.user_id}/keys", json=body, headers=management.headers)
    assert response.status_code == 400
    assert response.json()["request_id"]
