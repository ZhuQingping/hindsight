"""First-release authorization: one operator and one Key-owned business ACL."""

from __future__ import annotations

import asyncio

import pytest
from hindsight_ext_contextdb.__main__ import migrate, rotate
from hindsight_ext_contextdb.bootstrap import AdministratorCredential, save_credential
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    ApiKeyPatch,
    Scope,
    ServiceError,
    UserCreate,
    UserPatch,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository
from pydantic import ValidationError

from .support.identities import ADMIN, ADMIN_SECRET, admin_actor, ready_workspace


async def test_permissions_change_without_changing_secret_and_user_disable_is_live(repository):
    a, b = [await ready_workspace(repository, name) for name in ("A", "B")]
    actor = await admin_actor(repository)
    user = await repository.create_user(actor, UserCreate(name="Application"), "user")
    key = await repository.create_key(
        actor,
        user.user_id,
        ApiKeyCreate(
            name="Primary",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": a.bank_id, "permission": "read_write"},
                    {"bank_id": b.bank_id, "permission": "read_write"},
                ],
            },
        ),
        "key",
    )
    assert (await repository.authenticate(key.secret, a.bank_id)).scopes == frozenset(Scope)
    await repository.update_key(
        actor,
        user.user_id,
        key.metadata.key_id,
        ApiKeyPatch(authorization={"mode": "selected", "workspaces": [{"bank_id": a.bank_id, "permission": "read"}]}),
        1,
        "narrow",
    )
    assert (await repository.authenticate(key.secret, a.bank_id)).scopes == {
        Scope.MEMORY_READ,
        Scope.KNOWLEDGE_READ,
        Scope.REFLECT,
    }
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret, b.bank_id)
    with pytest.raises(ServiceError) as stale:
        await repository.update_key(
            actor,
            user.user_id,
            key.metadata.key_id,
            ApiKeyPatch(
                authorization={
                    "mode": "selected",
                    "workspaces": [{"bank_id": b.bank_id, "permission": "read_write"}],
                }
            ),
            1,
            "stale",
        )
    assert stale.value.status == 412
    await repository.update_user(actor, user.user_id, UserPatch(status="disabled"), 1, "disable")
    with pytest.raises(ServiceError) as disabled:
        await repository.authenticate(key.secret)
    assert disabled.value.status == 401
    await repository.update_user(actor, user.user_id, UserPatch(status="active"), 2, "restore")
    assert (await repository.authenticate(key.secret, a.bank_id)).user_id == user.user_id


async def test_all_business_key_includes_future_spaces_but_never_manages_resources(repository):
    actor = await admin_actor(repository)
    user = await repository.create_user(actor, UserCreate(name="Application"), "user")
    key = await repository.create_key(
        actor, user.user_id, ApiKeyCreate(name="All", authorization={"mode": "all", "permission": "read"}), "key"
    )
    a = await ready_workspace(repository)
    assert (await repository.authenticate(key.secret, a.bank_id)).scopes == {
        Scope.MEMORY_READ,
        Scope.KNOWLEDGE_READ,
        Scope.REFLECT,
    }
    assert (await repository.authenticate(ADMIN_SECRET, a.bank_id)).scopes == frozenset(Scope)
    with pytest.raises(ServiceError) as denied:
        await repository.authenticate_admin(key.secret)
    assert denied.value.status == 403
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.users") == 2
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.api_keys") == 2


async def test_revocation_survives_user_restore_and_deleted_user_never_restores(repository):
    actor = await admin_actor(repository)
    a = await ready_workspace(repository)
    user = await repository.create_user(actor, UserCreate(name="App"), "user")
    first = await repository.create_key(
        actor,
        user.user_id,
        ApiKeyCreate(
            name="One",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": a.bank_id, "permission": "read_write"}],
            },
        ),
        "one",
    )
    second = await repository.create_key(
        actor,
        user.user_id,
        ApiKeyCreate(
            name="Two",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": a.bank_id, "permission": "read_write"}],
            },
        ),
        "two",
    )
    await repository.revoke_key(actor, user.user_id, first.metadata.key_id, "revoke")
    await repository.update_user(actor, user.user_id, UserPatch(status="disabled"), 1, "disable")
    await repository.update_user(actor, user.user_id, UserPatch(status="active"), 2, "restore")
    with pytest.raises(ServiceError):
        await repository.authenticate(first.secret)
    assert (await repository.authenticate(second.secret)).user_id == user.user_id
    await repository.update_user(actor, user.user_id, UserPatch(status="disabled"), None, "delete", delete=True)
    with pytest.raises(ServiceError):
        await repository.authenticate(second.secret)
    with pytest.raises(ServiceError) as missing:
        await repository.update_user(actor, user.user_id, UserPatch(status="active"), 3, "restore-deleted")
    assert missing.value.status == 404


