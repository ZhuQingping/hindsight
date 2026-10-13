"""A dynamically issued member Key works through the published memory client.

Management calls below belong to fixture provisioning, because the upstream SDK
does not expose optional extension APIs. Memory assertions and background waiting
go exclusively through the published Hindsight client, never SQL or an engine.
The deployment has a unique PG instance and leaves the developer's runtime alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg
import httpx
import pytest
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException, UnauthorizedException
from pg0 import Pg0

from hindsight_system_tests import reflect_loop
from hindsight_system_tests.payloads import consolidation, extracted, fact
from hindsight_system_tests.server import HindsightServer, free_port, start_hindsight_server, stub_environment
from hindsight_system_tests.waiting import wait_until_settled

ROOT = Path(__file__).resolve().parents[2]
EXTENSION = ROOT / "hindsight-extensions" / "contextdb-service"


@dataclass
class ContextDBDeployment:
    server: HindsightServer
    headers: dict[str, str] = field(repr=False)
    database_url: str = field(default="", repr=False)


@dataclass
class MemberClients:
    own: Hindsight
    same_bank: Hindsight
    other_bank: Hindsight
    read_only: Hindsight
    knowledge_only: Hindsight
    bank_id: str
    other_bank_id: str
    own_key: str = field(repr=False)


@pytest.fixture(scope="session", params=["embedded-worker", "standalone-worker"])
def contextdb_deployment(
    request: pytest.FixtureRequest, stub_server, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[ContextDBDeployment]:
    root = tmp_path_factory.mktemp("contextdb-blackbox")
    name = f"ctxdb-story-{secrets.token_hex(6)}"
    pg = Pg0(name=name, port=free_port(), data_dir=str(root / "pg"), database="contextdb_story")

    async def bootstrap() -> None:
        conn = await asyncpg.connect(info.uri)
        try:
            await conn.execute((EXTENSION / "hindsight_ext_contextdb" / "schema.sql").read_text())
        finally:
            await conn.close()

    key_id = secrets.token_hex(16)
    secret = f"ctx_ctrl_{key_id}_{secrets.token_urlsafe(32)}"
    server = None
    worker = None
    worker_log = None
    settings = {
        "PYTHONPATH": str(EXTENSION),
        "CONTEXTDB_INSTANCE_ID": "story-instance",
        "CONTEXTDB_CLOUD_TENANT_ID": "story-tenant",
        "CONTEXTDB_KEY_PEPPER": "synthetic-story-pepper-32-bytes-long",
        "CONTEXTDB_CONTROL_KEYS": json.dumps(
            [{"key_id": key_id, "sha256": hashlib.sha256(secret.encode()).hexdigest()}]
        ),
        "HINDSIGHT_API_TENANT_EXTENSION": "hindsight_ext_contextdb.tenant:ContextDBTenantExtension",
        "HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION": "hindsight_ext_contextdb.validator:ContextDBOperationValidator",
        "HINDSIGHT_API_HTTP_EXTENSION": "hindsight_ext_contextdb.http:ContextDBHttpExtension",
        "HINDSIGHT_API_MCP_ENABLED": "true",
        "HINDSIGHT_API_WORKER_ENABLED": "true" if request.param == "embedded-worker" else "false",
    }
    template = getattr(request, "contextdb_default_template", None)
    if template is not None:
        settings["HINDSIGHT_API_DEFAULT_BANK_TEMPLATE"] = json.dumps(template)
    try:
        # Establish cleanup ownership before starting PG or running bootstrap.
        # A failed migration must not leave this test's database process running.
        info = pg.start()
        assert info.uri is not None
        asyncio.run(bootstrap())
        server = start_hindsight_server(
            stub_url=stub_server.url,
            log_path=root / "server.log",
            database_url=info.uri,
            python_executable=sys.executable,
            extra_env=settings,
        )
        if request.param == "standalone-worker":
            worker_port = free_port()
            env = {key: value for key, value in os.environ.items() if not key.startswith("HINDSIGHT_API_")}
            env.update(stub_environment(stub_server.url))
            env.update(settings)
            env["HINDSIGHT_API_DATABASE_URL"] = info.uri
            worker_log = (root / "worker.log").open("w")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "hindsight_api.worker.main",
                    "--http-host",
                    "127.0.0.1",
                    "--http-port",
                    str(worker_port),
                    "--worker-id",
                    name,
                ],
                cwd=root / "run",
                env=env,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
            )
            worker = HindsightServer(
                url=f"http://127.0.0.1:{worker_port}", log_path=root / "worker.log", _process=process
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise AssertionError(f"Standalone worker startup failed; log: {worker.log_path}")
                try:
                    if httpx.get(worker.url + "/health/ready", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError(f"Standalone worker readiness timed out; log: {worker.log_path}")
        headers = {"X-ContextDB-Control-Key": secret, "X-ContextDB-Actor-Subject": "story-admin"}
        response = httpx.post(
            server.url + "/ext/contextdb/v1/instances",
            headers=headers,
            json={"instance_id": "story-instance", "name": "Story"},
        )
        assert response.status_code == 201, response.text
        yield ContextDBDeployment(server, headers, info.uri)
    finally:
        if worker is not None:
            worker.stop()
        if worker_log is not None:
            worker_log.close()
        if server is not None:
            server.stop()
        pg.stop()


@pytest.fixture
async def contextdb_clients(contextdb_deployment: ContextDBDeployment) -> AsyncIterator[MemberClients]:
    base = contextdb_deployment.server.url
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers
    ) as management:

        async def create_workspace(name: str) -> str:
            response = await management.post(
                "/workspaces", json={"name": name}, headers={"Idempotency-Key": secrets.token_hex(8)}
            )
            assert response.status_code == 202, response.text
            operation = response.json()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                result = await management.get(f"/operations/{operation['operation_id']}")
                status = result.json()["state"]
                assert status != "failed", result.text
                if status == "succeeded":
                    return operation["workspace_id"]
                await asyncio.sleep(0.1)
            raise AssertionError("Workspace migration did not finish")

        bank_id = await create_workspace("Bank one")
        other_bank_id = await create_workspace("Bank two")

        async def member_key(bank: str, name: str, scopes: list[str] | None = None) -> str:
            response = await management.post(f"/workspaces/{bank}/members", json={"member_name": name})
            assert response.status_code == 201, response.text
            member_id = response.json()["member_id"]
            response = await management.post(
                f"/workspaces/{bank}/members/{member_id}/api-keys",
                json={
                    "name": "Story client",
                    "scopes": scopes or ["memory.read", "memory.write", "reflect", "knowledge.read"],
                    "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                },
            )
            assert response.status_code == 201, response.text
            return response.json()["secret"]

        own_key = await member_key(bank_id, "Alice")
        own = Hindsight(base_url=base, api_key=own_key)
        same = Hindsight(base_url=base, api_key=await member_key(bank_id, "Bob"))
        other = Hindsight(base_url=base, api_key=await member_key(other_bank_id, "Carol"))
        read_only = Hindsight(base_url=base, api_key=await member_key(bank_id, "Reader", ["memory.read"]))
        knowledge_only = Hindsight(
            base_url=base, api_key=await member_key(bank_id, "Knowledge reader", ["knowledge.read"])
        )
        try:
            yield MemberClients(own, same, other, read_only, knowledge_only, bank_id, other_bank_id, own_key)
        finally:
            await own.aclose()
            await same.aclose()
            await other.aclose()
            await read_only.aclose()
            await knowledge_only.aclose()


@pytest.mark.asyncio
async def test_dynamic_keys_shared_bank_and_worker_schema_isolation(contextdb_clients: MemberClients, llm) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    accepted = await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    assert accepted.operation_id is not None
    await wait_until_settled(clients.own, clients.bank_id)
    operations = await clients.own.operations.list_operations(clients.bank_id, limit=100)
    assert any(
        operation.operation_id == accepted.operation_id and operation.status == "completed"
        for operation in operations.operations
    )
    own = await clients.own.arecall(bank_id=clients.bank_id, query="What does Alice build?")
    shared = await clients.same_bank.arecall(bank_id=clients.bank_id, query="What does Alice build?")
    assert [item.text for item in own.results] == ["Alice builds Lighthouse | Involving: Alice"]
    assert [item.id for item in own.results] == [item.id for item in shared.results]
    other = await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="What does Alice build?")
    assert other.results == []
    with pytest.raises(ForbiddenException):
        await clients.other_bank.arecall(bank_id=clients.bank_id, query="What does Alice build?")


@pytest.mark.asyncio
async def test_mcp_uses_member_key_and_hides_bank_management(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    from fastmcp import Client

    clients = contextdb_clients
    async with Client(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=clients.own_key) as mcp:
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        assert "recall" in names
        assert "retain" in names
        assert "create_bank" not in names
        assert "delete_bank" not in names
        result = await mcp.call_tool("recall", {"query": "What is in this empty Bank?"})
        assert not result.is_error


@pytest.mark.asyncio
async def test_read_scopes_do_not_allow_writes_reflect_or_memory_recall(contextdb_clients: MemberClients) -> None:
    clients = contextdb_clients
    with pytest.raises(ForbiddenException):
        await clients.read_only.aretain(bank_id=clients.bank_id, content="Forbidden write")
    with pytest.raises(ForbiddenException):
        await clients.read_only.areflect(bank_id=clients.bank_id, query="Forbidden reflect")
    with pytest.raises(ForbiddenException):
        await clients.knowledge_only.arecall(bank_id=clients.bank_id, query="Forbidden memory recall")
    tree = await clients.knowledge_only.aget_knowledge_base_tree(clients.bank_id)
    assert tree.roots == []


@pytest.mark.asyncio
async def test_reflect_scope_runs_the_native_reasoning_loop(contextdb_clients: MemberClients, llm) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    await wait_until_settled(clients.own, clients.bank_id)
    reflect_loop(llm, answer="Alice builds Lighthouse.")
    response = await clients.own.areflect(bank_id=clients.bank_id, query="What does Alice build?", include_facts=True)
    assert response.text == "Alice builds Lighthouse."
    assert response.based_on is not None


@pytest.mark.asyncio
async def test_workspace_deletion_revokes_access_without_touching_another_schema(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    llm,
) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("extract_facts", contains="Atlas").returns(
        extracted(fact("Carol builds Atlas", who="Carol", entities=["Carol", "Atlas"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    await clients.other_bank.aretain(bank_id=clients.other_bank_id, content="Carol builds Atlas.", retain_async=True)
    await wait_until_settled(clients.own, clients.bank_id)
    await wait_until_settled(clients.other_bank, clients.other_bank_id)
    async with httpx.AsyncClient(
        base_url=contextdb_deployment.server.url + "/ext/contextdb/v1", headers=contextdb_deployment.headers
    ) as management:
        response = await management.delete(
            f"/workspaces/{clients.bank_id}", headers={"Idempotency-Key": "delete-story"}
        )
        assert response.status_code == 202, response.text
        operation_id = response.json()["operation_id"]
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            response = await management.get(f"/operations/{operation_id}")
            state = response.json()["state"]
            assert state != "failed", response.text
            if state == "succeeded":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Workspace deletion did not finish")
    with pytest.raises(UnauthorizedException):
        await clients.own.arecall(bank_id=clients.bank_id, query="Lighthouse")
    other = await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="What does Carol build?")
    assert [item.text for item in other.results] == ["Carol builds Atlas | Involving: Carol"]
