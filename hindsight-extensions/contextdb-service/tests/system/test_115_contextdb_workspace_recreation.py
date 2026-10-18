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

from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


async def test_same_name_recreation_has_new_identity_and_no_inherited_grants(
    contextdb_deployment: ContextDBDeployment, llm
) -> None:
    base = contextdb_deployment.server.url
    name = "jiamu_" + secrets.token_hex(5)
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as management:
        created = await management.post("/workspaces", json={"name": name})
        assert created.status_code == 201, created.text
        original = created.json()
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
        all_issued = await management.post(
            f"/users/{user['user_id']}/keys",
            json={"name": "All future spaces", "authorization": {"mode": "all", "permission": "read"}},
        )
        assert all_issued.status_code == 201, all_issued.text
        all_spaces = Hindsight(base_url=base, api_key=all_issued.json()["secret"])
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
            deletion = await management.delete("/workspaces/" + name, headers={"If-Match": old_etag})
            assert deletion.status_code == 204, deletion.text
            assert (await management.get("/workspaces/" + quote(name, safe=""))).status_code == 404
            listed = next(
                item
                for item in (await management.get(f"/users/{user['user_id']}/keys")).json()["items"]
                if item["key_id"] == key["key_id"]
            )
            assert listed["authorization"] == {"mode": "selected", "workspaces": []}
            assert listed["version"] == key["version"] + 1
            stale = await management.patch(
                f"/users/{user['user_id']}/keys/{key['key_id']}",
                headers={"If-Match": f'"{key["version"]}"'},
                json={"name": "Stale edit"},
            )
            assert stale.status_code == 412
            replacement = await management.post("/workspaces", json={"name": name})
            assert replacement.status_code == 201, replacement.text
            new = replacement.json()["workspace_id"]
            assert new != old
            assert replacement.json()["bank_id"] == original["bank_id"] == name
            assert (await all_spaces.arecall(bank_id=name, query="All includes the new object")).results == []
            assert (await admin.arecall(bank_id=name, query="RecreateSentinel")).results == []
            with pytest.raises(ForbiddenException):
                await member.arecall(bank_id=name, query="Must not inherit old grants")
            current = await management.get("/workspaces/" + name)
            assert current.headers["etag"] != old_etag
            stale_delete = await management.delete(
                "/workspaces/" + name,
                headers={"If-Match": old_etag},
            )
            assert stale_delete.status_code == 412
            # Both an old delete retry and an explicit stale grant must fail;
            # the readable name now identifies a different object.
            replay = await management.delete("/workspaces/" + name, headers={"If-Match": old_etag})
            assert replay.status_code == 412
            stale_grant = await management.post(
                f"/users/{user['user_id']}/keys",
                json={
                    "name": "Stale selection",
                    "authorization": {"mode": "selected", "workspaces": [{"bank_id": name, "workspace_id": old}]},
                },
            )
            assert stale_grant.status_code == 409, stale_grant.text
            assert (await management.get("/workspaces/" + quote(name, safe=""))).json()["workspace_id"] == new
        finally:
            await member.aclose()
            await all_spaces.aclose()
            await admin.aclose()


async def test_deleted_user_name_can_be_reused_without_inheriting_old_credentials(
    contextdb_deployment: ContextDBDeployment,
) -> None:
    from hindsight_client_api.exceptions import UnauthorizedException

    deployment = contextdb_deployment
    base = deployment.server.url
    name = "Reusable app " + secrets.token_hex(5)
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
    ) as management:
        created = await management.post("/users", json={"name": name})
        assert created.status_code == 201, created.text
        original = created.json()
        issued = await management.post(
            f"/users/{original['user_id']}/keys",
            json={"name": "Old user key", "authorization": {"mode": "all", "permission": "read"}},
        )
        assert issued.status_code == 201, issued.text
        old = Hindsight(base_url=base, api_key=issued.json()["secret"])
        try:
            await old.banks.list_banks(limit=1)
            removed = await management.delete(f"/users/{original['user_id']}")
            assert removed.status_code == 204, removed.text
            with pytest.raises(UnauthorizedException):
                await old.banks.list_banks(limit=1)
            replacement = await management.post("/users", json={"name": name})
            assert replacement.status_code == 201, replacement.text
            current = replacement.json()
            assert current["user_id"] != original["user_id"]
            keys = await management.get(f"/users/{current['user_id']}/keys")
            assert keys.status_code == 200 and keys.json()["items"] == []
            with pytest.raises(UnauthorizedException):
                await old.banks.list_banks(limit=1)
        finally:
            await old.aclose()
