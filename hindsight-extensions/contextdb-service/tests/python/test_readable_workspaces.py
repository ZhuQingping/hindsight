"""Readable native Bank addresses keep immutable authorization/lifecycle identity."""

from __future__ import annotations

import asyncio

import pytest
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    ApiKeyPatch,
    ServiceError,
    UserCreate,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository
from pydantic import ValidationError

from .support.identities import ADMIN, ready_workspace
from .support.lifecycle import lifecycle_for


@pytest.mark.parametrize("name", ["jiamu", "MySQL", "a" * 54, "ws_2_a"])
async def test_readable_bank_and_schema_are_canonical_and_bounded(repository: Repository, name: str) -> None:
    space = await ready_workspace(repository, name)
    assert space.bank_id == space.name == name.lower()
    assert space.schema_name == "ctxdb_ws_" + name.lower()
    assert len(space.schema_name.encode()) <= 63
    assert space.workspace_id != space.bank_id
    assert (await repository.get_workspace_by_name(ADMIN, space.bank_id)).workspace_id == space.workspace_id


@pytest.mark.parametrize(
    "name", ["a" * 55, "中文", "two words", "bad-hyphen", "1bank", "../bank", 'x";DROP SCHEMA public']
)
def test_new_names_reject_ambiguous_or_unsafe_identifiers(name: str) -> None:
    with pytest.raises(ValidationError):
        WorkspaceCreate(name=name)


async def test_concurrent_case_variants_cannot_claim_same_readable_schema(repository: Repository) -> None:
    results = await asyncio.gather(
        repository.create_workspace(ADMIN, WorkspaceCreate(name="MySQL"), "r1"),
        repository.create_workspace(ADMIN, WorkspaceCreate(name="mysql"), "r2"),
        return_exceptions=True,
    )
    assert len([item for item in results if isinstance(item, ServiceError) and item.status == 409]) == 1
    assert (await repository.list_workspaces(ADMIN, 10, 0)).total == 1


async def test_unregistered_schema_is_never_adopted(repository: Repository) -> None:
    await repository.pool.execute("CREATE SCHEMA ctxdb_ws_foreign")
    with pytest.raises(ServiceError) as error:
        await repository.create_workspace(ADMIN, WorkspaceCreate(name="foreign"), "r")
    assert error.value.code == "schema_conflict"
    assert (await repository.list_workspaces(ADMIN, 10, 0)).total == 0


async def test_same_name_successor_does_not_inherit_selected_grants_or_stale_deletes(repository: Repository) -> None:
    old = await ready_workspace(repository, "jiamu")
    user = await repository.create_user(ADMIN, UserCreate(name="application"), "u")
    selected = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="selected", authorization={"mode": "selected", "workspaces": [{"bank_id": "jiamu"}]}),
        "k1",
    )
    all_spaces = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="future", authorization={"mode": "all"}), "k2"
    )
    grant = await repository.pool.fetchrow(
        "SELECT workspace_id FROM ctxdb_meta.key_workspace_permissions WHERE key_id=$1", selected.metadata.key_id
    )
    assert grant["workspace_id"] == old.workspace_id
    lifecycle = lifecycle_for(repository)
    await lifecycle.delete(ADMIN, old.bank_id, "delete", expected_id=old.workspace_id, expected_version=old.version)
    successor = await ready_workspace(repository, "jiamu")
    assert successor.bank_id == old.bank_id and successor.schema_name == old.schema_name
    assert successor.workspace_id != old.workspace_id and successor.etag != old.etag
    with pytest.raises(ServiceError) as forbidden:
        await repository.authenticate(selected.secret, successor.bank_id)
    assert forbidden.value.status == 403
    assert (await repository.authenticate(all_spaces.secret, successor.bank_id)).workspace_id == successor.workspace_id
    with pytest.raises(ServiceError) as stale_key:
        await repository.update_key(
            ADMIN,
            user.user_id,
            selected.metadata.key_id,
            ApiKeyPatch(
                authorization={"mode": "selected", "workspaces": [{"bank_id": "jiamu", "permission": "read_write"}]}
            ),
            selected.metadata.version,
            "stale-editor",
        )
    assert stale_key.value.status == 412
    with pytest.raises(ServiceError) as stale_delete:
        await lifecycle.delete(ADMIN, "jiamu", "stale", expected_id=old.workspace_id, expected_version=old.version)
    assert stale_delete.value.status == 412
    assert (await repository.get_workspace_by_name(ADMIN, "jiamu")).state == "active"


