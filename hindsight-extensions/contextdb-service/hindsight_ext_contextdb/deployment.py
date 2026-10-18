"""Small, secret-safe file contract for a node Agent; no management daemon."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import ssl
import stat
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .bootstrap import ApiSecrets, UiSecrets, read_credential


class DeploymentConfig(BaseModel):
    """Public deployment intent. Secret values are only read from private files."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    format: Literal[1] = 1
    instance_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    cloud_tenant_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    topology: Literal["merged"] = "merged"
    database_url_file: Path
    maas_api_key_file: Path
    ui_password_file: Path
    api_port: int = Field(default=8888, ge=1024, le=65535)
    ui_port: int = Field(default=9999, ge=1024, le=65535)
    ui_api_url: str
    language: Literal["english"] = "english"
    text_search: Literal["native"] = "native"
    worker_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    db_pool_max: int = Field(default=10, ge=2, le=100)
    llm_model: str = Field(default="deepseek-v4.1-flash", min_length=1, max_length=128)
    ca_bundle_file: Path | None = None

    @field_validator("database_url_file", "maas_api_key_file", "ui_password_file", "ca_bundle_file")
    @classmethod
    def absolute_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("Use an absolute file path")
        return value

    @field_validator("ui_api_url")
    @classmethod
    def api_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTP(S) URL without credentials")
        if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("Use the API origin without path/query/fragment")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Invalid API port")
        return value.rstrip("/")

    @model_validator(mode="after")
    def consistent(self) -> DeploymentConfig:
        if self.api_port == self.ui_port:
            raise ValueError("API and UI ports must differ")
        return self


class DeploymentStatus(BaseModel):
    ready: bool
    api_http_status: int | None = None
    secrets_present: bool
    detail: str


class RuntimeReadiness(BaseModel):
    status: Literal["healthy"]
    database: Literal["connected"]


class RuntimeIdentity(BaseModel):
    role: Literal["admin"]
    instance_id: str
    cloud_tenant_id: str


class DeploymentResult(BaseModel):
    ok: bool
    command: Literal["validate", "render"] | None = None
    error: Literal["invalid_or_inaccessible_deployment_configuration"] | None = None


def read_secret(path: Path) -> str:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Secret input must be a private regular file (0600)")
    value = path.read_text().removesuffix("\n")
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise ValueError("Secret input must contain one non-empty line")
    return value


def load_config(path: Path) -> DeploymentConfig:
    config = DeploymentConfig.model_validate_json(path.read_text())
    url = read_secret(config.database_url_file)
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("Database URL must select an existing PostgreSQL database")
    # Ports are validated here; urlsplit defers invalid-port errors to this property.
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("Invalid PostgreSQL port")
    read_secret(config.maas_api_key_file)
    password = read_secret(config.ui_password_file)
    if len(password) < 12 or password.startswith(("ctx_admin_", "ctx_live_", "ctx_ctrl_")):
        raise ValueError("Use an independent UI password of at least12 characters")
    if config.ca_bundle_file is not None and not config.ca_bundle_file.is_file():
        raise ValueError("CA bundle must exist at the same absolute path in each container")
    return config


