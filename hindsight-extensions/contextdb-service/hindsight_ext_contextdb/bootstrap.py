"""Offline administrator import and private, non-overwriting credential storage."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from .security import credential_key_id, key_digest

SYSTEM_ADMIN_NAME = "System administrator"


class AdministratorCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    secret: str = Field(repr=False)
    # Retained only as an optional offline handoff checksum, never runtime auth.
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class ApiSecrets(BaseModel):
    pepper: str = Field(min_length=32, repr=False)


class UiSecrets(BaseModel):
    password: str = Field(min_length=1, repr=False)
    admin_key: str = Field(repr=False)


def read_credential(path: Path) -> AdministratorCredential:
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Administrator credential must be a private regular file (0600)")
    try:
        credential = AdministratorCredential.model_validate_json(path.read_text())
        if not credential.secret.startswith("ctx_admin_") or credential_key_id(credential.secret) != credential.key_id:
            raise ValueError("Credential format does not match")
        if credential.sha256 and not hmac.compare_digest(
            hashlib.sha256(credential.secret.encode()).hexdigest(), credential.sha256
        ):
            raise ValueError("Credential checksum does not match")
    except (ValueError, TypeError):
        raise ValueError("Invalid administrator credential file") from None
    return credential


def save_credential(path: Path, credential: BaseModel) -> None:
    """Publish a fully flushed file atomically; an existing secret is never replaced."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".admin-", delete=False) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            stream.write(credential.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        # link() is an atomic no-replace operation on both supported POSIX hosts.
        os.link(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


async def prepare_deployment(directory: Path, database_url: str, password: str | None = None) -> None:
    """Persist all initial secrets before touching metadata; restart never regenerates."""
    from .security import issue_admin_key

    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_mode & 0o077:
        raise ValueError("Deployment directory must be private (0700)")
    connection = await asyncpg.connect(database_url, timeout=10)
    try:
        initialized = bool(await connection.fetchval("SELECT to_regnamespace('ctxdb_meta')"))
    finally:
        await connection.close()
    files = [directory / name for name in ("admin-key.json", "api-secrets.json", "ui-secrets.json")]
    if initialized and any(not path.is_file() for path in files):
        raise ValueError("Existing deployment secrets are missing; restore them instead of generating replacements")
    for path in files:
        if path.exists():
            mode = path.lstat().st_mode
            if not stat.S_ISREG(mode) or mode & 0o077:
                raise ValueError("Existing secret files must be private regular files (0600)")
    if not files[0].exists():
        issued = issue_admin_key()
        save_credential(
            files[0], AdministratorCredential(key_id=issued.key_id, secret=issued.secret, sha256=issued.digest.hex())
        )
    credential = read_credential(files[0])
    if not files[1].exists():
        save_credential(files[1], ApiSecrets(pepper=secrets.token_urlsafe(48)))
    if not files[2].exists():
        ui_password = password or secrets.token_urlsafe(24)
        if ui_password == credential.secret or ui_password.startswith(("ctx_admin_", "ctx_live_", "ctx_ctrl_")):
            raise ValueError("UI password must be independent from API keys")
        save_credential(files[2], UiSecrets(password=ui_password, admin_key=credential.secret))
    # Invalid partial files are never silently replaced, even before first boot.
    try:
        ApiSecrets.model_validate_json(files[1].read_text())
        ui = UiSecrets.model_validate_json(files[2].read_text())
        if (
            ui.admin_key != credential.secret
            or ui.password == credential.secret
            or ui.password.startswith(("ctx_admin_", "ctx_live_", "ctx_ctrl_"))
        ):
            raise ValueError("Credential mismatch")
    except ValueError:
        raise ValueError("Deployment secret files are invalid or inconsistent") from None


def load_deployment_secrets(directory: Path, component: Literal["api", "ui"]) -> None:
    """Only the UI receives its password/admin secret; only the API receives pepper."""
    path = directory / ("api-secrets.json" if component == "api" else "ui-secrets.json")
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o077:
        raise ValueError("Deployment secret file must be private (0600)")
    try:
        if component == "api":
            value = ApiSecrets.model_validate_json(path.read_text())
            os.environ["CONTEXTDB_KEY_PEPPER"] = value.pepper
        else:
            ui = UiSecrets.model_validate_json(path.read_text())
            os.environ["HINDSIGHT_CP_ACCESS_KEY"] = ui.password
            os.environ["HINDSIGHT_CP_DATAPLANE_API_KEY"] = ui.admin_key
    except ValueError:
        raise ValueError("Invalid deployment secret file") from None


async def initialize_administrator(conn: asyncpg.Connection, secret: str, pepper: str) -> None:
    """Called inside the offline migration transaction; repeated import is read-only."""
    key_id = credential_key_id(secret)
    if key_id is None or not secret.startswith("ctx_admin_") or len(pepper) < 32:
        raise ValueError("A valid administrator credential and deployment pepper are required")
    admins = await conn.fetch("SELECT user_id,status FROM ctxdb_meta.users WHERE role='admin'")
    if admins:
        if len(admins) != 1 or admins[0]["status"] != "active":
            raise ValueError("Invalid system administrator state; use controlled offline recovery")
        keys = await conn.fetch("SELECT * FROM ctxdb_meta.api_keys WHERE user_id=$1", admins[0]["user_id"])
        if (
            len(keys) != 1
            or keys[0]["key_id"] != key_id
            or keys[0]["revoked_at"] is not None
            or keys[0]["access_mode"] != "all"
            or keys[0]["permission"] != "read_write"
            or not hmac.compare_digest(keys[0]["digest"], key_digest(secret, pepper))
        ):
            raise ValueError("Administrator credential or pepper does not match the existing deployment")
        return
    if await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM ctxdb_meta.users WHERE name_key=$1 AND status<>'deleted')",
        SYSTEM_ADMIN_NAME.casefold(),
    ):
        raise ValueError("Existing member conflicts with the reserved system administrator name")
    user_id = secrets.token_hex(16)
    await conn.execute(
        "INSERT INTO ctxdb_meta.users(user_id,name,name_key,role) VALUES($1,$2,$3,'admin')",
        user_id,
        SYSTEM_ADMIN_NAME,
        SYSTEM_ADMIN_NAME.casefold(),
    )
    await conn.execute(
        "INSERT INTO ctxdb_meta.api_keys(key_id,user_id,name,digest,access_mode,permission) VALUES($1,$2,'System administrator',$3,'all','read_write')",
        key_id,
        user_id,
        key_digest(secret, pepper),
    )


