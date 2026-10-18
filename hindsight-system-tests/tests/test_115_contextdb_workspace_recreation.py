"""Deletion, same-name recreation and a stale Key never reconnect old memory.

The real API and both Worker modes run against fixture-owned PG. Management
provisioning uses the optional REST contract; all memory assertions use the SDK.
"""

from __future__ import annotations

import secrets
from urllib.parse import quote

import httpx
import pytest
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException

from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import ContextDBDeployment
from .test_110_contextdb_tenant_admin import operation_done

contextdb_deployment = service_story.contextdb_deployment
pytestmark = pytest.mark.asyncio


async def test_same_name_recreation_has_new_identity_and_no_inherited_grants(
    contextdb_deployment: ContextDBDeployment, llm
) -> None:
    base = contextdb_deployment.server.url
    name = "jiamu_" + secrets.token_hex(5)
    create_key, delete_key = secrets.token_hex(12), secrets.token_hex(12)
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as management:
        created = await management.post("/workspaces", json={"name": name}, headers={"Idempotency-Key": create_key})
        assert created.status_code == 202, created.text
        original = created.json()
        await operation_done(management, original)
        old = original["workspace_id"]
        detail = await management.get("/workspaces/" + quote(name, safe=""))
        assert detail.status_code == 200 and detail.json()["workspace_id"] == old
        assert detail.json()["bank_id"] == name
        old_etag = detail.headers["etag"]
        assert (await management.get("/workspaces/" + old)).status_code == 404
        user_name = "App " + secrets.token_hex(5)
        user = (await management.post("/users", json={"name": user_name})).json()
        assert (await management.post("/users", json={"name": user_name.upper()})).status_code == 409
        issued = await management.post(
            f"/users/{user['user_id']}/keys",
            json={
                "name": "Selected",
                "authorization": {"mode": "selected", "workspaces": [{"bank_id": name, "workspace_id": old}]},
            },
        )
        assert issued.status_code == 201, issued.text
        key = issued.json()
        assert key["authorization"]["workspaces"][0]["workspace_name"] == name
        member = Hindsight(base_url=base, api_key=key["secret"])
        admin = Hindsight(base_url=base, api_key=contextdb_deployment.headers["Authorization"].removeprefix("Bearer "))
        try:
            llm.on_step("extract_facts", contains="RecreateSentinel").returns(
                extracted(fact("Alice builds RecreateSentinel", who="Alice", entities=["Alice", "RecreateSentinel"]))
            )
            llm.on_step("consolidate").returns(consolidation())
            await member.aretain(bank_id=name, content="Alice builds RecreateSentinel.", retain_async=True)
            await wait_until_settled(member, name)
            assert (await member.arecall(bank_id=name, query="RecreateSentinel")).results
            deletion = await management.delete(
                "/workspaces/" + name, headers={"Idempotency-Key": delete_key, "If-Match": old_etag}
            )
            assert deletion.status_code == 202, deletion.text
            await operation_done(management, deletion.json())
            assert (await management.get("/workspaces/" + quote(name, safe=""))).status_code == 404
            listed = (await management.get(f"/users/{user['user_id']}/keys")).json()["items"][0]
            assert listed["authorization"] == {"mode": "selected", "workspaces": []}
            assert listed["version"] == key["version"] + 1
            stale = await management.patch(
                f"/users/{user['user_id']}/keys/{key['key_id']}",
                headers={"If-Match": f'"{key["version"]}"'},
                json={"name": "Stale edit"},
            )
            assert stale.status_code == 412
            replacement = await management.post(
                "/workspaces", json={"name": name}, headers={"Idempotency-Key": secrets.token_hex(12)}
            )
            assert replacement.status_code == 202, replacement.text
            await operation_done(management, replacement.json())
            new = replacement.json()["workspace_id"]
            assert new != old
            assert (await admin.arecall(bank_id=name, query="RecreateSentinel")).results == []
            with pytest.raises(ForbiddenException):
                await member.arecall(bank_id=name, query="Must not inherit old grants")
            current = await management.get("/workspaces/" + name)
            assert current.headers["etag"] != old_etag
            stale_delete = await management.delete(
                "/workspaces/" + name,
                headers={"Idempotency-Key": secrets.token_hex(12), "If-Match": old_etag},
            )
            assert stale_delete.status_code == 412
            replay = await management.delete(
                "/workspaces/" + name, headers={"Idempotency-Key": delete_key, "If-Match": old_etag}
            )
            assert replay.json()["operation_id"] == deletion.json()["operation_id"]
            assert replay.json()["state"] == "succeeded"
            assert (await management.get("/workspaces/" + quote(name, safe=""))).json()["workspace_id"] == new
        finally:
            await member.aclose()
            await admin.aclose()