def write_environment(path: Path, values: dict[str, str], replace: bool) -> None:
    content = "".join(f"{name}={shlex.quote(value)}\n" for name, value in sorted(values.items()))
    if path.exists() or path.is_symlink():
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("Existing configuration must be a private regular file (0600)")
        if path.read_text() == content:
            return
        if not replace:
            raise ValueError("Configuration differs; use --replace after stopping the affected components")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".config-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def render(config: DeploymentConfig, directory: Path, *, replace: bool = False) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Deployment directory must be private (0700)")
    password = read_secret(config.ui_password_file)
    persisted = directory / "ui-secrets.json"
    if persisted.exists() or persisted.is_symlink():
        mode = persisted.lstat().st_mode
        if not stat.S_ISREG(mode) or mode & 0o077:
            raise ValueError("Persisted UI secrets must be a private regular file (0600)")
        # JSON secrets may be pretty-printed; the single-line input-password
        # contract does not apply to an already persisted typed JSON document.
        if UiSecrets.model_validate_json(persisted.read_text()).password != password:
            raise ValueError("UI password differs from persisted secrets; ordinary render cannot rotate it")
    maas_key = read_secret(config.maas_api_key_file)
    api = {
        "CONTEXTDB_INSTANCE_ID": config.instance_id,
        "CONTEXTDB_CLOUD_TENANT_ID": config.cloud_tenant_id,
        "HINDSIGHT_API_DATABASE_URL": read_secret(config.database_url_file),
        "HINDSIGHT_API_HOST": "0.0.0.0",
        "HINDSIGHT_API_PORT": str(config.api_port),
        "HINDSIGHT_API_WORKER_ENABLED": "true",
        "HINDSIGHT_API_WORKER_ID": config.worker_id,
        "HINDSIGHT_API_WORKER_HTTP_PORT": "8889",
        "HINDSIGHT_API_DB_POOL_MIN_SIZE": "2",
        "HINDSIGHT_API_DB_POOL_MAX_SIZE": str(config.db_pool_max),
        "HINDSIGHT_API_READ_DB_POOL_MIN_SIZE": "2",
        "HINDSIGHT_API_READ_DB_POOL_MAX_SIZE": str(config.db_pool_max),
        "HINDSIGHT_API_TENANT_EXTENSION": "hindsight_ext_contextdb.tenant:ContextDBTenantExtension",
        "HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION": "hindsight_ext_contextdb.validator:ContextDBOperationValidator",
        "HINDSIGHT_API_HTTP_EXTENSION": "hindsight_ext_contextdb.http:ContextDBHttpExtension",
        "HINDSIGHT_API_MCP_EXTENSION": "hindsight_ext_contextdb.mcp:ContextDBMCPExtension",
        "HINDSIGHT_API_MCP_ENABLED": "true",
        "HINDSIGHT_API_MIGRATION_ISOLATION": "false",
        "HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP": "false",
        "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
        "HINDSIGHT_API_AUDIT_LOG_ENABLED": "false",
        "HINDSIGHT_API_VECTOR_EXTENSION": "pgvector",
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION": config.text_search,
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION_NATIVE_LANGUAGE": "english",
        "HINDSIGHT_API_LLM_PROVIDER": "openai",
        "HINDSIGHT_API_LLM_BASE_URL": "https://api.modelarts-maas.com/v2",
        "HINDSIGHT_API_LLM_API_KEY": maas_key,
        "HINDSIGHT_API_LLM_MODEL": config.llm_model,
        "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "openai",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL": "https://api.modelarts-maas.com/v1",
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY": maas_key,
        "HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL": "bge-m3",
        "HINDSIGHT_API_RERANKER_PROVIDER": "siliconflow",
        "HINDSIGHT_API_RERANKER_SILICONFLOW_BASE_URL": "https://api.modelarts-maas.com/v1",
        "HINDSIGHT_API_RERANKER_SILICONFLOW_API_KEY": maas_key,
        "HINDSIGHT_API_RERANKER_SILICONFLOW_MODEL": "bge-reranker-v2-m3",
        "HINDSIGHT_API_LOG_LEVEL": "info",
        "HINDSIGHT_API_LOG_FORMAT": "json",
    }
    ui = {
        "HINDSIGHT_CP_CONTEXTDB_ENABLED": "true",
        "HINDSIGHT_CP_HOST": "0.0.0.0",
        "HINDSIGHT_CP_PORT": str(config.ui_port),
        "HINDSIGHT_CP_DATAPLANE_API_URL": config.ui_api_url,
        "HINDSIGHT_CP_ACCESS_KEY": password,
    }
    if config.ca_bundle_file:
        api["SSL_CERT_FILE"] = str(config.ca_bundle_file)
        ui["SSL_CERT_FILE"] = str(config.ca_bundle_file)
        ui["NODE_EXTRA_CA_CERTS"] = str(config.ca_bundle_file)
    write_environment(directory / "api.env", api, replace)
    write_environment(directory / "ui.env", ui, replace)


