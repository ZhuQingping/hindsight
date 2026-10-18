"""Bound SQL work without weakening authorization, generation or DB constraints."""

import asyncio
from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest
from hindsight_ext_contextdb.authorization import authenticated_request
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    Permission,
    SelectedAuthorization,
    ServiceError,
    UserCreate,
)

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace


async def test_targeted_auth_reads_one_snapshot_and_only_the_target_grant(repository):
    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "u")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="two",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": first.bank_id},
                    {"bank_id": second.bank_id, "permission": "read"},
                ],
            },
        ),
        "k",
    )
    pool = repository.pool
    proxy = Mock(wraps=pool)
    proxy.fetchrow = AsyncMock(wraps=pool.fetchrow)
    repository.pool = proxy
    principal = await repository.authenticate(issued.secret, second.bank_id)
    assert principal.permission == Permission.READ
    assert principal.workspace_ids == {second.workspace_id}
    assert proxy.fetchrow.await_count == 1
    proxy.fetchval.assert_not_called()


async def test_request_reuses_target_auth_but_next_request_rechecks_revocation(repository, configured):
    space = await ready_workspace(repository)
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "u")
    issued = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="all", authorization={"mode": "all"}), "k"
    )
    before = await repository.authenticate(issued.secret, space.bank_id)
    with authenticated_request(issued.secret, before, space.bank_id, configured):
        await repository.revoke_key(ADMIN, user.user_id, issued.metadata.key_id, "revoke")
        assert await repository.authenticate(issued.secret, space.bank_id) is before
        with pytest.raises(ServiceError):
            await repository.authenticate(ADMIN_SECRET.replace("b", "c"), space.bank_id)
        # Target snapshots do not grant unscoped directory access.
        with pytest.raises(ServiceError):
            await repository.authenticate(issued.secret)
    with pytest.raises(ServiceError):
        await repository.authenticate(issued.secret, space.bank_id)


async def test_thousand_grants_use_bounded_sql_and_still_reject_overflow(repository):
    await repository.pool.execute(
        "INSERT INTO ctxdb_meta.workspaces(workspace_id,bank_id,schema_name,state) SELECT lpad(to_hex(i),32,'0'),'ws_'||i,'ctxdb_ws_ws_'||i,'active' FROM generate_series(1,1001) AS i"
    )
    user = await repository.create_user(ADMIN, UserCreate(name="Bulk"), "u")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="selected", authorization={"mode": "selected", "workspaces": [{"bank_id": "ws_1"}]}),
        "k",
    )
    body = SelectedAuthorization(workspaces=[{"bank_id": f"ws_{i}"} for i in range(1, 1001)])
    logged = []
    async with repository.pool.acquire() as conn:
        async with conn.transaction():
            with conn.query_logger(logged.append):
                await repository._replace_authorization(conn, issued.metadata.key_id, body)
                await asyncio.sleep(0)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM ctxdb_meta.key_workspace_permissions WHERE key_id=$1", issued.metadata.key_id
            )
            == 1000
        )
        assert len(logged) == 3
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO ctxdb_meta.key_workspace_permissions SELECT $1,workspace_id,'read' FROM ctxdb_meta.workspaces WHERE bank_id='ws_1001'",
                    issued.metadata.key_id,
                )
    assert (await repository.authenticate(issued.secret, "ws_1000")).workspace_id is not None


async def test_selected_key_denials_do_not_disclose_other_workspace_existence(repository):
    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    user = await repository.create_user(ADMIN, UserCreate(name="Scoped"), "u")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="one", authorization={"mode": "selected", "workspaces": [{"bank_id": first.bank_id}]}),
        "k",
    )
    errors = []
    for target in (second.bank_id, "absent"):
        with pytest.raises(ServiceError) as error:
            await repository.authenticate(issued.secret, target)
        errors.append((error.value.status, error.value.code, error.value.message))
    assert errors[0] == errors[1]
