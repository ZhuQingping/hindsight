"""Real PG metadata invariants; lifecycle/engine behavior has separate blackbox tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    ControlPrincipal,
    InstanceCreate,
    MemberCreate,
    MemberPatch,
    Role,
    Scope,
    ServiceError,
    Workspace,
    WorkspaceCreate,
    WorkspacePatch,
)
from hindsight_ext_contextdb.repository import Repository

ADMIN = ControlPrincipal("control-test", "tenant-test", "admin-one")
OTHER = ControlPrincipal("control-test", "tenant-test", "other-user")


async def ready_workspace(repository: Repository, name: str = "Demo") -> Workspace:
    operation = await repository.create_workspace(ADMIN, WorkspaceCreate(name=name), name, "request-create")
    # Foundation tests isolate metadata from engine migration. Production readiness
    # must be established by the lifecycle runner, never by a management client.
    claimed = await repository.claim_operation()
    assert claimed is not None and claimed.operation_id == operation.operation_id
    await repository.complete_operation(claimed)
    return await repository.get_workspace(ADMIN, operation.workspace_id)


def key_input() -> ApiKeyCreate:
    return ApiKeyCreate(
        name="test",
        scopes=[Scope.MEMORY_READ, Scope.MEMORY_WRITE],
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


async def test_instance_registration_is_fixed_to_deployment(repository: Repository) -> None:
    instance = await repository.get_instance(ADMIN, "instance-test")
    assert instance.cloud_tenant_id == "tenant-test"
    with pytest.raises(ServiceError) as error:
        await repository.create_instance(ADMIN, InstanceCreate(instance_id="somebody-else", name="Wrong instance"))
    assert error.value.status == 403
    with pytest.raises(ServiceError):
        await repository.get_instance(ControlPrincipal("key", "wrong-tenant", "admin-one"), "instance-test")


async def test_workspace_create_retries_do_not_duplicate_metadata(repository: Repository) -> None:
    async def create():
        return await repository.create_workspace(ADMIN, WorkspaceCreate(name="same"), "same-request", "request")

    results = await asyncio.gather(create(), create(), create())
    assert len({result.workspace_id for result in results}) == 1
    assert len({result.operation_id for result in results}) == 1
    page = await repository.list_workspaces(ADMIN, 10, 0)
    assert page.total == 1
    assert page.items[0].state == "creating"
    with pytest.raises(ServiceError) as error:
        await repository.create_workspace(ADMIN, WorkspaceCreate(name="changed"), "same-request", "request")
    assert error.value.code == "idempotency_conflict"


async def test_member_and_key_target_must_belong_to_workspace(repository: Repository) -> None:
    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    member = await repository.create_member(
        ADMIN, first.workspace_id, MemberCreate(member_name="User", iam_subject="other-user"), "create-user"
    )
    with pytest.raises(ServiceError) as error:
        await repository.create_key(ADMIN, second.workspace_id, member.member_id, key_input(), "key")
    assert error.value.status == 404
    with pytest.raises(ServiceError):
        await repository.get_workspace(OTHER, second.workspace_id)
    page = await repository.list_workspaces(OTHER, 10, 0)
    assert [item.workspace_id for item in page.items] == [first.workspace_id]


async def test_member_can_manage_own_keys_not_directory_or_other_member(repository: Repository) -> None:
    space = await ready_workspace(repository)
    member = await repository.create_member(
        ADMIN, space.workspace_id, MemberCreate(member_name="User", iam_subject="other-user"), "create-user"
    )
    key = await repository.create_key(OTHER, space.workspace_id, member.member_id, key_input(), "key")
    assert (await repository.authenticate(key.secret)).member_id == member.member_id
    with pytest.raises(ServiceError) as error:
        await repository.list_members(OTHER, space.workspace_id, 10, 0)
    assert error.value.status == 403
    with pytest.raises(ServiceError):
        await repository.create_member(OTHER, space.workspace_id, MemberCreate(member_name="Forbidden"), "create-user")


async def test_only_one_key_secret_is_returned_for_idempotent_retry(repository: Repository) -> None:
    space = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, space.workspace_id, 10, 0)).items[0]
    body = key_input()
    first = await repository.create_key(ADMIN, space.workspace_id, member.member_id, body, "key", "key-request")
    with pytest.raises(ServiceError) as error:
        await repository.create_key(ADMIN, space.workspace_id, member.member_id, body, "key", "key-request")
    assert error.value.code == "key_already_issued"
    assert first.metadata.key_id in error.value.message
    with pytest.raises(ServiceError) as conflict:
        await repository.create_key(
            ADMIN,
            space.workspace_id,
            member.member_id,
            body.model_copy(update={"name": "Different"}),
            "key",
            "key-request",
        )
    assert conflict.value.code == "idempotency_conflict"
    page = await repository.list_keys(ADMIN, space.workspace_id, member.member_id, 10, 0)
    assert page.total == 1
    assert "secret" not in page.model_dump_json()
    assert "digest" not in page.model_dump_json()


async def test_revoke_disable_and_freeze_affect_next_authentication(repository: Repository) -> None:
    space = await ready_workspace(repository)
    member = await repository.create_member(ADMIN, space.workspace_id, MemberCreate(member_name="User"), "create-user")
    key = await repository.create_key(ADMIN, space.workspace_id, member.member_id, key_input(), "key")
    assert (await repository.authenticate(key.secret)).workspace_id == space.workspace_id
    await repository.update_member(
        ADMIN, space.workspace_id, member.member_id, MemberPatch(status="disabled"), member.version, "disable"
    )
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)
    member = await repository.get_member(ADMIN, space.workspace_id, member.member_id)
    await repository.update_member(
        ADMIN, space.workspace_id, member.member_id, MemberPatch(status="active"), member.version, "enable"
    )
    await repository.update_workspace(
        ADMIN, space.workspace_id, WorkspacePatch(state="frozen"), space.version, "freeze"
    )
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)
    space = await repository.get_workspace(ADMIN, space.workspace_id)
    await repository.update_workspace(
        ADMIN, space.workspace_id, WorkspacePatch(state="active"), space.version, "unfreeze"
    )
    await repository.revoke_key(ADMIN, space.workspace_id, member.member_id, key.metadata.key_id, "revoke")
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)


async def test_concurrent_demotion_preserves_last_administrator(repository: Repository) -> None:
    space = await ready_workspace(repository)
    initial = (await repository.list_members(ADMIN, space.workspace_id, 10, 0)).items[0]
    second = await repository.create_member(
        ADMIN,
        space.workspace_id,
        MemberCreate(member_name="Admin two", role=Role.ADMIN, iam_subject="admin-two"),
        "create-admin",
    )
    principal = ControlPrincipal("control-test", "tenant-test", "admin-two")
    results = await asyncio.gather(
        repository.update_member(
            ADMIN, space.workspace_id, initial.member_id, MemberPatch(role=Role.MEMBER), initial.version, "demote-one"
        ),
        repository.update_member(
            principal, space.workspace_id, second.member_id, MemberPatch(role=Role.MEMBER), second.version, "demote-two"
        ),
        return_exceptions=True,
    )
    failures = [result for result in results if isinstance(result, ServiceError)]
    assert len(failures) == 1
    assert failures[0].code == "last_admin"
    page = await repository.list_members(
        principal if isinstance(results[1], ServiceError) else ADMIN, space.workspace_id, 10, 0
    )
    assert sum(member.role == Role.ADMIN and member.status == "active" for member in page.items) == 1


async def test_pagination_and_worker_discovery_follow_space_state(repository: Repository) -> None:
    for index in range(3):
        await ready_workspace(repository, f"space-{index}")
    first = await repository.list_workspaces(ADMIN, 2, 0)
    last = await repository.list_workspaces(ADMIN, 2, 2)
    assert first.total == last.total == 3
    assert len(first.items) == 2
    assert len(last.items) == 1
    assert not set(item.workspace_id for item in first.items) & set(item.workspace_id for item in last.items)
    assert len(await repository.worker_workspaces()) == 3
