"""Exercise the actual node-Agent boundary, including shell-safe secret rendering."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from aiohttp import web
from hindsight_ext_contextdb.bootstrap import UiSecrets, save_credential
from hindsight_ext_contextdb.deployment import (
    DeploymentConfig,
    load_config,
    render,
    status,
)

from ..paths import EXTENSION, ROOT


def intent(tmp_path: Path, **changes: object) -> Path:
    for name, value in {
        "database": "postgresql://service:p%40ss@db.example:5432/contextdb?sslmode=verify-full",
        "maas": "synthetic-maas-secret-'$(touch SHOULD_NOT_EXIST)'",
        "password": "independent-password-123",
    }.items():
        path = tmp_path / name
        path.write_text(value + "\n")
        path.chmod(0o600)
    config = DeploymentConfig(
        instance_id="instance1",
        cloud_tenant_id="tenant1",
        topology="merged",
        database_url_file=tmp_path / "database",
        maas_api_key_file=tmp_path / "maas",
        ui_password_file=tmp_path / "password",
        ui_api_url="http://api:8888",
        language="english",
        text_search="native",
        worker_id="instance1-worker1",
    ).model_dump(mode="json")
    config.update(changes)
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(config))
    return path


def test_rendered_shell_preserves_secrets_without_execution(tmp_path: Path) -> None:
    config = load_config(intent(tmp_path))
    directory = tmp_path / "deployment"
    render(config, directory)
    render(config, directory)
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "api.env").stat().st_mode & 0o777 == 0o600
    probe = subprocess.run(
        ["bash", "-c", '. "$1"; printf "%s" "$HINDSIGHT_API_LLM_API_KEY"', "probe", str(directory / "api.env")],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout == (tmp_path / "maas").read_text().strip()
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    environment = (directory / "api.env").read_text()
    assert "HINDSIGHT_API_WORKER_ENABLED=true" in environment
    assert "HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false" in environment
    assert "HINDSIGHT_API_LLM_TRACE_ENABLED=false" in environment
    assert "HINDSIGHT_API_AUDIT_LOG_ENABLED=false" in environment
    assert "HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS" not in environment
    assert "HINDSIGHT_API_EMBEDDINGS_DIMENSION=" not in environment
    assert "CONTEXTDB_BOOTSTRAP_DATABASE_URL" not in environment
    assert "CONTEXTDB_METADATA_POOL_MAX_SIZE" not in environment
    assert "CONTEXTDB_ADMISSION_POOL_MAX_SIZE" not in environment
    assert "CONTEXTDB_OPERATION_RETENTION_HOURS" not in environment
    assert "CONTEXTDB_VALIDATION_LANGUAGE" not in environment
    assert "CONTEXTDB_KEY_PEPPER" not in environment
    assert "HINDSIGHT_CP_ACCESS_KEY" not in environment
    assert "HINDSIGHT_API_DATABASE_URL" not in (directory / "ui.env").read_text()


def test_release_example_renders_without_pgroonga(tmp_path: Path) -> None:
    example = json.loads((EXTENSION / "deployment/intent.example.json").read_text())
    private_intent = intent(tmp_path)
    private = json.loads(private_intent.read_text())
    for field in ("database_url_file", "maas_api_key_file", "ui_password_file"):
        example[field] = private[field]
    private_intent.write_text(json.dumps(example))
    config = load_config(private_intent)
    assert config.text_search == "native" and config.language == "english" and config.topology == "merged"
    render(config, tmp_path / "rds")
    environment = (tmp_path / "rds/api.env").read_text()
    assert "HINDSIGHT_API_TEXT_SEARCH_EXTENSION=native\n" in environment
    assert "HINDSIGHT_API_TEXT_SEARCH_EXTENSION_NATIVE_LANGUAGE=english\n" in environment
    assert "CONTEXTDB_VALIDATION_LANGUAGE" not in environment
    assert "pgroonga" not in environment


@pytest.mark.parametrize(
    "changes",
    [
        {"topology": "automatic"},
        {"topology": "split"},
        {"language": "multilingual", "text_search": "pgroonga"},
        {"language": "english", "text_search": "pg_search"},
        {"metadata_pool_max": 10},
        {"admission_pool_max": 64},
        {"operation_retention_hours": 168},
        {"language": "chinese", "text_search": "native"},
        {"language": "chinese", "text_search": "pg_search"},
        {"api_port": 9999},
        {"api_port": 65536},
        {"ui_api_url": "http://admin:secret@api:8888"},
        {"ui_api_url": "http://api:8888/path"},
        {"database_url_file": "relative"},
        {"unknown": True},
    ],
)
def test_reject_invalid_or_ambiguous_config(tmp_path: Path, changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        load_config(intent(tmp_path, **changes))


def test_permissions_symlink_and_password_change_fail_closed(tmp_path: Path) -> None:
    path = intent(tmp_path)
    config = load_config(path)
    directory = tmp_path / "deployment"
    render(config, directory)
    save_credential(directory / "ui-secrets.json", UiSecrets(password="independent-password-123", admin_key="test"))
    (tmp_path / "password").write_text("different-password-123")
    with pytest.raises(ValueError, match="differs"):
        render(config, directory, replace=True)
    (tmp_path / "password").write_text("independent-password-123")
    (tmp_path / "maas").chmod(0o644)
    with pytest.raises(ValueError, match="private regular"):
        load_config(path)
    (tmp_path / "maas").unlink()
    (tmp_path / "maas").symlink_to(tmp_path / "password")
    with pytest.raises(ValueError, match="private regular"):
        load_config(path)


def test_cli_failure_does_not_echo_secret_and_merged_explicit(tmp_path: Path) -> None:
    path = intent(tmp_path, topology="merged")
    config = load_config(path)
    render(config, tmp_path / "deployment")
    assert "HINDSIGHT_API_WORKER_ENABLED=true" in (tmp_path / "deployment/api.env").read_text()
    (tmp_path / "database").write_text("malformed-DONT-LEAK-THIS-SECRET")
    result = subprocess.run(
        [sys.executable, "-m", "hindsight_ext_contextdb.deployment", "validate", "--config", str(path)],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "DONT-LEAK" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["ok"] is False


async def test_status_reports_http_failure_without_upstream_body(tmp_path: Path) -> None:
    async def unavailable(_: web.Request) -> web.Response:
        return web.Response(status=503, text="private diagnostic body")

    app = web.Application()
    app.router.add_get("/health/ready", unavailable)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        port = runner.addresses[0][1]
        report = await status(f"http://127.0.0.1:{port}", tmp_path, instance_id="instance1", cloud_tenant_id="tenant1")
        assert report.ready is False
        assert report.api_http_status == 503
        assert "private diagnostic" not in report.model_dump_json()
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("origin", ["http://api:abc", "http://api:99999", "http://api:0"])
def test_config_rejects_invalid_api_port(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ValueError):
        load_config(intent(tmp_path, ui_api_url=origin))


@pytest.mark.parametrize(
    "failure", [None, "wrong_instance", "wrong_tenant", "bad_health", "invalid_secret", "redirect"]
)
async def test_status_requires_private_secrets_and_authenticated_instance(tmp_path: Path, failure: str | None) -> None:
    from hindsight_ext_contextdb.bootstrap import AdministratorCredential, ApiSecrets
    from hindsight_ext_contextdb.security import issue_admin_key

    issued = issue_admin_key()
    tmp_path.chmod(0o700)
    save_credential(tmp_path / "admin-key.json", AdministratorCredential(key_id=issued.key_id, secret=issued.secret))
    save_credential(tmp_path / "api-secrets.json", ApiSecrets(pepper="synthetic-status-pepper-32-bytes-long"))
    save_credential(
        tmp_path / "ui-secrets.json", UiSecrets(password="independent-test-password", admin_key=issued.secret)
    )
    if failure == "invalid_secret":
        (tmp_path / "api-secrets.json").write_text("{}")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({} if failure == "bad_health" else {"status": "healthy", "database": "connected"})

    async def identity(request: web.Request) -> web.Response:
        assert request.headers.get("Authorization") == "Bearer " + issued.secret
        if failure == "redirect":
            return web.Response(status=302, headers={"Location": "/unexpected"})
        return web.json_response(
            {
                "role": "admin",
                "instance_id": "other" if failure == "wrong_instance" else "instance1",
                "cloud_tenant_id": "other" if failure == "wrong_tenant" else "tenant1",
            }
        )

    app = web.Application()
    app.router.add_get("/health/ready", health)
    app.router.add_get("/ext/contextdb/v1/admin/identity", identity)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        port = runner.addresses[0][1]
        report = await status(f"http://127.0.0.1:{port}", tmp_path, instance_id="instance1", cloud_tenant_id="tenant1")
        assert report.ready is (failure is None)
        assert issued.secret not in report.model_dump_json()
    finally:
        await runner.cleanup()


def test_render_always_enables_contextdb_management(tmp_path: Path) -> None:
    render(load_config(intent(tmp_path)), tmp_path / "deployment")
    assert "HINDSIGHT_CP_CONTEXTDB_ENABLED=true" in (tmp_path / "deployment/ui.env").read_text()


async def test_rendered_ui_ca_reaches_native_probe_and_survives_sanitizer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the service.sh readiness subprocess against a real private CA."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("OpenSSL is required to generate the isolated HTTPS fixture")
    certificate = tmp_path / "ca.pem"
    private_key = tmp_path / "server.key"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    directory = tmp_path / "deployment"
    render(load_config(intent(tmp_path, ca_bundle_file=str(certificate))), directory)
    environment = {key: value for key, value in os.environ.items() if key not in {"SSL_CERT_FILE", "SSL_CERT_DIR"}}
    root = ROOT
    environment["PYTHONPATH"] = str(root / "hindsight-api-slim")
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, private_key)

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "database": "connected"})

    app = web.Application()
    app.router.add_get("/health/ready", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=tls)
    await site.start()
    try:
        url = f"https://localhost:{runner.addresses[0][1]}/health/ready"
        for with_python_ca in (False, True):
            # Source the actual rendered file exactly as service.sh does. Node's
            # CA setting alone must not accidentally make the Python probe pass.
            command = 'set -a; . "$1"; set +a; '
            if not with_python_ca:
                command += "unset SSL_CERT_FILE; "
            command += 'exec "$2" -m hindsight_api.http_probe "$3" 2'
            process = await asyncio.create_subprocess_exec(
                "bash",
                "-c",
                command,
                "probe",
                str(directory / "ui.env"),
                sys.executable,
                url,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=10)
            assert process.returncode == (0 if with_python_ca else 1)
    finally:
        await runner.cleanup()

    from hindsight_ext_contextdb import launch as launch_module

    server = tmp_path / "hindsight-control-plane/standalone/server.js"
    server.parent.mkdir(parents=True)
    server.write_text("// isolated launch fixture")
    captured: dict[str, str] = {}

    def capture_exec(_: str, __: list[str]) -> None:
        captured.update(os.environ)
        raise RuntimeError("captured node launch")

    with monkeypatch.context() as isolated:
        isolated.setattr(launch_module, "verify_ui_build", lambda _: None)
        isolated.setattr(launch_module, "load_deployment_secrets", lambda *_: None)
        isolated.setattr(launch_module.os, "environ", {"SSL_CERT_FILE": str(certificate)})
        isolated.setattr(launch_module.os, "execvp", capture_exec)
        with pytest.raises(RuntimeError, match="captured node launch"):
            launch_module.launch("ui", directory, tmp_path)
    assert captured["SSL_CERT_FILE"] == str(certificate)


async def test_real_source_init_preserves_secrets_without_public_business_tables(
    tmp_path: Path, database_url: str
) -> None:
    """Create/drop only a fresh database and role on the fixture-owned PG."""
    import secrets

    admin_url = os.environ.get("CONTEXTDB_DEPLOYMENT_TEST_ADMIN_URL") or database_url
    name = "ctxdb_night_deploy_" + secrets.token_hex(6)
    role_password = secrets.token_hex(32)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(
            f"CREATE ROLE \"{name}\" LOGIN PASSWORD '{role_password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        )
        await admin.execute(f'CREATE DATABASE "{name}" OWNER "{name}" TEMPLATE template0 ENCODING \'UTF8\'')
        provisioning = await asyncpg.connect(admin_url, database=name)
        try:
            for extension in ["vector", "pg_trgm", "btree_gin"]:
                await provisioning.execute(f'CREATE EXTENSION "{extension}"')
            host = await provisioning.fetchval("SELECT host(inet_server_addr())")
            port = await provisioning.fetchval("SELECT inet_server_port()")
        finally:
            await provisioning.close()
        # A generated password works with either trust or SCRAM fixtures; the
        # service role remains non-superuser and cannot provision other databases.
        url = f"postgresql://{name}:{role_password}@{host}:{port}/{name}"
        path = intent(tmp_path, language="english", text_search="native")
        (tmp_path / "database").write_text(url)
        directory = tmp_path / "deployment"
        render(load_config(path), directory)
        root = ROOT
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith(("HINDSIGHT_", "CONTEXTDB_"))
        }
        environment.update(CONTEXTDB_DEPLOY_DIR=str(directory), CONTEXTDB_PYTHON=sys.executable)
        before: dict[str, bytes] | None = None
        for _ in range(2):
            result = subprocess.run(
                ["bash", str(root / "hindsight-extensions/contextdb-service/scripts/service.sh"), "init"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            # Exercise the real prepare/init -> render seam, including valid
            # multiline JSON emitted by operator tooling on a later restart.
            ui_secrets = directory / "ui-secrets.json"
            ui_secrets.write_text(UiSecrets.model_validate_json(ui_secrets.read_text()).model_dump_json(indent=2))
            secret_files = [directory / "admin-key.json", *directory.glob("*secrets.json")]
            current = {item.name: item.read_bytes() for item in secret_files}
            if before is not None:
                assert current == before
            before = current
            render(load_config(path), directory)
            assert {item.name: item.read_bytes() for item in secret_files} == current
        connection = await asyncpg.connect(admin_url, database=name)
        try:
            assert not await connection.fetchval("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public')")
            assert await connection.fetchval("SELECT count(*) FROM ctxdb_meta.users WHERE role='admin'") == 1
            assert (
                UiSecrets.model_validate_json((directory / "ui-secrets.json").read_text()).password
                == (tmp_path / "password").read_text().strip()
            )
        finally:
            await connection.close()
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'DROP ROLE IF EXISTS "{name}"')
        await admin.close()


@pytest.mark.parametrize("component", ["init", "api", "worker"])
def test_managed_preflight_uses_fixed_english_without_derived_environment(tmp_path: Path, component: str) -> None:
    """Legacy shell variables cannot silently change the managed release's scope."""
    directory = tmp_path / "deployment"
    directory.mkdir(mode=0o700)
    environment = directory / "api.env"
    environment.write_text("CONTEXTDB_VALIDATION_LANGUAGE=chinese\n")
    environment.chmod(0o600)
    captured = tmp_path / "arguments"
    interpreter = tmp_path / "python"
    interpreter.write_text(
        "#!/bin/bash\n"
        'if [ "$1" = - ]; then exec "$REAL_PYTHON" "$@"; fi\n'
        'printf "%s\\n" "$@" > "$CAPTURE_ARGUMENTS"\n'
        "exit 37\n"
    )
    interpreter.chmod(0o700)
    result = subprocess.run(
        ["bash", str(EXTENSION / "scripts/service.sh"), component],
        env={
            **os.environ,
            "CONTEXTDB_DEPLOY_DIR": str(directory),
            "CONTEXTDB_PYTHON": str(interpreter),
            "REAL_PYTHON": sys.executable,
            "CAPTURE_ARGUMENTS": str(captured),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 37
    arguments = captured.read_text().splitlines()
    assert arguments[:3] == ["-m", "hindsight_ext_contextdb", "preflight"]
    assert arguments[-2:] == ["--language", "english"]
