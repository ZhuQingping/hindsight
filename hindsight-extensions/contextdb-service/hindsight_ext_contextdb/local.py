"""Authenticated local deployment with durable pg0 or an explicit external PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import os
import signal
import subprocess
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

from .bootstrap import prepare_deployment
from .deployment import write_environment
from .embedded import DatabaseConnection, private_directory
from .environment import service_env

EXTENSIONS = ("vector", "pg_trgm", "btree_gin")


def pg_control(command: str, directory: Path, data_dir: Path) -> DatabaseConnection | None:
    registry = directory / "pg0-home"
    private_directory(registry)
    result = subprocess.run(
        [sys.executable, "-m", "hindsight_ext_contextdb.embedded", command, str(directory), str(data_dir)],
        # pg0 keeps passwords in its instance registry. Isolate both that registry
        # and its extracted binaries; only this short control subprocess changes HOME.
        env={**os.environ, "HOME": str(registry)},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("Embedded PostgreSQL control failed; use a non-root Linux x86_64 user and pg0-embedded")
    return DatabaseConnection.model_validate_json(result.stdout) if command == "start" else None


async def enable_extensions(url: str) -> None:
    connection = await asyncpg.connect(url, timeout=10)
    try:
        for extension in EXTENSIONS:
            await connection.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    finally:
        await connection.close()


def configure(directory: Path, url: str, api_port: int, ui_port: int) -> None:
    # Preserve model/provider configuration from .env, but force all auth slots
    # under both aliases so an ambient public alias cannot override this contract.
    api = {key: value for key, value in os.environ.items() if key.startswith(("HINDSIGHT_API_", "CONTEXTBASE_API_"))}
    overrides = {
        "DATABASE_URL": url,
        "HOST": service_env("API_HOST", "0.0.0.0"),
        "PORT": str(api_port),
        "WORKER_ENABLED": "true",
        "TENANT_EXTENSION": "hindsight_ext_contextdb.tenant:ContextDBTenantExtension",
        "OPERATION_VALIDATOR_EXTENSION": "hindsight_ext_contextdb.validator:ContextDBOperationValidator",
        "HTTP_EXTENSION": "hindsight_ext_contextdb.http:ContextDBHttpExtension",
        "MCP_EXTENSION": "hindsight_ext_contextdb.mcp:ContextDBMCPExtension",
        "MCP_ENABLED": "true",
        "RUN_MIGRATIONS_ON_STARTUP": "false",
        "MIGRATION_ISOLATION": "false",
        "LLM_TRACE_ENABLED": "false",
        "AUDIT_LOG_ENABLED": "false",
    }
    for key, value in overrides.items():
        for prefix in ("HINDSIGHT_API_", "CONTEXTBASE_API_"):
            api[prefix + key] = value
    api["CONTEXTDB_INSTANCE_ID"] = os.environ.get("CONTEXTDB_INSTANCE_ID", "local")
    api["CONTEXTDB_CLOUD_TENANT_ID"] = os.environ.get("CONTEXTDB_CLOUD_TENANT_ID", "local")
    api["CONTEXTDB_RECALL_USAGE_ENABLED"] = os.environ.get("CONTEXTDB_RECALL_USAGE_ENABLED", "false")
    sessions = directory / "ui-sessions"
    private_directory(sessions)
    ui: dict[str, str] = {}
    for key, value in {
        "AUTH_MODE": "local",
        "CONTEXTDB_ENABLED": "true",
        "HOST": service_env("CP_HOST", "0.0.0.0"),
        "PORT": str(ui_port),
        "PUBLIC_ORIGIN": service_env("CP_PUBLIC_ORIGIN", f"http://localhost:{ui_port}"),
        "SESSION_DIR": str(sessions),
        "DATAPLANE_API_URL": f"http://127.0.0.1:{api_port}",
    }.items():
        for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
            ui[prefix + key] = value
    write_environment(directory / "api.env", api, replace=True)
    write_environment(directory / "ui.env", ui, replace=True)
    os.environ.update(api)


def serve(command: list[str], environment: dict[str, str]) -> int:
    process = subprocess.Popen(command, env=environment, start_new_session=True)

    def stop(signum: int, _frame: object) -> None:
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        return process.wait()
    finally:
        stop(signal.SIGTERM, None)
        try:
            process.wait(timeout=40)
        except subprocess.TimeoutExpired:
            stop(signal.SIGKILL, None)
            process.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=["all", "api", "ui"], default="all")
    parser.add_argument("--port", type=int)
    parser.add_argument("--ui-port", type=int)
    parser.add_argument("--random-port", action="store_true")
    args = parser.parse_args()

    def interrupted(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    root = Path(__file__).resolve().parents[3]
    load_dotenv(root / ".env", override=True)
    directory = (
        Path(os.environ.get("CONTEXTDB_DEPLOY_DIR", str(Path.home() / ".contextbase/local"))).expanduser().resolve()
    )
    private_directory(directory)
    environment = {
        **os.environ,
        "CONTEXTDB_DEPLOY_DIR": str(directory),
        "CONTEXTDB_PYTHON": sys.executable,
        "CONTEXTDB_UI_DEV": "1",
    }
    service = root / "hindsight-extensions/contextdb-service/scripts/service.sh"
    if args.component == "ui":
        raise SystemExit(serve(["bash", str(service), "ui"], environment))
    # Hold ownership for initialization and the complete API/Worker/UI lifetime.
    with (directory / "local.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.exit(2, "This local deployment is already running\n")
        url = service_env("API_DATABASE_URL", "pg0") or "pg0"
        embedded = url == "pg0" or url.startswith("pg0://")
        data_dir = Path(os.environ.get("CONTEXTDB_PG_DATA_DIR", str(directory / "pgdata"))).expanduser().resolve()
        started = False
        try:
            if embedded:
                if url != "pg0":
                    raise ValueError("Use pg0 with CONTEXTDB_PG_DATA_DIR, or an external PostgreSQL URL")
                info = pg_control("start", directory, data_dir)
                assert info is not None
                started = True
                url = info.uri
                asyncio.run(enable_extensions(url))
            api_port = args.port if args.port is not None else int(service_env("API_PORT", "8888"))
            ui_port = args.ui_port if args.ui_port is not None else int(service_env("CP_PORT", "9999"))
            if args.random_port:
                import socket

                with socket.socket() as api_socket, socket.socket() as ui_socket:
                    api_socket.bind(("127.0.0.1", 0))
                    ui_socket.bind(("127.0.0.1", 0))
                    api_port, ui_port = api_socket.getsockname()[1], ui_socket.getsockname()[1]
            if not 1024 <= api_port <= 65535 or not 1024 <= ui_port <= 65535 or api_port == ui_port:
                raise ValueError("API/UI ports must differ and be within 1024..65535")
            configure(directory, url, api_port, ui_port)
            # Persist credentials before the metadata migration. Existing deployments
            # must restore missing credentials rather than silently rotating them.
            asyncio.run(prepare_deployment(directory, url, service_env("CP_ACCESS_KEY") or None))
            environment.update(os.environ)
            environment.update(
                CONTEXTDB_DEPLOY_DIR=str(directory), CONTEXTDB_PYTHON=sys.executable, CONTEXTDB_UI_DEV="1"
            )
            environment["PYTHON_DOTENV_DISABLED"] = "1"
            subprocess.run(["bash", str(service), "init"], env=environment, check=True)
            print(f"ContextBase API: http://localhost:{api_port}; UI: http://localhost:{ui_port}", flush=True)
            print(f"Private login credentials: {directory / 'ui-secrets.json'}", flush=True)
            raise SystemExit(serve(["bash", str(service), args.component], environment))
        except KeyboardInterrupt:
            raise SystemExit(130) from None
        except (ValueError, OSError, asyncpg.PostgresError, subprocess.CalledProcessError):
            parser.exit(
                2,
                "Local initialization failed; check database/extensions, private state and configuration. Authentication remains required.\n",
            )
        finally:
            if started:
                try:
                    pg_control("stop", directory, data_dir)
                except ValueError:
                    print(
                        "Embedded database cleanup failed; inspect this deployment before restarting", file=sys.stderr
                    )


if __name__ == "__main__":
    main()
