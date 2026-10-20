"""All management routes share operator Bearer authentication and real PG metadata."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from .support.identities import (
    ADMIN_SECRET,
    admin_actor,
    key_input,
    ready_workspace,
    space_user,
)


async def test_auth_precedes_body_validation_and_errors_hide_credentials(management):
    response = await management.client.post("/workspaces", content="not-json")
    assert response.status_code == 401 and response.json()["code"] == "invalid_key"
    response = await management.client.post("/workspaces", content="not-json", headers=management.headers)
    assert response.status_code == 400
    assert ADMIN_SECRET not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]


async def test_workspace_lifecycle_is_sync_without_idempotency_or_operation_resource(repository, management):
    client, headers = management.client, management.headers
    response = await client.post("/workspaces", json={"name": "Managed", "description": "Example"}, headers=headers)
    assert response.status_code == 201, response.text
    workspace = response.json()
    assert workspace["state"] == "active" and workspace["description"] == "Example"
    assert workspace["bank_id"] == "managed"
    assert not {"operation_id", "latest_operation_id", "schema_name"} & workspace.keys()
    assert response.headers["ETag"] == workspace["etag"] and "Location" not in response.headers
    assert (await client.post("/workspaces", json={"name": "managed"}, headers=headers)).status_code == 409
    assert (await client.get("/operations/" + "a" * 32, headers=headers)).status_code == 404
    assert (await client.get("/workspaces?q=managed", headers=headers)).json()["total"] == 1
    deletion = await client.delete("/workspaces/managed", headers={**headers, "If-Match": workspace["etag"]})
    assert deletion.status_code == 204 and deletion.content == b""
    assert (await client.get("/workspaces/managed", headers=headers)).status_code == 404


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
    assert response.status_code == 201
    response = await client.patch("/users/" + "a" * 32, json={"name": "A"}, headers=headers)
    assert response.status_code == 400 and response.json()["code"] == "invalid_version"
    response = await client.post("/users", json={"name": "A", "workspace_ids": []}, headers=headers)
    assert response.status_code == 400
    assert (await client.get("/users/nonexistent", headers=headers)).status_code == 405
    response = await client.post("/users", json={"name": "A"}, headers={"X-ContextDB-Control-Key": ADMIN_SECRET})
    assert response.status_code == 401


def test_management_openapi_declares_only_thirteen_operations(management):
    spec = management.app.openapi()
    assert sum(len(path) for path in spec["paths"].values()) == 13
    assert set(spec["components"]["securitySchemes"]) == {"AdministratorKey"}
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation["security"] == [{"AdministratorKey": []}]
            assert "422" not in operation["responses"]
            if method == "get" and path.endswith(("/workspaces", "/users", "/keys")):
                assert {"q", "limit", "offset"} == {x["name"] for x in operation["parameters"] if x["in"] == "query"}
    assert "ManagementOperationResponse" not in spec["components"]["schemas"]


async def test_workspace_create_does_not_require_idempotency(management):
    response = await management.client.post("/workspaces", json={"name": "no_header"}, headers=management.headers)
    assert response.status_code == 201


@pytest.mark.parametrize("value", ['"0"', '"01"', '"-1"', '"١"', "*", "1", '"' + "1" * 23 + '"'])
async def test_version_requires_quoted_positive_ascii(management, value):
    response = await management.client.patch(
        "/users/" + "a" * 32,
        json={"name": "header_test"},
        headers={**management.headers, "If-Match": value.encode("utf-8")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_version"


@pytest.mark.parametrize("path", ["/users/ABC/keys"])
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


async def test_creation_response_waits_for_native_migration_without_polling(management):
    entered, release = asyncio.Event(), asyncio.Event()

    async def migrate(schema):
        entered.set()
        await release.wait()

    management.memory.tenant_extension.context.run_migration = AsyncMock(side_effect=migrate)
    task = asyncio.create_task(
        management.client.post("/workspaces", json={"name": "waiting"}, headers=management.headers)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert not task.done()
        current = await management.client.get("/workspaces/waiting", headers=management.headers)
        assert current.json()["state"] == "creating"
        release.set()
        result = await asyncio.wait_for(task, 5)
        assert result.status_code == 201 and result.json()["state"] == "active"
    finally:
        release.set()
        await task


async def test_native_creation_error_has_safe_response_and_failed_queryable_identity(management):
    management.memory.update_bank = AsyncMock(side_effect=RuntimeError("secret-native-error-sentinel"))
    response = await management.client.post("/workspaces", json={"name": "failure"}, headers=management.headers)
    assert response.status_code == 500
    assert response.json()["code"] == "management_failed"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
    assert "secret-native-error-sentinel" not in response.text
    failed = await management.client.get("/workspaces/failure", headers=management.headers)
    assert failed.status_code == 200 and failed.json()["state"] == "failed"
    assert (
        await management.client.post("/workspaces", json={"name": "failure"}, headers=management.headers)
    ).status_code == 409
    assert (
        await management.client.delete(
            "/workspaces/failure", headers={**management.headers, "If-Match": failed.headers["ETag"]}
        )
    ).status_code == 204
