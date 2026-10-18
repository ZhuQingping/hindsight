"""Real native lifecycle work can precede a failed metadata commit.

Only inject infrastructure faults through SQL on this fixture-owned PG. All
observable resource, grant and memory assertions go through management HTTP/SDK.
"""

from __future__ import annotations

import secrets
from contextlib import AsyncExitStack

import asyncpg
import httpx
import pytest
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException

from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("phase", ["activate", "delete_finalize"])
async def test_partial_lifecycle_failure_is_observable_and_explicitly_recoverable(
    contextdb_deployment: ContextDBDeployment, phase: str
) -> None:
    deployment = contextdb_deployment
    token = secrets.token_hex(6)
    bank = "fault_" + token
    trigger = "quality_fault_" + token
    table = "workspaces" if phase == "activate" else "audit_events"
    async with (
        AsyncExitStack() as resources,
        httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
        ) as management,
    ):
        connection = await asyncpg.connect(deployment.database_url)
        resources.push_async_callback(connection.close)
        user = await management.post("/users", json={"name": "Lifecycle fault " + token})
        assert user.status_code == 201
        user_id = user.json()["user_id"]
        issued = await management.post(
            f"/users/{user_id}/keys",
            json={"name": "All reader", "authorization": {"mode": "all", "permission": "read"}},
        )
        assert issued.status_code == 201
        reader = Hindsight(base_url=deployment.server.url, api_key=issued.json()["secret"])
        resources.push_async_callback(reader.aclose)
        selected = None
        selected_key = None
        original = None
        if phase == "delete_finalize":
            created = await management.post("/workspaces", json={"name": bank})
            assert created.status_code == 201
            original = created.json()
            issued = await management.post(
                f"/users/{user_id}/keys",
                json={
                    "name": "Selected reader",
                    "authorization": {"mode": "selected", "workspaces": [{"bank_id": bank, "permission": "read"}]},
                },
            )
            assert issued.status_code == 201
            selected_key = issued.json()
            selected = Hindsight(base_url=deployment.server.url, api_key=selected_key["secret"])
            resources.push_async_callback(selected.aclose)
            assert (await selected.arecall(bank, "Before failed deletion")).results == []
        # A trigger is needed to place a fault AFTER native work, at the commit
        # seam a client-side disconnect or mocked engine cannot exercise.
        condition = (
            f"NEW.bank_id='{bank}' AND NEW.state='active'"
            if phase == "activate"
            else f"NEW.action='delete_workspace' AND NEW.workspace_id='{original['workspace_id']}'"
        )
        event = "UPDATE" if phase == "activate" else "INSERT"
        try:
            await connection.execute(
                f"CREATE FUNCTION ctxdb_meta.\"{trigger}\"() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'synthetic-private-lifecycle-fault'; END; $$"
            )
            await connection.execute(
                f'CREATE TRIGGER "{trigger}" BEFORE {event} ON ctxdb_meta.{table} FOR EACH ROW WHEN ({condition}) EXECUTE FUNCTION ctxdb_meta."{trigger}"()'
            )
            if phase == "activate":
                failed = await management.post("/workspaces", json={"name": bank})
            else:
                failed = await management.delete("/workspaces/" + bank, headers={"If-Match": original["etag"]})
            assert failed.status_code == 503, failed.text
            assert failed.json()["code"] == "metadata_unavailable"
            assert "synthetic-private-lifecycle-fault" not in failed.text
            detail = await management.get("/workspaces/" + bank)
            assert detail.status_code == 200
            failed_resource = detail.json()
            assert failed_resource["state"] == "failed"
            assert failed_resource["bank_id"] == bank
            if original:
                assert failed_resource["workspace_id"] == original["workspace_id"]
                assert detail.headers["etag"] != original["etag"]
                assert (
                    await management.delete("/workspaces/" + bank, headers={"If-Match": original["etag"]})
                ).status_code == 412
            assert (await management.post("/workspaces", json={"name": bank})).status_code == 409
            with pytest.raises(ForbiddenException):
                await reader.arecall(bank, "A failed workspace is not accessible")
            if selected is not None:
                with pytest.raises(ForbiddenException):
                    await selected.arecall(bank, "Failed deletion is not business access")
                records = (await management.get(f"/users/{user_id}/keys")).json()["items"]
                remaining = next(key for key in records if key["key_id"] == selected_key["key_id"])
                assert remaining["version"] == selected_key["version"]
                assert remaining["authorization"] == selected_key["authorization"]
        finally:
            await connection.execute(f'DROP TRIGGER IF EXISTS "{trigger}" ON ctxdb_meta.{table}')
            await connection.execute(f'DROP FUNCTION IF EXISTS ctxdb_meta."{trigger}"()')
        # Recovery is an explicit new request with the observed failed identity,
        # not automatic replay or a claim that earlier native work rolled back.
        removed = await management.delete("/workspaces/" + bank, headers={"If-Match": detail.headers["etag"]})
        assert removed.status_code == 204, removed.text
        assert (await management.get("/workspaces/" + bank)).status_code == 404
        replacement = await management.post("/workspaces", json={"name": bank})
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["workspace_id"] != failed_resource["workspace_id"]
        assert (await reader.arecall(bank, "All access includes a fresh empty successor")).results == []
        if selected_key is not None:
            old = Hindsight(base_url=deployment.server.url, api_key=selected_key["secret"])
            try:
                with pytest.raises(ForbiddenException):
                    await old.arecall(bank, "A successor must not inherit selected grants")
            finally:
                await old.aclose()