async def status(
    url: str, directory: Path, *, instance_id: str, cloud_tenant_id: str, ca_bundle_file: Path | None = None
) -> DeploymentStatus:
    present = False
    credential = None
    try:
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise ValueError("Private deployment directory required")
        credential = read_credential(directory / "admin-key.json")
        for name in ("api-secrets.json", "ui-secrets.json"):
            mode = (directory / name).lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                raise ValueError("Private deployment secrets required")
        ApiSecrets.model_validate_json((directory / "api-secrets.json").read_text())
        ui = UiSecrets.model_validate_json((directory / "ui-secrets.json").read_text())
        present = ui.admin_key == credential.secret
    except (OSError, ValueError):
        credential = None
    try:
        ssl_context = (
            ssl.create_default_context(cafile=str(ca_bundle_file)) if ca_bundle_file else ssl.create_default_context()
        )
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=ssl_context),
            timeout=aiohttp.ClientTimeout(total=5),
            trust_env=False,  # Node-Agent readiness must reach the configured node directly.
        ) as session:
            async with session.get(url + "/health/ready", allow_redirects=False) as response:
                report = DeploymentStatus(
                    ready=False,
                    api_http_status=response.status,
                    secrets_present=present,
                    detail="Readiness or persisted-secret validation failed",
                )
                if response.status != 200 or not present or credential is None:
                    return report
                RuntimeReadiness.model_validate_json(await response.text())
            # Health alone can belong to a stale/unrelated container at the same
            # address. Confirm the private credential and immutable cloud binding.
            async with session.get(
                url + "/ext/contextdb/v1/admin/identity",
                headers={"Authorization": "Bearer " + credential.secret},
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    report.detail = "Administrator identity verification failed"
                    return report
                identity = RuntimeIdentity.model_validate_json(await response.text())
                report.ready = identity.instance_id == instance_id and identity.cloud_tenant_id == cloud_tenant_id
                report.detail = (
                    "API readiness and deployment identity verified; model and worker execution not checked"
                    if report.ready
                    else "Deployment identity does not match configuration"
                )
                return report
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return DeploymentStatus(ready=False, secrets_present=present, detail="API readiness connection failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["schema", "validate", "render", "status"])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--api-url", help="Readiness origin reachable from this command's network namespace")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.command == "schema":
        print(json.dumps(DeploymentConfig.model_json_schema(), indent=2))
        return
    if args.config is None or (args.command in {"render", "status"} and args.directory is None):
        parser.error("--config is required; render/status also require --directory")
    try:
        config = (
            DeploymentConfig.model_validate_json(args.config.read_text())
            if args.command == "status"
            else load_config(args.config)
        )
        if args.command == "render":
            render(config, args.directory, replace=args.replace)
        elif args.command == "status":
            origin = DeploymentConfig.api_url(args.api_url) if args.api_url else config.ui_api_url
            report = asyncio.run(
                status(
                    origin,
                    args.directory,
                    instance_id=config.instance_id,
                    cloud_tenant_id=config.cloud_tenant_id,
                    ca_bundle_file=config.ca_bundle_file,
                )
            )
            print(report.model_dump_json())
            raise SystemExit(0 if report.ready else 1)
        print(DeploymentResult(ok=True, command=args.command).model_dump_json(exclude_none=True))
    except (OSError, ValueError):
        # Validation exceptions may embed input values, including malformed secret
        # URLs. Keep the machine-visible failure independent of all input content.
        print(
            DeploymentResult(ok=False, error="invalid_or_inaccessible_deployment_configuration").model_dump_json(
                exclude_none=True
            )
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
