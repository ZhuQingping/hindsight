"""Readable native Bank addresses keep immutable authorization/lifecycle identity."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import ExtensionContext
from hindsight_ext_contextdb.lifecycle import Lifecycle
from hindsight_ext_contextdb.models import ApiKeyCreate, ApiKeyPatch, ServiceError, UserCreate, WorkspaceCreate
from hindsight_ext_contextdb.repository import Repository
from pydantic import ValidationError

from .test_http import management as management
from .test_repository import ADMIN, ready_workspace


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
        repository.create_workspace(ADMIN, WorkspaceCreate(name="MySQL"), "one", "r1"),
        repository.create_workspace(ADMIN, WorkspaceCreate(name="mysql"), "two", "r2"),
        return_exceptions=True,
    )
    assert len([item for item in results if isinstance(item, ServiceError) and item.status == 409]) == 1
    assert (await repository.list_workspaces(ADMIN, 10, 0)).total == 1


async def test_unregistered_schema_is_never_adopted(repository: Repository) -> None:
    await repository.pool.execute("CREATE SCHEMA ctxdb_ws_foreign")
    with pytest.raises(ServiceError) as error:
        await repository.create_workspace(ADMIN, WorkspaceCreate(name="foreign"), "create", "r")
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
    deleted = await repository.delete_workspace(
        ADMIN, old.bank_id, "delete-old", "r", expected_id=old.workspace_id, expected_version=old.version
    )
    claimed = await repository.claim_operation()
    assert claimed is not None
    await repository.complete_operation(claimed)
    # The create idempotency scope also deliberately preserves old results.
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "new-generation", "new")
    claimed = await repository.claim_operation()
    assert claimed is not None
    await repository.complete_operation(claimed)
    successor = await repository.get_workspace(ADMIN, created.workspace_id)
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
    replay = await repository.delete_workspace(
        ADMIN, "jiamu", "delete-old", "lost-response", expected_id=old.workspace_id, expected_version=old.version
    )
    assert replay.operation_id == deleted.operation_id
    for key in ["new-stale-request", "delete-old"]:
        if key == "delete-old":
            await repository.pool.execute(
                "UPDATE ctxdb_meta.management_operations SET updated_at=now()-interval '8 days' WHERE operation_id=$1",
                deleted.operation_id,
            )
            assert await repository.prune_operations() == 1
        with pytest.raises(ServiceError) as stale_delete:
            await repository.delete_workspace(
                ADMIN, "jiamu", key, "stale", expected_id=old.workspace_id, expected_version=old.version
            )
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
    assert response.status_code == 202
    operation = await repository.claim_operation()
    assert operation is not None
    await repository.complete_operation(operation)
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "new", "new")
    operation = await repository.claim_operation()
    assert operation is not None
    await repository.complete_operation(operation)
    assert (
        await client.delete("/workspaces/jiamu", headers={**request_headers, "If-Match": old.etag})
    ).status_code == 202
    stale = await client.delete(
        "/workspaces/jiamu", headers={**request_headers, "Idempotency-Key": "stale-new", "If-Match": old.etag}
    )
    assert stale.status_code == 412
    assert (await client.get("/workspaces/jiamu", headers=headers)).json()["state"] == "active"


async def test_old_migration_thread_blocks_schema_reuse_after_lease_replacement(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "old", "r")
    original = await repository.claim_operation()
    assert original is not None
    entered, release = asyncio.Event(), asyncio.Event()

    async def migrate(schema: str) -> None:
        entered.set()
        await release.wait()
        await repository.pool.execute(f'CREATE SCHEMA "{schema}"')

    context = Mock(spec=ExtensionContext)
    context.run_migration = AsyncMock(side_effect=migrate)
    memory = Mock(spec=MemoryEngine)
    memory.update_bank = AsyncMock()
    memory.get_bank_profile = AsyncMock(return_value=None)
    memory._file_storage = Mock()
    memory._file_storage.delete_prefix = AsyncMock()
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    old_executor = asyncio.create_task(lifecycle._apply(original))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await repository.pool.execute(
            "UPDATE ctxdb_meta.management_operations SET lease_until=now()-interval '1 second' WHERE operation_id=$1",
            original.operation_id,
        )
        replacement = await repository.claim_operation()
        assert replacement is not None
        await repository.complete_operation(replacement, error_code="operator_cancelled_create")
        failed = await repository.get_workspace(ADMIN, created.workspace_id)
        await repository.delete_workspace(
            ADMIN, "jiamu", "delete", "r", expected_id=failed.workspace_id, expected_version=failed.version
        )
        deletion = await repository.claim_operation()
        assert deletion is not None
        assert await lifecycle._apply(deletion) is False
        assert await repository.has_outstanding_admissions(failed.workspace_id)
        with pytest.raises(ServiceError):
            await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "premature", "r")
        release.set()
        with pytest.raises(ServiceError) as stale:
            await asyncio.wait_for(old_executor, 5)
        assert stale.value.code == "lease_lost"
        memory.update_bank.assert_not_called()
        assert not await repository.has_outstanding_admissions(failed.workspace_id)
        assert await lifecycle._apply(deletion) is True
        await repository.complete_operation(deletion)
        assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_jiamu')") is None
        fresh = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "fresh", "r")
        assert fresh.workspace_id != failed.workspace_id
    finally:
        release.set()
        if not old_executor.done():
            old_executor.cancel()
        await asyncio.gather(old_executor, return_exceptions=True)


async def test_grant_expectation_rejects_same_name_successor_for_new_and_existing_key(repository: Repository) -> None:
    old = await ready_workspace(repository, "jiamu")
    user = await repository.create_user(ADMIN, UserCreate(name="application"), "u")
    unaffected = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="existing", authorization={"mode": "all"}), "k"
    )
    await repository.delete_workspace(
        ADMIN, "jiamu", "delete", "d", expected_id=old.workspace_id, expected_version=old.version
    )
    deletion = await repository.claim_operation()
    assert deletion is not None
    await repository.complete_operation(deletion)
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "successor", "r")
    creation = await repository.claim_operation()
    assert creation is not None
    await repository.complete_operation(creation)
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
