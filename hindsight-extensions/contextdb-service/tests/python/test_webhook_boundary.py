"""Unsupported delivery jobs fail before an instance starts or upgrades."""

from typing import cast

import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import DefaultExtensionContext
from hindsight_api.models import RequestContext
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.migrations import migrate_connection
from hindsight_ext_contextdb.preflight import preflight
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.identities import ADMIN_SECRET, ready_workspace
from .support.native_doubles import PoolHost


async def test_global_webhook_rejected_without_logging_destination(monkeypatch):
    destination = "https://private-destination.example/hook?token=private"
    monkeypatch.setenv("HINDSIGHT_API_WEBHOOK_URL", destination)
    monkeypatch.delenv("HINDSIGHT_API_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="does not support HINDSIGHT_API_WEBHOOK_URL") as error:
        Settings.from_environment()
    assert destination not in str(error.value)
    report = await preflight()
    assert any(item.name == "webhooks" and item.status == "fail" for item in report.checks)
    assert destination not in report.model_dump_json()


async def test_enabled_legacy_webhook_rejected_before_start_or_migration(repository):
    workspace = await ready_workspace(repository)
    table = f'"{workspace.schema_name}".webhooks'
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    await repository.pool.execute(f"CREATE TABLE {table}(enabled boolean NOT NULL)")
    await repository.pool.execute(f"INSERT INTO {table} VALUES(true)")
    with pytest.raises(ValueError, match="Disable existing native webhooks"):
        await repository.verify_schema()
    async with repository.pool.acquire() as connection:
        with pytest.raises(ValueError, match="Disable existing native webhooks"):
            await migrate_connection(
                connection,
                repository.instance_id,
                repository.cloud_tenant_id,
                pepper=repository.pepper,
                admin_secret=ADMIN_SECRET,
            )
    await repository.pool.execute(f"UPDATE {table} SET enabled=false")
    await repository.verify_schema()


@pytest.mark.parametrize("flag", ["HINDSIGHT_API_LLM_TRACE_ENABLED", "HINDSIGHT_API_AUDIT_LOG_ENABLED"])
async def test_unfenced_native_diagnostics_rejected(flag, monkeypatch):
    monkeypatch.setenv(flag, "true")
    with pytest.raises(ValueError, match=flag + "=false"):
        Settings.from_environment()
    monkeypatch.delenv("HINDSIGHT_API_DATABASE_URL", raising=False)
    assert any(item.name == flag and item.status == "fail" for item in (await preflight()).checks)


def test_native_trace_requires_explicit_opt_out(monkeypatch):
    monkeypatch.delenv("HINDSIGHT_API_LLM_TRACE_ENABLED")
    with pytest.raises(ValueError, match="LLM_TRACE_ENABLED=false"):
        Settings.from_environment()


async def test_legacy_bank_audit_override_rejected(repository):
    workspace = await ready_workspace(repository)
    table = f'"{workspace.schema_name}".banks'
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    await repository.pool.execute(f"CREATE TABLE {table}(bank_id text,config jsonb)")
    await repository.pool.execute(f"INSERT INTO {table} VALUES($1,'{{\"audit_log_enabled\":true}}')", workspace.bank_id)
    with pytest.raises(ValueError, match="Disable existing native Bank audit"):
        await repository.verify_schema()
    await repository.pool.execute(f"UPDATE {table} SET config='{{}}'")
    await repository.verify_schema()


def test_default_template_cannot_enable_native_audit(monkeypatch):
    monkeypatch.setenv("HINDSIGHT_API_DEFAULT_BANK_TEMPLATE", '{"bank":{"audit_log_enabled":true}}')
    with pytest.raises(ValueError, match="must not enable native audit"):
        Settings.from_environment()


async def test_admin_and_internal_config_updates_cannot_enable_native_audit(repository, configured):
    workspace = await ready_workspace(repository)
    extension = ContextDBTenantExtension({})
    extension.set_context(
        DefaultExtensionContext(
            "", memory_engine=cast(MemoryEngine, PoolHost(repository.pool, ContextDBOperationValidator({})))
        )
    )
    for context in [RequestContext(internal=True), RequestContext(api_key=ADMIN_SECRET)]:
        allowed = await extension.get_allowed_config_fields(context, workspace.bank_id)
        assert allowed and "reflect_mission" in allowed
        assert "audit_log_enabled" not in allowed
