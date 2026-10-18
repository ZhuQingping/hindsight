"""A replica must not reuse a deleted workspace's native profile/config cache."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import cast

import pytest
from hindsight_api import MemoryEngine
from hindsight_api.config_resolver import ConfigResolver
from hindsight_api.engine import bank_info_cache
from hindsight_api.engine.bank_stats_cache import BankStatsCache, DistributedBankStatsCache
from hindsight_api.engine.memory_engine import _current_schema
from hindsight_api.engine.retain.bank_utils import get_bank_profile_if_exists
from hindsight_api.extensions import DefaultExtensionContext
from hindsight_api.models import RequestContext
from hindsight_ext_contextdb.models import Workspace, WorkspaceCreate
from hindsight_ext_contextdb.routing import bank_target
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .test_extensions import PoolHost
from .test_extensions import configured as configured
from .test_repository import ADMIN, ADMIN_SECRET, ready_workspace


async def create_native_tables(repository, workspace: Workspace, mission: str, chunk_size: int) -> None:
    schema = workspace.schema_name
    await repository.pool.execute(
        f'CREATE SCHEMA "{schema}"; '
        f'CREATE TABLE "{schema}".banks(bank_id text PRIMARY KEY,name text,disposition jsonb,mission text,config jsonb); '
        f'CREATE TABLE "{schema}".bank_stats_cache(bank_id text PRIMARY KEY,payload jsonb,computed_at timestamptz)'
    )
    await repository.pool.execute(
        f'INSERT INTO "{schema}".banks VALUES($1,$1,$2::jsonb,$3,$4::jsonb)',
        workspace.bank_id,
        json.dumps({"skepticism": 3, "literalism": 3, "empathy": 3}),
        mission,
        json.dumps({"retain_chunk_size": chunk_size}),
    )


@pytest.mark.parametrize("entry", ["http", "worker"])
@pytest.mark.parametrize("first_observation", [False, True])
async def test_same_name_successor_reads_fresh_native_profile_config_and_stats(
    repository, configured, monkeypatch, entry: str, first_observation: bool
) -> None:
    old = await ready_workspace(repository, "jiamu")
    await create_native_tables(repository, old, "generation A mission", 1111)
    # Model a long-lived API replica or independent Worker. The API performing
    # deletion can invalidate only its OWN process; this replica stays warm.
    monkeypatch.setattr(bank_info_cache, "_cache", BankStatsCache(ttl_seconds=30, max_entries=20))

    def make_tenant() -> ContextDBTenantExtension:
        extension = ContextDBTenantExtension({})
        extension.metadata_pool = repository.pool
        extension.transport_guard_installed = True
        extension.set_context(
            DefaultExtensionContext(
                "", memory_engine=cast(MemoryEngine, PoolHost(repository.pool, ContextDBOperationValidator({})))
            )
        )
        return extension

    tenant = make_tenant()
    resolver = ConfigResolver(repository.pool)
    stats = DistributedBankStatsCache(backend=repository.pool, ttl_seconds=60)

    @asynccontextmanager
    async def enter(workspace: Workspace):
        # Native tool calls create fresh RequestContexts and use authenticate;
        # queued internal contexts instead pass the whole-execution guard.
        token = _current_schema.set("outer_schema")
        try:
            if entry == "worker":
                async with tenant.async_execution_scope(
                    workspace.schema_name, workspace.bank_id, workspace.workspace_id
                ):
                    assert _current_schema.get() == "outer_schema"
                    _current_schema.set(workspace.schema_name)
                    yield
            else:
                with bank_target(workspace.bank_id):
                    context = await tenant.authenticate(RequestContext(api_key=ADMIN_SECRET))
                assert _current_schema.get() == "outer_schema"
                _current_schema.set(context.schema_name)
                yield
        finally:
            _current_schema.reset(token)

    async with enter(old):
        assert (await get_bank_profile_if_exists(repository.pool, old.bank_id))["mission"] == "generation A mission"
        assert (await resolver._load_bank_config(old.bank_id))["retain_chunk_size"] == 1111

        async def old_stats():
            return {"total_nodes": 17}

        assert (await stats.get_or_load(old.schema_name, old.bank_id, old_stats))["total_nodes"] == 17
    # Same-generation entries retain the native cache behavior.
    await repository.pool.execute(f"UPDATE \"{old.schema_name}\".banks SET mission='edited elsewhere'")
    async with enter(old):
        assert (await get_bank_profile_if_exists(repository.pool, old.bank_id))["mission"] == "generation A mission"

    await repository.delete_workspace(
        ADMIN, old.bank_id, "delete", "r", expected_id=old.workspace_id, expected_version=old.version
    )
    deletion = await repository.claim_operation()
    assert deletion is not None
    await repository.pool.execute(f'DROP SCHEMA "{old.schema_name}" CASCADE')
    await repository.complete_operation(deletion)
    creation = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "recreate", "r")
    operation = await repository.claim_operation()
    assert operation is not None
    await repository.complete_operation(operation)
    new = await repository.get_workspace(ADMIN, creation.workspace_id)
    assert new.workspace_id != old.workspace_id
    assert new.schema_name == old.schema_name and new.bank_id == old.bank_id
    await create_native_tables(repository, new, "generation B mission", 2222)
    if first_observation:
        # A newly attached Tenant instance must also invalidate an already-warm
        # native module cache; an absent identity entry is not proof of freshness.
        tenant = make_tenant()

    async with enter(new):
        assert (await get_bank_profile_if_exists(repository.pool, new.bank_id))["mission"] == "generation B mission"
        assert (await resolver._load_bank_config(new.bank_id))["retain_chunk_size"] == 2222

        async def new_stats():
            return {"total_nodes": 0}

        # PG stats use a distributed table, which physical DROP already cleared.
        assert (await stats.get_or_load(new.schema_name, new.bank_id, new_stats))["total_nodes"] == 0


async def test_generation_registry_is_bounded_and_eviction_rechecks_identity(configured, monkeypatch) -> None:
    tenant = ContextDBTenantExtension({})
    invalidated: list[str] = []

    async def invalidate(bank_id: str) -> None:
        invalidated.append(bank_id)
        await asyncio.sleep(0)

    monkeypatch.setattr(bank_info_cache, "invalidate", invalidate)
    # Concurrent first requests must serialize identity publication.
    await asyncio.gather(*(tenant._refresh_bank_generation("schema", "first", "a") for _ in range(8)))
    assert invalidated == ["first"]
    for number in range(2048):
        await tenant._refresh_bank_generation("schema", str(number), "a")
    assert len(tenant._bank_generations) == 2048
    await tenant._refresh_bank_generation("schema", "first", "a")
    assert invalidated.count("first") == 2


async def test_failed_invalidation_restores_context_and_next_request_retries(configured, monkeypatch) -> None:
    tenant = ContextDBTenantExtension({})
    attempts = 0

    async def invalidate(bank_id: str) -> None:
        nonlocal attempts
        attempts += 1
        assert _current_schema.get() == "workspace_schema"
        if attempts == 1:
            raise RuntimeError("controlled cache failure")

    monkeypatch.setattr(bank_info_cache, "invalidate", invalidate)
    token = _current_schema.set("outer_schema")
    try:
        with pytest.raises(RuntimeError, match="controlled cache failure"):
            await tenant._refresh_bank_generation("workspace_schema", "jiamu", "a")
        assert _current_schema.get() == "outer_schema"
        await tenant._refresh_bank_generation("workspace_schema", "jiamu", "a")
        assert attempts == 2 and _current_schema.get() == "outer_schema"
    finally:
        _current_schema.reset(token)
