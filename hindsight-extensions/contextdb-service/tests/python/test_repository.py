"""Real PG metadata invariants; lifecycle/engine behavior has separate blackbox tests."""

from __future__ import annotations

import asyncio

import pytest
from hindsight_ext_contextdb.models import (
    BusinessPrincipal,
    Permission,
    Role,
    ServiceError,
    UserCreate,
    UserPatch,
    Workspace,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository

from .support.identities import (
    ADMIN,
    admin_actor,
    key_input,
    ready_workspace,
    space_user,
)


async def test_concurrent_create_is_strict_and_reserves_one_identity(repository: Repository) -> None:
    async def create():
        return await repository.create_workspace(ADMIN, WorkspaceCreate(name="same"), "request")

    results = await asyncio.gather(create(), create(), create(), return_exceptions=True)
    assert len([item for item in results if isinstance(item, Workspace)]) == 1
    assert len([item for item in results if isinstance(item, ServiceError) and item.status == 409]) == 2
    page = await repository.list_workspaces(ADMIN, 10, 0)
    assert page.total == 1 and page.items[0].state == "creating"


async def test_key_is_the_only_workspace_authorization(repository: Repository) -> None:
    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    actor = await admin_actor(repository)
    user = await space_user(repository, first.workspace_id)
    key = await repository.create_key(actor, user.user_id, key_input(second.bank_id), "key")
    assert (await repository.authenticate(key.secret, second.bank_id)).user_id == user.user_id
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret, first.bank_id)


async def test_member_cannot_manage_keys_or_directory(repository: Repository) -> None:
    space = await ready_workspace(repository)
    actor = await admin_actor(repository)
    user = await space_user(repository, space.workspace_id)
    key = await repository.create_key(actor, user.user_id, key_input(space.bank_id), "key")
    with pytest.raises(ServiceError) as error:
        await repository.authenticate_admin(key.secret)
    assert error.value.status == 403
    principal = BusinessPrincipal(
        key.metadata.key_id, user.user_id, Role.MEMBER, "all", frozenset(), Permission.READ_WRITE
    )
    for operation in (
        repository.list_users(principal, 10, 0),
        repository.create_key(principal, user.user_id, key_input(space.bank_id), "self-key"),
        repository.create_user(principal, UserCreate(name="Forbidden"), "self-user"),
    ):
        with pytest.raises(ServiceError):
            await operation


async def test_key_listing_hides_secret_and_digest(repository: Repository) -> None:
    space = await ready_workspace(repository)
    actor = await admin_actor(repository)
    user = await space_user(repository, space.workspace_id)
    issued = await repository.create_key(actor, user.user_id, key_input(space.bank_id), "key")
    page = await repository.list_keys(actor, user.user_id, 10, 0)
    assert page.total == 1 and page.items[0].key_id == issued.metadata.key_id
    assert "secret" not in page.model_dump_json() and "digest" not in page.model_dump_json()


async def test_revoke_disable_and_workspace_delete_affect_next_authentication(repository: Repository) -> None:
    space = await ready_workspace(repository)
    actor = await admin_actor(repository)
    user = await space_user(repository, space.workspace_id)
    key = await repository.create_key(actor, user.user_id, key_input(space.bank_id), "key")
    assert (await repository.authenticate(key.secret, space.bank_id)).workspace_id == space.workspace_id
    user = await repository.update_user(actor, user.user_id, UserPatch(status="disabled"), 1, "disable")
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)
    await repository.update_user(actor, user.user_id, UserPatch(status="active"), user.version, "enable")
    assert (await repository.authenticate(key.secret, space.bank_id)).workspace_id == space.workspace_id
    await repository.revoke_key(actor, user.user_id, key.metadata.key_id, "revoke")
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)
    fresh = await repository.create_key(actor, user.user_id, key_input(space.bank_id), "fresh")
    await repository.delete_workspace(
        ADMIN, space.bank_id, "request", expected_id=space.workspace_id, expected_version=space.version
    )
    with pytest.raises(ServiceError):
        await repository.authenticate(fresh.secret, space.bank_id)


async def test_pagination_and_worker_discovery_follow_space_state(repository: Repository) -> None:
    for index in range(3):
        await ready_workspace(repository, f"space_{index}")
    first = await repository.list_workspaces(ADMIN, 2, 0)
    last = await repository.list_workspaces(ADMIN, 2, 2)
    assert first.total == last.total == 3
    assert len(first.items) == 2
    assert len(last.items) == 1
    assert not set(item.workspace_id for item in first.items) & set(item.workspace_id for item in last.items)
    assert len(await repository.worker_workspaces()) == 3