async def rotate_administrator(conn: asyncpg.Connection, secret: str, pepper: str) -> None:
    """Explicit offline owner operation; ordinary CRUD cannot rotate this identity."""
    key_id = credential_key_id(secret)
    if key_id is None or not secret.startswith("ctx_admin_") or len(pepper) < 32:
        raise ValueError("A valid new administrator credential and the original pepper are required")
    if not await conn.fetchval(
        "SELECT pg_get_userbyid(nspowner)=current_user FROM pg_namespace WHERE nspname='ctxdb_meta'"
    ):
        raise ValueError("Administrator rotation requires the existing metadata owner")
    rows = await conn.fetch(
        "SELECT k.* FROM ctxdb_meta.api_keys k JOIN ctxdb_meta.users u USING(user_id) WHERE u.role='admin' AND u.status='active' FOR UPDATE OF k,u"
    )
    if len(rows) != 1:
        raise ValueError("Expected one protected administrator Key; explicit metadata repair is required")
    current = rows[0]
    if current["key_id"] == key_id:
        if current["revoked_at"] is None and hmac.compare_digest(current["digest"], key_digest(secret, pepper)):
            return
        raise ValueError("Generate a new administrator Key ID for rotation")
    await conn.execute(
        "UPDATE ctxdb_meta.api_keys SET key_id=$2,digest=$3,revoked_at=NULL,version=version+1,updated_at=now(),last_used_at=NULL WHERE key_id=$1",
        current["key_id"],
        key_id,
        key_digest(secret, pepper),
    )
    await conn.execute(
        "INSERT INTO ctxdb_meta.audit_events(request_id,user_id,key_id,control_key_id,action,result) VALUES($1,$2,$3::text,$3::text,'offline_admin_rotation','success')",
        secrets.token_hex(16),
        current["user_id"],
        key_id,
    )
