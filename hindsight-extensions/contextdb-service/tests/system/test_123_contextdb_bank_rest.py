"""Real REST/SDK prototype on disposable PG and random API/Worker ports."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
from contextlib import aclosing

import aiohttp
import asyncpg
import httpx
import pytest
from contextbase_client import ContextBase
from contextbase_client_api.exceptions import ApiException
from hindsight_system_tests.server import start_hindsight_server

from ..paths import EXTENSION, ROOT
from ..python.support.metadata import postgres_owner
from .support.deployment import ContextDBDeployment


@pytest.fixture(scope="module")
def typescript_probe(tmp_path_factory):
    output = tmp_path_factory.mktemp("bank-sdk") / "probe.cjs"
    subprocess.run(
        [
            str(ROOT / "node_modules/.bin/esbuild"),
            str(EXTENSION / "tests/contracts/bank-sdk-probe.ts"),
            "--bundle",
            "--platform=node",
            "--format=cjs",
            '--define:__CLIENT_VERSION__="1.0.0"',
            f"--outfile={output}",
        ],
        check=True,
        capture_output=True,
    )
    return output


async def run_typescript(probe, base: str, key: str, *, plugin: bool) -> None:
    process = await asyncio.create_subprocess_exec(
        "node",
        str(probe),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, error = await process.communicate(
        json.dumps({"base": base, "key": key, "bank": "ts_" + secrets.token_hex(5), "plugin": plugin}).encode()
    )
    assert process.returncode == 0, error.decode()
    assert b"verified" in out


@pytest.mark.asyncio
async def test_python_and_typescript_sdk_contract(contextdb_deployment: ContextDBDeployment, typescript_probe):
    deployment = contextdb_deployment
    base = deployment.server.url
    key = deployment.headers["Authorization"].split(" ", 1)[1]
    bank = "sdk_" + secrets.token_hex(5)
    log_offset = len(deployment.server.log_path.read_text())
    async with (
        aclosing(ContextBase(base_url=base, api_key=key)) as sdk,
        httpx.AsyncClient(base_url=base, headers=deployment.headers, timeout=100) as raw,
    ):
        created = await sdk.acreate_bank(bank, name="SDK label", mission="SDK mission")
        assert created.bank_id == bank and created.name == "SDK label"
        again = await sdk.acreate_bank(bank, name="Updated SDK label")
        assert again.name == "Updated SDK label"
        specification = (await raw.get("/openapi.json")).json()
        operations = specification["paths"]["/v1/default/banks/{bank_id}"]
        assert any(p["name"] == "If-None-Match" for p in operations["put"]["parameters"])
        assert any(p["name"] == "If-Match" and p["required"] for p in operations["delete"]["parameters"])
        detail = await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")
        identity = detail.json()["workspace_id"]
        conflict = await raw.put(f"/v1/default/banks/{bank}", json={}, headers={"If-None-Match": "*"})
        assert conflict.status_code == 412
        with pytest.raises(ApiException) as denied:
            await sdk.adelete_bank(bank)
        assert denied.value.status == 428
        removed = await sdk._banks_api.delete_bank(bank, _headers={"If-Match": detail.headers["etag"]})
        assert removed.success
        assert (await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")).status_code == 404
        assert (await raw.put(f"/v1/default/banks/{bank}", json={})).status_code == 200
        new = await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")
        assert new.json()["workspace_id"] != identity
        assert (
            await raw.delete(f"/v1/default/banks/{bank}", headers={"If-Match": detail.headers["etag"]})
        ).status_code == 412
        assert (
            await raw.delete(f"/v1/default/banks/{bank}", headers={"If-Match": new.headers["etag"]})
        ).status_code == 200
    await run_typescript(typescript_probe, base, key, plugin=True)
    # Use the real server/logger and its fresh library without public tables,
    # rather than a mocked should_log which hides a wrong-schema lookup.
    log = deployment.server.log_path.read_text()[log_offset:]
    assert "Failed to load bank config" not in log
    assert 'relation "public.banks" does not exist' not in log


@pytest.mark.asyncio
async def test_conditions_concurrency_description_and_missing_bank(contextdb_deployment: ContextDBDeployment):
    deployment = contextdb_deployment
    bank = "conditional_" + secrets.token_hex(5)
    path = f"/v1/default/banks/{bank}"
    async with httpx.AsyncClient(base_url=deployment.server.url, headers=deployment.headers, timeout=100) as raw:
        results = await asyncio.gather(
            *(raw.put(path, json={"name": "Atomic label"}, headers={"If-None-Match": "*"}) for _ in range(2))
        )
        assert sorted(r.status_code for r in results) == [200, 412]
        assert (await raw.patch(path, json={"name": "New display"})).json()["name"] == "New display"
        legacy = await raw.post(
            "/ext/contextdb/v1/workspaces", json={"name": "desc_" + bank, "description": "Keep existing ability"}
        )
        assert legacy.status_code == 201 and legacy.json()["description"] == "Keep existing ability"
        assert (await raw.delete(path)).status_code == 428
        detail = await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")
        # Deliberately corrupt only this fixture's Bank row to prove update-only
        # behavior. Metadata identity assertions still use the management API.
        conn = await asyncpg.connect(deployment.database_url)
        try:
            await conn.execute(f'DELETE FROM "ctxdb_ws_{bank}".banks WHERE bank_id=$1', bank)
        finally:
            await conn.close()
        for method in (raw.put, raw.patch):
            response = await method(path, json={"name": "Must not resurrect"})
            assert response.status_code == 404, response.text
        current = await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")
        assert current.json()["workspace_id"] == detail.json()["workspace_id"]
        removed = await raw.delete(path, headers={"If-Match": current.headers["etag"]})
        assert removed.status_code == 200 and removed.json()["deleted_count"] == 0


@pytest.fixture(scope="module")
def native_bank_server(stub_server, tmp_path_factory):
    root = tmp_path_factory.mktemp("native-bank-control")
    with postgres_owner(root / "pg") as database_url:
        server = start_hindsight_server(
            stub_url=stub_server.url,
            log_path=root / "native.log",
            database_url=database_url,
            python_executable=sys.executable,
            extra_env={
                "PYTHON_DOTENV_DISABLED": "1",
                "PYTHONPATH": os.pathsep.join([str(ROOT / "hindsight-api-slim")]),
                "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
                "HINDSIGHT_API_AUDIT_LOG_ENABLED": "false",
            },
        )
        try:
            yield server
        finally:
            server.stop()


@pytest.mark.asyncio
async def test_without_plugin_preserves_native_bank_contract(native_bank_server, typescript_probe):
    base = native_bank_server.url
    bank = "native_" + secrets.token_hex(5)
    async with aclosing(ContextBase(base_url=base)) as sdk, httpx.AsyncClient(base_url=base, timeout=100) as raw:
        assert (await sdk.acreate_bank(bank, name="Native label")).name == "Native label"
        assert (await raw.patch(f"/v1/default/banks/{bank}", json={"name": "Native update"})).status_code == 200
        conditional = await raw.put(
            f"/v1/default/banks/{bank}", json={"name": "Native conditional upsert"}, headers={"If-None-Match": "*"}
        )
        assert conditional.status_code == 200 and conditional.json()["name"] == "Native conditional upsert"
        operations = (await raw.get("/openapi.json")).json()["paths"]["/v1/default/banks/{bank_id}"]
        for method in ("put", "delete"):
            assert not any(p["name"] in {"If-Match", "If-None-Match"} for p in operations[method].get("parameters", []))
        # No plugin-only deletion condition, metadata table or extension API.
        await sdk.adelete_bank(bank)
        assert (await raw.get("/ext/contextdb/v1/workspaces")).status_code == 404
    await run_typescript(typescript_probe, base, "", plugin=False)


@pytest.mark.asyncio
async def test_invalid_sdk_configuration_does_not_reserve_workspace(contextdb_deployment: ContextDBDeployment):
    deployment = contextdb_deployment
    key = deployment.headers["Authorization"].split(" ", 1)[1]
    async with (
        aclosing(ContextBase(base_url=deployment.server.url, api_key=key)) as sdk,
        httpx.AsyncClient(base_url=deployment.server.url, headers=deployment.headers, timeout=100) as raw,
    ):
        for field in ("retain_chunk_size", "retain_structured_chunk_size"):
            bank = "invalid_" + secrets.token_hex(5)
            # The high-level create method uses aiohttp, unlike generated delete.
            with pytest.raises(aiohttp.ClientResponseError) as rejected:
                await sdk.acreate_bank(bank, **{field: 0})
            assert rejected.value.status == 400
            assert (await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")).status_code == 404
            # Only a direct namespace query can prove the absence of DDL effects.
            connection = await asyncpg.connect(deployment.database_url)
            try:
                assert await connection.fetchval("SELECT to_regnamespace($1)", f"ctxdb_ws_{bank}") is None
            finally:
                await connection.close()
            created = await sdk.acreate_bank(bank, **{field: 1000})
            assert created.bank_id == bank
            config = await sdk.aget_bank_config(bank)
            assert config["overrides"][field] == 1000
            detail = await raw.get(f"/ext/contextdb/v1/workspaces/{bank}")
            removed = await raw.delete(f"/v1/default/banks/{bank}", headers={"If-Match": detail.headers["etag"]})
            assert removed.status_code == 200
