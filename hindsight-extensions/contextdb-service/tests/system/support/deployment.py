"""Own a disposable PG, API and optional native Worker; never a developer service."""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import asyncpg
import httpx
from hindsight_system_tests.server import (
    HindsightServer,
    free_port,
    start_hindsight_server,
    stub_environment,
)
from pg0 import Pg0

from ...paths import EXTENSION, ROOT


@dataclass(frozen=True)
class DeploymentOptions:
    worker_mode: Literal["embedded-worker", "standalone-worker"] = "embedded-worker"
    default_template: str | None = None


@dataclass
class ContextDBDeployment:
    server: HindsightServer
    headers: dict[str, str] = field(repr=False)
    database_url: str = field(default="", repr=False)


@contextmanager
def deployment_owner(options: DeploymentOptions, stub_url: str, root: Path) -> Iterator[ContextDBDeployment]:
    name = f"ctxdb-story-{secrets.token_hex(6)}"
    pg = Pg0(name=name, port=free_port(), data_dir=str(root / "pg"), database="contextdb_story")

    async def bootstrap() -> None:
        from hindsight_ext_contextdb.migrations import migrate_connection

        conn = await asyncpg.connect(info.uri)
        try:
            # Offline fixture provisioning binds this dedicated instance before
            # the API is available. This does not inspect or fabricate memory.
            await migrate_connection(
                conn,
                "story-instance",
                "story-tenant",
                pepper="synthetic-story-pepper-32-bytes-long",
                admin_secret=secret,
            )
        finally:
            await conn.close()

    async def assert_no_public_business_tables() -> None:
        conn = await asyncpg.connect(info.uri)
        try:
            assert not await conn.fetchval("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public')")
        finally:
            await conn.close()

    key_id = secrets.token_hex(16)
    secret = f"ctx_admin_{key_id}_{secrets.token_urlsafe(32)}"
    server = None
    worker = None
    worker_log = None
    settings = {
        "PYTHONPATH": os.pathsep.join([str(ROOT / "hindsight-api-slim"), str(EXTENSION)]),
        "CONTEXTDB_INSTANCE_ID": "story-instance",
        "CONTEXTDB_CLOUD_TENANT_ID": "story-tenant",
        "CONTEXTDB_KEY_PEPPER": "synthetic-story-pepper-32-bytes-long",
        "HINDSIGHT_API_TENANT_EXTENSION": "hindsight_ext_contextdb.tenant:ContextDBTenantExtension",
        "HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION": "hindsight_ext_contextdb.validator:ContextDBOperationValidator",
        "HINDSIGHT_API_HTTP_EXTENSION": "hindsight_ext_contextdb.http:ContextDBHttpExtension",
        "PYTHON_DOTENV_DISABLED": "1",
        "HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP": "false",
        "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
        "HINDSIGHT_API_AUDIT_LOG_ENABLED": "false",
        "HINDSIGHT_API_MCP_ENABLED": "true",
        "HINDSIGHT_API_MCP_EXTENSION": "hindsight_ext_contextdb.mcp:ContextDBMCPExtension",
        "HINDSIGHT_API_WORKER_ENABLED": "true" if options.worker_mode == "embedded-worker" else "false",
    }
    template = options.default_template
    if template is not None:
        settings["HINDSIGHT_API_DEFAULT_BANK_TEMPLATE"] = template
    try:
        # Establish cleanup ownership before starting PG or running bootstrap.
        # A failed migration must not leave this test's database process running.
        info = pg.start()
        assert info.uri is not None
        asyncio.run(bootstrap())
        server = start_hindsight_server(
            stub_url=stub_url,
            log_path=root / "server.log",
            database_url=info.uri,
            python_executable=sys.executable,
            app_factory="hindsight_ext_contextdb.asgi:create_app",
            extra_env=settings,
        )
        if options.worker_mode == "standalone-worker":
            worker_port = free_port()
            env = {key: value for key, value in os.environ.items() if not key.startswith("HINDSIGHT_API_")}
            env.update(stub_environment(stub_url))
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
        headers = {"Authorization": "Bearer " + secret}
        yield ContextDBDeployment(server, headers, info.uri)
        # Infrastructure invariant after all SDK stories, including workspace
        # creation/deletion and async work; never inspect business content here.
        asyncio.run(assert_no_public_business_tables())
    finally:
        if worker is not None:
            worker.stop()
        if worker_log is not None:
            worker_log.close()
        if server is not None:
            server.stop()
        pg.stop()
