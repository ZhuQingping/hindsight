"""Usage reads follow content authority; refresh never mutates usage."""

from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from hindsight_ext_contextdb.models import ApiKeyCreate, ApiKeyPatch, UserPatch
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.usage_repository import UsageDelta, UsageRepository, UsageTarget, provision_usage_tables

from .support.identities import ADMIN, ready_workspace, space_user


@pytest.fixture
async def usage_space(repository):
    space = await ready_workspace(repository, "usage_auth")
    async with repository.pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{space.schema_name}"')
        await conn.execute(
            f'CREATE TABLE "{space.schema_name}".knowledge_pages (id text PRIMARY KEY,bank_id text,kind text)'
        )
        await conn.execute(
            f"INSERT INTO \"{space.schema_name}\".knowledge_pages VALUES('page',$1,'page')", space.bank_id
        )
        await provision_usage_tables(conn, space.schema_name)
    return space


async def issue(repository, space, mode="selected", permission="read"):
    user = await space_user(repository, space.workspace_id, "Usage " + uuid4().hex)
    authorization = (
        {"mode": "all", "permission": permission}
        if mode == "all"
        else {"mode": "selected", "workspaces": [{"bank_id": space.bank_id, "permission": permission}]}
    )
    return await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="Usage reader", authorization=authorization), "k"
    )