async def test_concurrent_permission_updates_have_one_winner(repository):
    actor = await admin_actor(repository)
    a = await ready_workspace(repository)
    user = await repository.create_user(actor, UserCreate(name="App"), "user")
    key = await repository.create_key(
        actor,
        user.user_id,
        ApiKeyCreate(
            name="One",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": a.bank_id, "permission": "read_write"}],
            },
        ),
        "one",
    )
    results = await asyncio.gather(
        *(
            repository.update_key(
                actor,
                user.user_id,
                key.metadata.key_id,
                ApiKeyPatch(
                    authorization={
                        "mode": "selected",
                        "workspaces": [{"bank_id": a.bank_id, "permission": p}],
                    }
                ),
                1,
                p,
            )
            for p in ("read", "read_write")
        ),
        return_exceptions=True,
    )
    assert sum((isinstance(result, ServiceError) and result.status == 412 for result in results)) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "empty"},
        {"name": "bad", "workspace_ids": ["bad"]},
        {"name": "dup", "workspace_ids": ["a" * 32, "a" * 32]},
        {"name": "all", "access_mode": "all", "workspace_ids": ["a" * 32]},
        {"name": "old", "grants": []},
        {"name": "old", "access_mode": "all", "expires_at": "2030-01-01T00:00:00Z"},
        {"name": "bad", "access_mode": "all", "permission": "admin"},
    ],
)
def test_key_authorization_rejects_ambiguous_or_legacy_payloads(payload):
    with pytest.raises(ValidationError):
        ApiKeyCreate.model_validate(payload)


async def test_authorization_targets_must_exist_and_be_ready(repository):
    actor = await admin_actor(repository)
    user = await repository.create_user(actor, UserCreate(name="App"), "user")
    operation = await repository.create_workspace(actor, WorkspaceCreate(name="Creating"), "r")
    for target in ("a" * 32, operation.workspace_id):
        with pytest.raises(ServiceError):
            await repository.create_key(
                actor,
                user.user_id,
                ApiKeyCreate(
                    name="Bad",
                    authorization={
                        "mode": "selected",
                        "workspaces": [{"bank_id": target, "permission": "read_write"}],
                    },
                ),
                "bad",
            )


def deployment_environment(repository, database_url, monkeypatch, tmp_path):
    monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", database_url)
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    path = tmp_path / "admin.json"
    save_credential(path, AdministratorCredential(key_id="a" * 32, secret=ADMIN_SECRET))
    return path


