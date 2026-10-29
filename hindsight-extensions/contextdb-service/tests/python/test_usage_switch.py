"""The plugin switch stops collection and presentation without relaxing authorization."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.http import ContextDBHttpExtension
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.usage import collector_for, observe_knowledge
from hindsight_ext_contextdb.usage_repository import UsageRepository
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.http import management_client
from .support.identities import ADMIN, key_input, ready_workspace, space_user


def test_default_is_disabled(configured, monkeypatch):
    monkeypatch.delenv("CONTEXTDB_RECALL_USAGE_ENABLED")
    assert Settings.from_environment().recall_usage_enabled is False


@pytest.mark.parametrize("value", ["", "1", "0", "TRUE", "False", "yes", " true "])
def test_invalid_switch_is_rejected(configured, monkeypatch, value):
    monkeypatch.setenv("CONTEXTDB_RECALL_USAGE_ENABLED", value)
    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_environment()


@pytest.mark.parametrize("enabled", [True, False])
async def test_collector_lifecycle_is_owned_by_enabled_http_extension(repository, configured, monkeypatch, enabled):
    monkeypatch.setenv("CONTEXTDB_RECALL_USAGE_ENABLED", str(enabled).lower())
    extension = ContextDBHttpExtension({})
    engine = SimpleNamespace(
        tenant_extension=Mock(spec=ContextDBTenantExtension),
        _operation_validator=Mock(spec=ContextDBOperationValidator),
        _get_pool=AsyncMock(return_value=repository.pool),
    )
    extension.memory = engine
    await extension.on_startup()
    collector = collector_for(engine)
    try:
        assert (collector is not None) == enabled
        if collector is not None:
            task = collector.task
            await extension.on_startup()
            assert collector_for(engine).task is task
    finally:
        await extension.on_shutdown()
    assert collector_for(engine) is None
    if collector is not None:
        assert collector.closed and collector.task.done()


async def test_disabled_capability_and_usage_keep_auth_without_storage_read(repository, configured, monkeypatch):
    monkeypatch.setenv("CONTEXTDB_RECALL_USAGE_ENABLED", "false")
    read = AsyncMock(side_effect=AssertionError("Disabled usage must not query storage"))
    monkeypatch.setattr(UsageRepository, "read", read)
    workspace = await ready_workspace(repository)
    user = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(ADMIN, user.user_id, key_input(workspace.bank_id), "key")
    async with management_client(repository) as management:
        identity = await management.client.get("admin/identity", headers=management.admin_headers)
        assert identity.status_code == 200
        assert identity.json()["capabilities"] == {"recall_usage": False}
        path = f"workspaces/{workspace.bank_id}/usage?object_type=knowledge_page&ids=page"
        off = await management.client.get(path, headers=management.admin_headers)
        assert off.status_code == 404 and off.json()["code"] == "usage_disabled"
        assert (await management.client.get(path)).status_code == 401
        response = await management.client.get(path, headers={"Authorization": "Bearer " + key.secret})
        assert response.status_code == 404 and response.json()["code"] == "usage_disabled"
    read.assert_not_awaited()


async def test_disabled_knowledge_observer_preserves_original_scope_and_bytes():
    scope = {"headers": [(b"accept-encoding", b"gzip")]}
    sent = []

    async def app(actual, receive, send):
        assert actual is scope
        await send({"type": "http.response.body", "body": b"compressed-original"})

    async def send(message):
        sent.append(message)

    await observe_knowledge(app, scope, AsyncMock(), send, None)
    assert sent == [{"type": "http.response.body", "body": b"compressed-original"}]