async def test_http_delete_requires_identity_etag_and_preserves_successor(repository, management) -> None:
    old = await ready_workspace(repository, "jiamu")
    client, headers = management.client, management.headers
    detail = await client.get("/workspaces/jiamu", headers=headers)
    assert detail.status_code == 200
    assert detail.headers["ETag"] == detail.json()["etag"] == old.etag
    listed = await client.get("/workspaces", headers=headers)
    assert listed.json()["items"][0]["bank_id"] == "jiamu"
    assert listed.json()["items"][0]["etag"] == old.etag
    request_headers = {**headers, "Idempotency-Key": "delete-once"}
    assert (await client.delete("/workspaces/jiamu", headers=request_headers)).status_code == 428
    assert (await client.delete("/workspaces/jiamu", headers={**request_headers, "If-Match": '"2"'})).status_code == 400
    response = await client.delete("/workspaces/jiamu", headers={**request_headers, "If-Match": old.etag})
    assert response.status_code == 204
    await ready_workspace(repository, "jiamu")
    stale = await client.delete("/workspaces/jiamu", headers={**headers, "If-Match": old.etag})
    assert stale.status_code == 412
    assert (await client.get("/workspaces/jiamu", headers=headers)).json()["state"] == "active"


async def test_grant_expectation_rejects_same_name_successor_for_new_and_existing_key(repository: Repository) -> None:
    old = await ready_workspace(repository, "jiamu")
    user = await repository.create_user(ADMIN, UserCreate(name="application"), "u")
    unaffected = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="existing", authorization={"mode": "all"}), "k"
    )
    lifecycle = lifecycle_for(repository)
    await lifecycle.delete(ADMIN, "jiamu", "d", expected_id=old.workspace_id, expected_version=old.version)
    created = await ready_workspace(repository, "jiamu")
    stale_authorization = {
        "mode": "selected",
        "workspaces": [{"bank_id": "jiamu", "workspace_id": old.workspace_id, "permission": "read_write"}],
    }
    before = await repository.list_keys(ADMIN, user.user_id, 10, 0)
    with pytest.raises(ServiceError) as stale_create:
        await repository.create_key(
            ADMIN, user.user_id, ApiKeyCreate(name="stale-picker", authorization=stale_authorization), "create"
        )
    assert stale_create.value.code == "workspace_generation_changed"
    assert (await repository.list_keys(ADMIN, user.user_id, 10, 0)).total == before.total
    # This Key never had an old grant, so its own version is still current.
    with pytest.raises(ServiceError) as stale_edit:
        await repository.update_key(
            ADMIN,
            user.user_id,
            unaffected.metadata.key_id,
            ApiKeyPatch(authorization=stale_authorization),
            unaffected.metadata.version,
            "edit",
        )
    assert stale_edit.value.code == "workspace_generation_changed"
    assert (await repository.authenticate(unaffected.secret, "jiamu")).workspace_id == created.workspace_id
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="fresh-picker",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": "jiamu", "workspace_id": created.workspace_id}],
            },
        ),
        "fresh",
    )
    assert (await repository.authenticate(issued.secret, "jiamu")).workspace_id == created.workspace_id


async def test_http_rejects_hyphen_before_creating_unquoted_native_schema(repository, management) -> None:
    response = await management.client.post(
        "/workspaces", json={"name": "bad-hyphen"}, headers={**management.headers, "Idempotency-Key": "invalid-hyphen"}
    )
    assert response.status_code == 400
    assert (await repository.list_workspaces(ADMIN, 10, 0)).total == 0