async def test_repeated_offline_initialization_preserves_one_hidden_admin(
    repository, database_url, monkeypatch, tmp_path
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    await migrate(credential_path)
    await migrate(credential_path)
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.deployment_info") == 1
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.users") == 1
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.api_keys") == 1
    await repository.verify_schema()


async def test_offline_initialization_refuses_old_experimental_version_without_writes(
    repository, database_url, monkeypatch, tmp_path
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    await repository.pool.execute(
        "ALTER TABLE ctxdb_meta.deployment_info DROP CONSTRAINT deployment_info_metadata_version_check; UPDATE ctxdb_meta.deployment_info SET metadata_version=99"
    )
    with pytest.raises(ValueError, match="Unsupported"):
        await migrate(credential_path)
    assert await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == 99


async def test_offline_initialization_and_runtime_refuse_wrong_instance_binding(
    repository, database_url, monkeypatch, tmp_path
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", "another-instance")
    with pytest.raises(RuntimeError, match="another"):
        await migrate(credential_path)
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.deployment_info") == 1


async def test_names_normalize_and_only_release_after_deletion(repository):
    await ready_workspace(repository, "ＭｙＳＱＬ")
    with pytest.raises(ServiceError) as conflict:
        await ready_workspace(repository, "mysql")
    assert conflict.value.status == 409


async def test_metadata_future_attributes_default_to_objects(repository):
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "user")
    assert (
        await repository.pool.fetchval("SELECT metadata FROM ctxdb_meta.users WHERE user_id=$1", user.user_id) == "{}"
    )


async def test_old_experimental_version_one_without_format_marker_is_never_adopted(
    repository, database_url, monkeypatch, tmp_path
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    await repository.pool.execute(
        "DROP SCHEMA ctxdb_meta CASCADE; CREATE SCHEMA ctxdb_meta; CREATE TABLE ctxdb_meta.schema_versions(version integer)"
    )
    with pytest.raises(ValueError, match="development schemas"):
        await migrate(credential_path)
    with pytest.raises(RuntimeError, match="Unsupported"):
        await repository.verify_schema()


async def test_runtime_refuses_wrong_instance_binding(repository):
    from hindsight_ext_contextdb.repository import Repository

    wrong = Repository(repository.pool, "another-instance", repository.cloud_tenant_id, repository.pepper)
    with pytest.raises(RuntimeError, match="another deployment"):
        await wrong.verify_schema()


async def test_search_filters_before_pagination_and_literal_percent_is_not_wildcard(repository):
    for name in ("Alpha", "Beta", "A%percent"):
        await ready_workspace(repository, name.replace("%", "_"))
        await repository.create_user(ADMIN, UserCreate(name=name), name)
    for listing in (repository.list_workspaces, repository.list_users):
        page = await listing(ADMIN, 1, 0, "a")
        assert page.total == 3 and len(page.items) == 1
        assert (await listing(ADMIN, 20, 0, "%")).total == (0 if listing == repository.list_workspaces else 1)
        assert (await listing(ADMIN, 20, 0, "absent")).total == 0
    user = (await repository.list_users(ADMIN, 1, 0, "Alpha")).items[0]
    for name in ("Alpha", "Beta", "A%percent"):
        await repository.create_key(ADMIN, user.user_id, ApiKeyCreate(name=name, authorization={"mode": "all"}), name)
    assert (await repository.list_keys(ADMIN, user.user_id, 1, 1, "a")).total == 3
    assert (await repository.list_keys(ADMIN, user.user_id, 20, 0, "%")).total == 1


@pytest.mark.parametrize(
    "payload", [{"access_mode": "all"}, {"permission": "read"}, {"access_mode": "all", "workspace_ids": []}]
)
def test_permission_edits_require_explicit_complete_authorization(payload):
    with pytest.raises(ValidationError):
        ApiKeyPatch.model_validate(payload)


@pytest.mark.parametrize(
    "instance_id,tenant_id", [("other-instance", "tenant-test"), ("instance-test", "other-tenant")]
)
async def test_worker_discovery_refuses_wrong_deployment_binding(
    repository: Repository, instance_id: str, tenant_id: str
) -> None:
    with pytest.raises(RuntimeError, match="another deployment"):
        await Repository.discover_workspaces(repository.pool, instance_id, tenant_id)


@pytest.mark.parametrize("command", [migrate, rotate], ids=["initialize", "rotate-admin"])
async def test_offline_commands_use_the_same_database_url_as_runtime(
    repository, database_url, monkeypatch, tmp_path, command
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    # A leftover bootstrap setting must not redirect either offline command.
    monkeypatch.setenv("CONTEXTDB_BOOTSTRAP_DATABASE_URL", "postgresql://invalid-bootstrap.invalid/wrong_database")
    await command(credential_path)
    await repository.verify_schema()
    assert (await repository.authenticate(ADMIN_SECRET)).role == "admin"


@pytest.mark.parametrize("command", [migrate, rotate], ids=["initialize", "rotate-admin"])
async def test_offline_commands_require_runtime_database_url_without_legacy_fallback(
    repository, database_url, monkeypatch, tmp_path, command
):
    credential_path = deployment_environment(repository, database_url, monkeypatch, tmp_path)
    monkeypatch.setenv("CONTEXTDB_BOOTSTRAP_DATABASE_URL", database_url)
    monkeypatch.delenv("HINDSIGHT_API_DATABASE_URL")
    with pytest.raises(ValueError, match="Set HINDSIGHT_API_DATABASE_URL"):
        await command(credential_path)
    assert await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == 1