@pytest.mark.parametrize("mode", ["all", "selected"])
@pytest.mark.parametrize("permission", ["read", "read_write"])
@pytest.mark.parametrize("kind", ["memory", "knowledge_page"])
async def test_read_and_refresh_follow_content_scope_without_mutating_stats(
    repository, management, usage_space, monkeypatch, mode, permission, kind
):
    space = usage_space
    identity = str(uuid4()) if kind == "memory" else "page"
    store = Mock()
    store.live_memory_ids = AsyncMock(return_value={identity})
    monkeypatch.setattr("hindsight_api.engine.memories.get_memories", lambda: store)
    target = UsageTarget(space.workspace_id, space.bank_id, space.schema_name)
    at = datetime.now(timezone.utc)
    usage = UsageRepository(repository.pool)
    await usage.write(target, [UsageDelta(kind, identity, 3, at)])
    key = await issue(repository, space, mode, permission)
    pool = repository.pool
    proxy = Mock(wraps=pool)
    proxy.fetchrow = AsyncMock(wraps=pool.fetchrow)
    management.memory.pool = proxy
    path = f"/workspaces/{space.bank_id}/usage"
    params = [("object_type", kind), ("ids", identity), ("ids", identity)]
    headers = {"Authorization": "Bearer " + key.secret}
    for _ in range(2):
        response = await management.client.get(path, params=params, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["items"] == [
            {"object_id": identity, "recall_count": 3, "last_recalled_at": at.isoformat().replace("+00:00", "Z")}
        ]
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json()["bank_id"] == space.bank_id
    # One targeted authentication SQL per GET, not per object or twice per route.
    assert proxy.fetchrow.await_count == 2
    assert (await usage.read(target, kind, [identity]))[0].last_recalled_at == at
    assert (await usage.read(target, kind, [identity]))[0].recall_count == 3


async def test_usage_auth_rechecks_key_user_and_grants_on_every_get(repository, management, usage_space):
    space = usage_space
    other = await ready_workspace(repository, "other")
    path = f"/workspaces/{space.bank_id}/usage?object_type=knowledge_page&ids=page"
    for mutation in ("revoke", "disable", "grant"):
        key = await issue(repository, space)
        user_id, key_id = key.metadata.user_id, key.metadata.key_id
        headers = {"Authorization": "Bearer " + key.secret}
        assert (await management.client.get(path, headers=headers)).status_code == 200
        if mutation == "revoke":
            await repository.revoke_key(ADMIN, user_id, key_id, "revoke")
        elif mutation == "disable":
            await repository.update_user(ADMIN, user_id, UserPatch(status="disabled"), 1, "disable")
        else:
            await repository.update_key(
                ADMIN,
                user_id,
                key_id,
                ApiKeyPatch(
                    authorization={"mode": "selected", "workspaces": [{"bank_id": other.bank_id, "permission": "read"}]}
                ),
                1,
                "move",
            )
        response = await management.client.get(path, headers=headers)
        assert response.status_code == (403 if mutation == "grant" else 401)
        if mutation == "disable":
            await repository.update_user(ADMIN, user_id, UserPatch(status="active"), 2, "enable")


async def test_wrong_space_inactive_recreated_and_missing_key_cannot_read_usage(repository, management, usage_space):
    space = usage_space
    other = await ready_workspace(repository, "other")
    key = await issue(repository, other)
    path = f"/workspaces/{space.bank_id}/usage?object_type=knowledge_page&ids=page"
    for headers, status in (
        ({}, 401),
        ({"Authorization": "Bearer invalid"}, 401),
        ({"Authorization": "Bearer " + key.secret}, 403),
    ):
        assert (await management.client.get(path, headers=headers)).status_code == status
    key = await issue(repository, space)
    headers = {"Authorization": "Bearer " + key.secret}
    await repository.pool.execute(
        "UPDATE ctxdb_meta.workspaces SET state='deleting' WHERE workspace_id=$1", space.workspace_id
    )
    assert (await management.client.get(path, headers=headers)).status_code == 403
    await repository.pool.execute(
        "UPDATE ctxdb_meta.workspaces SET state='active' WHERE workspace_id=$1", space.workspace_id
    )
    deleted = await management.client.delete(
        f"/workspaces/{space.bank_id}", headers={**management.headers, "If-Match": space.etag}
    )
    assert deleted.status_code == 204
    created = await management.client.post("/workspaces", json={"name": space.bank_id}, headers=management.headers)
    assert created.status_code == 201
    assert created.json()["workspace_id"] != space.workspace_id
    assert (await management.client.get(path, headers=headers)).status_code == 403


@pytest.mark.parametrize("kind", ["memory", "knowledge_page"])
async def test_scope_denial_never_reads_usage(repository, management, usage_space, monkeypatch, kind):
    key = await issue(repository, usage_space)
    principal = await repository.authenticate(key.secret, usage_space.bank_id)
    monkeypatch.setattr(Repository, "authenticate", AsyncMock(return_value=replace(principal, scopes=frozenset())))
    read = AsyncMock(side_effect=AssertionError("Denied calls must not query usage"))
    monkeypatch.setattr(UsageRepository, "read", read)
    response = await management.client.get(
        f"/workspaces/{usage_space.bank_id}/usage",
        params={"object_type": kind, "ids": "page"},
        headers={"Authorization": "Bearer " + key.secret},
    )
    assert response.status_code == 403 and response.json()["code"] == "scope_forbidden"
    read.assert_not_awaited()


async def test_authorized_zero_omitted_invalid_and_unavailable_results(repository, management, usage_space):
    space = usage_space
    key = await issue(repository, space)
    headers = {"Authorization": "Bearer " + key.secret}
    path = f"/workspaces/{space.bank_id}/usage"
    response = await management.client.get(
        path, params=[("object_type", "knowledge_page"), ("ids", "page"), ("ids", "missing")], headers=headers
    )
    assert response.json()["items"] == [{"object_id": "page", "recall_count": 0, "last_recalled_at": None}]
    for params in (
        {"object_type": "invalid", "ids": "page"},
        {"object_type": "memory", "ids": "not-a-uuid"},
        [("object_type", "knowledge_page"), *(("ids", "page") for _ in range(101))],
    ):
        assert (await management.client.get(path, params=params, headers=headers)).status_code == 400
    await repository.pool.execute(f'DROP TABLE "{space.schema_name}".ctxdb_usage_stats')
    response = await management.client.get(
        path, params={"object_type": "knowledge_page", "ids": "page"}, headers=headers
    )
    assert response.status_code == 503 and response.json()["code"] == "usage_unavailable"
