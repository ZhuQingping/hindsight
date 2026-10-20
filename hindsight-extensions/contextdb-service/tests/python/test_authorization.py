"""Request snapshots and native internal contexts need no execution barrier."""

import asyncio
from dataclasses import replace

import pytest
from hindsight_api.engine.memory_engine import _current_schema
from hindsight_api.models import RequestContext
from hindsight_ext_contextdb.authorization import (
    authenticated_principal,
    authenticated_request,
    management_call,
    workspace_management,
)
from hindsight_ext_contextdb.models import WorkspaceCreate

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace


async def test_target_snapshot_is_scoped_to_credential_deployment_bank_and_request(repository, configured):
    workspace = await ready_workspace(repository)
    principal = await repository.authenticate(ADMIN_SECRET, workspace.bank_id)

    def lookup(credential=ADMIN_SECRET, bank=workspace.bank_id, instance=None, tenant=None, pepper=None):
        return authenticated_principal(
            credential,
            bank,
            instance or configured.instance_id,
            tenant or configured.cloud_tenant_id,
            pepper or configured.pepper,
        )

    assert lookup() is None
    with authenticated_request(ADMIN_SECRET, principal, workspace.bank_id, configured):
        assert lookup() is principal
        assert lookup(credential=ADMIN_SECRET + "x") is None
        assert lookup(bank="other") is None
        assert lookup(bank=None) is None
        assert lookup(instance="other") is None
        assert lookup(tenant="other") is None
        assert lookup(pepper="different-long-enough-synthetic-pepper") is None
    assert lookup() is None


async def test_inherited_authentication_snapshot_expires_without_tracking_child_tasks(repository, configured):
    workspace = await ready_workspace(repository)
    principal = await repository.authenticate(ADMIN_SECRET, workspace.bank_id)
    release = asyncio.Event()

    async def inherited():
        await release.wait()
        return authenticated_principal(
            ADMIN_SECRET, workspace.bank_id, configured.instance_id, configured.cloud_tenant_id, configured.pepper
        )

    with authenticated_request(ADMIN_SECRET, principal, workspace.bank_id, configured):
        child = asyncio.create_task(inherited())
    release.set()
    assert await child is None


@pytest.mark.parametrize("action", ["create_workspace", "delete_workspace"])
async def test_management_authority_matches_exact_context_task_bank_schema_and_identity(repository, action):
    workspace = await repository.create_workspace(ADMIN, WorkspaceCreate(name="trusted"), "create")
    previous_schema = _current_schema.get()
    with workspace_management(workspace, action) as context:
        assert _current_schema.get() == workspace.schema_name
        call = management_call(context, workspace.bank_id, workspace.schema_name)
        assert call is not None and call.action == action
        assert management_call(replace(context), workspace.bank_id, workspace.schema_name) is None
        assert management_call(context, "other", workspace.schema_name) is None
        assert management_call(context, workspace.bank_id, "other") is None
        forged = RequestContext(
            internal=True, tenant_id=workspace.workspace_id, extra_headers={"ctxdb-internal-purpose": action}
        )
        assert management_call(forged, workspace.bank_id, workspace.schema_name) is None

        async def child():
            return management_call(context, workspace.bank_id, workspace.schema_name)

        assert await asyncio.create_task(child()) is None
    assert _current_schema.get() == previous_schema
    assert management_call(context, workspace.bank_id, workspace.schema_name) is None


async def test_management_context_resets_schema_after_failure(repository):
    workspace = await repository.create_workspace(ADMIN, WorkspaceCreate(name="failure"), "create")
    token = _current_schema.set("previous_schema")
    try:
        with pytest.raises(RuntimeError, match="synthetic"):
            with workspace_management(workspace, "create_workspace") as context:
                raise RuntimeError("synthetic")
        assert _current_schema.get() == "previous_schema"
        assert management_call(context, workspace.bank_id, workspace.schema_name) is None
    finally:
        _current_schema.reset(token)
