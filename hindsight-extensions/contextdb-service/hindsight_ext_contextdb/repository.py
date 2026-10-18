"""Transactional tenant metadata; lifecycle safety remains independent of user grants."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import replace

import asyncpg
from pydantic import TypeAdapter

from . import METADATA_FORMAT_ID, METADATA_VERSION
from .bootstrap import SYSTEM_ADMIN_NAME
from .models import (
    AllAuthorization,
    ApiKeyCreate,
    ApiKeyPatch,
    Authorization,
    BusinessPrincipal,
    ControlPrincipal,
    IssuedApiKey,
    KeyMetadata,
    ManagementOperation,
    Page,
    Permission,
    Role,
    Scope,
    SelectedAuthorization,
    ServiceError,
    StoredSelectedAuthorization,
    StoredWorkspaceGrant,
    User,
    UserCreate,
    UserPatch,
    Workspace,
    WorkspaceCreate,
    WorkspaceGrant,
    normalized_name,
    workspace_name,
)
from .security import credential_key_id, issue_key, key_digest


def request_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Repository:
    def __init__(
        self,
        pool: asyncpg.Pool,
        instance_id: str,
        cloud_tenant_id: str,
        pepper: str,
        *,
        operation_retention_hours: int = 168,
    ) -> None:
        self.pool = pool
        self.instance_id = instance_id
        self.cloud_tenant_id = cloud_tenant_id
        self.pepper = pepper
        self.operation_retention_hours = operation_retention_hours

    async def _binding_matches(self, reader: asyncpg.Pool | asyncpg.Connection | None = None) -> bool:
        return bool(
            await (reader or self.pool).fetchval(
                "SELECT count(*)=1 AND bool_and(singleton AND instance_id=$1 AND cloud_tenant_id=$2 AND metadata_version=$3 AND format_id=$4) FROM ctxdb_meta.deployment_info",
                self.instance_id,
                self.cloud_tenant_id,
                METADATA_VERSION,
                METADATA_FORMAT_ID,
            )
        )

    async def _require_binding(self, reader: asyncpg.Pool | asyncpg.Connection | None = None) -> None:
        if not await self._binding_matches(reader):
            raise ServiceError(403, "deployment_mismatch", "Database does not belong to this deployment")

    async def verify_schema(self) -> None:
        await self._verify_format(self.pool)
        await self._verify_binding(self.pool, self.instance_id, self.cloud_tenant_id)
        await self.verify_background_write_policy(self.pool)
        if not await self.pool.fetchval(
            "SELECT count(*)=1 AND bool_and(u.status='active' AND k.revoked_at IS NULL AND k.access_mode='all' AND k.permission='read_write') FROM ctxdb_meta.users u LEFT JOIN ctxdb_meta.api_keys k USING(user_id) WHERE u.role='admin'"
        ):
            raise RuntimeError("ContextDB requires one active system administrator and Key; run offline initialization")

    @staticmethod
    async def verify_background_write_policy(reader: asyncpg.Pool | asyncpg.Connection) -> None:
        # API policy disallows webhook creation, but an older deployment may
        # already have enabled rows. Reject before workers can enqueue delivery
        # payloads without the workspace generation required by our fence.
        for workspace in await reader.fetch("SELECT schema_name FROM ctxdb_meta.workspaces"):
            schema = workspace["schema_name"].replace('"', '""')
            table = f'"{schema}".webhooks'
            if await reader.fetchval("SELECT to_regclass($1)", table) and await reader.fetchval(
                f"SELECT EXISTS(SELECT 1 FROM {table} WHERE enabled)"
            ):
                raise ValueError(
                    "Disable existing native webhooks with the old version before ContextDB startup or upgrade"
                )
            banks = f'"{schema}".banks'
            if await reader.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name='banks' AND column_name='config')",
                workspace["schema_name"],
            ):
                if await reader.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM {banks} WHERE config->'audit_log_enabled'='true'::jsonb)"
                ):
                    raise ValueError("Disable existing native Bank audit logging before ContextDB startup or upgrade")

    @staticmethod
    async def _verify_binding(
        reader: asyncpg.Pool | asyncpg.Connection, instance_id: str, cloud_tenant_id: str
    ) -> None:
        bindings = await reader.fetch("SELECT instance_id,cloud_tenant_id FROM ctxdb_meta.deployment_info")
        if (
            len(bindings) != 1
            or bindings[0]["instance_id"] != instance_id
            or bindings[0]["cloud_tenant_id"] != cloud_tenant_id
        ):
            raise RuntimeError("ContextDB database belongs to another deployment; check instance and tenant IDs")

    @staticmethod
    async def _verify_format(reader: asyncpg.Pool | asyncpg.Connection) -> None:
        marker = await reader.fetchval("SELECT to_regclass('ctxdb_meta.deployment_info')")
        if marker is None:
            raise RuntimeError("Unsupported ContextDB metadata schema; run the offline deployment migration first")
        versions = await reader.fetch("SELECT singleton,metadata_version,format_id FROM ctxdb_meta.deployment_info")
        if (
            len(versions) != 1
            or not versions[0]["singleton"]
            or versions[0]["metadata_version"] != METADATA_VERSION
            or versions[0]["format_id"] != METADATA_FORMAT_ID
        ):
            raise RuntimeError("Unsupported ContextDB metadata schema; run the offline deployment migration first")

    def _workspace_model(self, row: asyncpg.Record) -> Workspace:
        return Workspace.model_validate(
            {**dict(row), "instance_id": self.instance_id, "cloud_tenant_id": self.cloud_tenant_id}
        )

    def _operation_model(self, row: asyncpg.Record) -> ManagementOperation:
        return ManagementOperation.model_validate(
            {**dict(row), "instance_id": self.instance_id, "actor_subject": "instance-admin"}
        )

    @staticmethod
    def _key_metadata(row: asyncpg.Record) -> KeyMetadata:
        authorization = (
            AllAuthorization(mode="all", permission=row["permission"])
            if row["access_mode"] == "all"
            else StoredSelectedAuthorization(
                workspaces=TypeAdapter(list[StoredWorkspaceGrant]).validate_json(row["grants"])
            )
        )
        return KeyMetadata.model_validate(
            {**dict(row), "authorization": authorization, "display_key": row["display_key"]}
        )

    # Metadata stores only an actual credential suffix. Legacy keys have no suffix;
    # never fabricate one from the public key ID or from its non-reversible digest.
    _GRANTS = "COALESCE((SELECT jsonb_agg(jsonb_build_object('workspace_id',g.workspace_id,'bank_id',w.bank_id,'permission',g.permission,'workspace_name',w.name) ORDER BY g.workspace_id) FROM ctxdb_meta.key_workspace_permissions g JOIN ctxdb_meta.workspaces w USING(workspace_id) WHERE g.key_id=k.key_id),'[]'::jsonb) AS grants "
    _KEY_SELECT = (
        "SELECT k.*,"
        + _GRANTS
        + ",CASE WHEN k.metadata->>'display_suffix' ~ '^[A-Za-z0-9_-]{6}$' THEN 'ctx_live_***'||(k.metadata->>'display_suffix') ELSE NULL END AS display_key FROM ctxdb_meta.api_keys k "
    )
    _WORKSPACE_SELECT = "SELECT w.*,(SELECT operation_id FROM ctxdb_meta.management_operations o WHERE o.workspace_id=w.workspace_id ORDER BY o.created_at DESC,o.operation_id DESC LIMIT 1) AS latest_operation_id FROM ctxdb_meta.workspaces w "

    def _tenant(self, principal: ControlPrincipal) -> None:
        if principal.cloud_tenant_id != self.cloud_tenant_id:
            raise ServiceError(403, "tenant_mismatch", "Credential does not belong to this deployment")
        if principal.actor_subject != "instance-admin":
            raise ServiceError(403, "admin_required", "The operations administrator Key is required")

    async def _instance_lock(self, conn: asyncpg.Connection) -> None:
        # Keep the old management serialization while dropping repeated scope
        # columns. In particular, issuing a Key cannot race member disable/delete.
        if not await conn.fetchval(
            "SELECT instance_id FROM ctxdb_meta.deployment_info WHERE singleton AND instance_id=$1 AND cloud_tenant_id=$2 FOR UPDATE",
            self.instance_id,
            self.cloud_tenant_id,
        ):
            raise ServiceError(404, "not_found", "Instance not registered")

    async def _audit(
        self,
        conn: asyncpg.Connection,
        principal: ControlPrincipal,
        request_id: str,
        action: str,
        *,
        workspace_id: str | None = None,
        user_id: str | None = None,
        key_id: str | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO ctxdb_meta.audit_events (request_id,workspace_id,user_id,key_id,control_key_id,action,result) VALUES($1,$2,$3,$4,$5,$6,'success')",
            request_id,
            workspace_id,
            user_id,
            key_id,
            principal.control_key_id,
            action,
        )

    async def _workspace(
        self, conn: asyncpg.Connection, principal: ControlPrincipal, workspace_id: str, *, exclusive: bool = False
    ) -> Workspace:
        await self._require_binding(conn)
        self._tenant(principal)
        row = await conn.fetchrow(
            self._WORKSPACE_SELECT
            + "WHERE w.workspace_id=$1 "
            + ("FOR UPDATE OF w" if exclusive else "FOR NO KEY UPDATE OF w"),
            workspace_id,
        )
        if row is None or row["state"] == "deleted":
            raise ServiceError(404, "not_found", "Workspace not found")
        return self._workspace_model(row)

    async def create_workspace(
        self, principal: ControlPrincipal, body: WorkspaceCreate, idempotency_key: str, request_id: str
    ) -> ManagementOperation:
        self._tenant(principal)
        name = workspace_name(body.name)
        normalized = name.casefold()
        if not normalized or len(name) > 64:
            raise ServiceError(400, "invalid_name", "Workspace name cannot be blank")
        digest = request_hash(body.model_dump_json())
        workspace_id, operation_id = (secrets.token_hex(16), secrets.token_hex(16))
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            old = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE action='create_workspace' AND target_id='' AND idempotency_key=$1",
                idempotency_key,
            )
            if old is not None:
                if old["request_hash"] != digest:
                    raise ServiceError(409, "idempotency_conflict", "Idempotency Key used for another request")
                if old["state"] == "failed":
                    await self._workspace(conn, principal, old["workspace_id"])
                    old = await self._restart_operation(conn, old)
                return self._operation_model(old)
            if await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.workspaces WHERE name_key=$1 AND state<>'deleted'", normalized
            ):
                raise ServiceError(409, "name_conflict", "Workspace name already exists")
            if await conn.fetchval("SELECT to_regnamespace($1)", f"ctxdb_ws_{name}") is not None:
                raise ServiceError(
                    409, "schema_conflict", "Workspace schema already exists; operator review is required"
                )
            try:
                await conn.execute(
                    "INSERT INTO ctxdb_meta.workspaces(workspace_id,schema_name,name,name_key,description,bank_id,state) VALUES($1,$2,$3,$4,$5,$3,'creating')",
                    workspace_id,
                    f"ctxdb_ws_{name}",
                    name,
                    normalized,
                    body.description,
                )
            except asyncpg.UniqueViolationError:
                raise ServiceError(409, "name_conflict", "Workspace name or Bank ID already exists") from None
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.management_operations (operation_id,workspace_id,action,target_id,idempotency_key,request_hash) VALUES($1,$2,'create_workspace','',$3,$4) RETURNING *",
                operation_id,
                workspace_id,
                idempotency_key,
                digest,
            )
            await self._audit(conn, principal, request_id, "create_workspace", workspace_id=workspace_id)
            return self._operation_model(row)

    async def get_workspace(self, principal: ControlPrincipal, workspace_id: str) -> Workspace:
        async with self.pool.acquire() as conn, conn.transaction():
            return await self._workspace(conn, principal, workspace_id)

    async def get_workspace_by_name(self, principal: ControlPrincipal, name: str) -> Workspace:
        self._tenant(principal)
        try:
            key = name
        except ValueError:
            raise ServiceError(400, "invalid_name", "Invalid workspace name") from None
        async with self.pool.acquire() as conn, conn.transaction(readonly=True):
            await self._require_binding(conn)
            row = await conn.fetchrow(self._WORKSPACE_SELECT + "WHERE w.bank_id=$1 AND w.state<>'deleted'", key)
            if row is None:
                raise ServiceError(404, "not_found", "Workspace not found")
            return self._workspace_model(row)

    async def list_workspaces(
        self, principal: ControlPrincipal, limit: int, offset: int, q: str = ""
    ) -> Page[Workspace]:
        self._tenant(principal)
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            clause = "WHERE w.state<>'deleted' AND ($1='' OR strpos(lower(w.name),lower($1))>0)"
            total = await conn.fetchval("SELECT count(*) FROM ctxdb_meta.workspaces w " + clause, q)
            rows = await conn.fetch(
                self._WORKSPACE_SELECT + clause + " ORDER BY w.created_at,w.workspace_id LIMIT $2 OFFSET $3",
                q,
                limit,
                offset,
            )
            return Page[Workspace](
                items=[self._workspace_model(row) for row in rows], total=total, limit=limit, offset=offset
            )

    async def authenticate(
        self, credential: str | None, bank_id: str | None = None, *, record_use: bool = False
    ) -> BusinessPrincipal:
        await self._require_binding()
        key_id = credential_key_id(credential)
        if key_id is None or credential is None:
            raise ServiceError(401, "invalid_key", "A valid API Key is required")
        row = await self.pool.fetchrow(
            "SELECT k.*,u.role AS user_role,"
            + self._GRANTS
            + "FROM ctxdb_meta.api_keys k JOIN ctxdb_meta.users u USING(user_id) WHERE k.key_id=$1 AND u.status='active' AND k.revoked_at IS NULL",
            key_id,
        )
        valid = hmac.compare_digest(key_digest(credential, self.pepper), row["digest"] if row else bytes(32))
        if row is None or not valid:
            raise ServiceError(401, "invalid_key", "A valid API Key is required")
        grants = TypeAdapter(list[StoredWorkspaceGrant]).validate_json(row["grants"])
        principal = BusinessPrincipal(
            key_id,
            row["user_id"],
            Role(row["user_role"]),
            row["access_mode"],
            frozenset(grant.workspace_id for grant in grants),
            Permission(row["permission"]) if row["permission"] else Permission.READ,
            workspace_permissions=tuple(grants),
        )
        if record_use:
            # Usage is approximate telemetry, never an authorization cache. A
            # shared busy key no longer rewrites the same tuple on every call.
            await self.pool.execute(
                "UPDATE ctxdb_meta.api_keys SET last_used_at=clock_timestamp() WHERE key_id=$1 AND (last_used_at IS NULL OR last_used_at<clock_timestamp()-interval '60 seconds')",
                key_id,
            )
        if bank_id is not None:
            principal = await self.select_workspace(principal, bank_id)
        return principal

    async def select_workspace(self, principal: BusinessPrincipal, bank_id: str) -> BusinessPrincipal:
        await self._require_binding()
        row = await self.pool.fetchrow(
            "SELECT workspace_id,schema_name,state FROM ctxdb_meta.workspaces WHERE bank_id=$1", bank_id
        )
        if row is None or row["state"] != "active":
            raise ServiceError(403, "bank_forbidden", "Workspace is unavailable or not authorized")
        workspace_id = row["workspace_id"]
        if principal.access_mode != "all" and workspace_id not in principal.workspace_ids:
            raise ServiceError(403, "bank_forbidden", "Key cannot access this workspace")
        permission = principal.permission
        if principal.access_mode == "selected":
            permission = next(
                (grant.permission for grant in principal.workspace_permissions if grant.workspace_id == workspace_id),
                Permission.READ,
            )
        scopes = {Scope.MEMORY_READ, Scope.KNOWLEDGE_READ, Scope.REFLECT}
        if permission == Permission.READ_WRITE:
            scopes.add(Scope.MEMORY_WRITE)
        return replace(
            principal,
            workspace_id=workspace_id,
            schema_name=row["schema_name"],
            permission=permission,
            scopes=frozenset(scopes),
        )

    async def visible_workspaces(self, principal: BusinessPrincipal, *, readable: bool = True) -> list[Workspace]:
        await self._require_binding()
        rows = await self.pool.fetch(
            "SELECT * FROM ctxdb_meta.workspaces WHERE state='active' AND ($1::boolean OR workspace_id=ANY($2::text[])) ORDER BY workspace_id",
            principal.access_mode == "all",
            list(principal.workspace_ids),
        )
        return [self._workspace_model(row) for row in rows]

    async def authenticate_admin(self, credential: str | None) -> ControlPrincipal:
        principal = await self.authenticate(credential)
        if principal.role != Role.ADMIN:
            raise ServiceError(403, "admin_required", "The operations administrator Key is required")
        return ControlPrincipal(principal.key_id, self.cloud_tenant_id, "instance-admin")

    async def _admin(self, conn: asyncpg.Connection, principal: ControlPrincipal) -> None:
        self._tenant(principal)

    async def _user(self, conn: asyncpg.Connection, user_id: str, *, include_deleted: bool = False) -> User:
        row = await conn.fetchrow(
            "SELECT * FROM ctxdb_meta.users WHERE user_id=$1 AND role='member' AND (status<>'deleted' OR $2)",
            user_id,
            include_deleted,
        )
        if row is None:
            raise ServiceError(404, "not_found", "User not found")
        return User.model_validate(dict(row))

    @staticmethod
    def _member_name(name: str) -> None:
        if name.casefold() == SYSTEM_ADMIN_NAME.casefold():
            raise ServiceError(409, "name_conflict", "Member name is reserved")

    async def create_user(self, principal: ControlPrincipal, body: UserCreate, request_id: str) -> User:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            await self._admin(conn, principal)
            name = normalized_name(body.name)
            self._member_name(name)
            try:
                row = await conn.fetchrow(
                    "INSERT INTO ctxdb_meta.users(user_id,name,name_key) VALUES($1,$2,$3) RETURNING *",
                    secrets.token_hex(16),
                    name,
                    name.casefold(),
                )
            except asyncpg.UniqueViolationError:
                raise ServiceError(409, "name_conflict", "Member name already exists") from None
            user = User.model_validate(dict(row))
            await self._audit(conn, principal, request_id, "create_user", user_id=user.user_id)
            return user

    async def list_users(self, principal: ControlPrincipal, limit: int, offset: int, q: str = "") -> Page[User]:
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            await self._admin(conn, principal)
            clause = "FROM ctxdb_meta.users WHERE role='member' AND status<>'deleted' AND ($1='' OR strpos(lower(name),lower($1))>0)"
            total = await conn.fetchval("SELECT count(*) " + clause, q)
            rows = await conn.fetch(
                "SELECT * " + clause + " ORDER BY created_at,user_id LIMIT $2 OFFSET $3", q, limit, offset
            )
            return Page[User](
                items=[User.model_validate(dict(row)) for row in rows], total=total, limit=limit, offset=offset
            )

    async def update_user(
        self,
        principal: ControlPrincipal,
        user_id: str,
        body: UserPatch,
        version: int | None,
        request_id: str,
        *,
        delete: bool = False,
    ) -> User:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            await self._admin(conn, principal)
            user = await self._user(conn, user_id, include_deleted=delete)
            if delete and user.status == "deleted":
                return user
            if version is not None and version != user.version:
                raise ServiceError(412, "version_conflict", "User version has changed")
            name = normalized_name(body.name or user.name)
            self._member_name(name)
            try:
                row = await conn.fetchrow(
                    "UPDATE ctxdb_meta.users SET name=$2,name_key=$4,status=$3,version=version+1,updated_at=now() WHERE user_id=$1 RETURNING *",
                    user_id,
                    name,
                    "deleted" if delete else body.status or user.status,
                    name.casefold(),
                )
            except asyncpg.UniqueViolationError:
                raise ServiceError(409, "name_conflict", "Member name already exists") from None
            await self._audit(conn, principal, request_id, "delete_user" if delete else "update_user", user_id=user_id)
            return User.model_validate(dict(row))

    async def _replace_authorization(self, conn: asyncpg.Connection, key_id: str, authorization: Authorization) -> None:
        await conn.execute("DELETE FROM ctxdb_meta.key_workspace_permissions WHERE key_id=$1", key_id)
        if isinstance(authorization, SelectedAuthorization):
            # The deployment row serializes lifecycle/name reuse with this
            # resolution. Persist immutable IDs, never reusable names as grants.
            for grant in authorization.workspaces:
                workspace_id = await conn.fetchval(
                    "SELECT workspace_id FROM ctxdb_meta.workspaces WHERE bank_id=$1 AND state='active'", grant.bank_id
                )
                if workspace_id is None:
                    raise ServiceError(400, "invalid_workspace", "Selected workspace must exist and be ready")
                if grant.workspace_id is not None and grant.workspace_id != workspace_id:
                    raise ServiceError(
                        409,
                        "workspace_generation_changed",
                        "Selected workspace was replaced; refresh the workspace picker",
                    )
                await conn.execute(
                    "INSERT INTO ctxdb_meta.key_workspace_permissions(key_id,workspace_id,permission) VALUES($1,$2,$3)",
                    key_id,
                    workspace_id,
                    grant.permission.value,
                )

    async def create_key(
        self, principal: ControlPrincipal, user_id: str, body: ApiKeyCreate, request_id: str
    ) -> IssuedApiKey:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            await self._admin(conn, principal)
            user = await self._user(conn, user_id)
            if user.status != "active":
                raise ServiceError(409, "inactive_user", "Inactive users cannot receive Keys")
            key = issue_key(self.pepper)
            authorization = body.authorization
            permission = authorization.permission.value if isinstance(authorization, AllAuthorization) else None
            await conn.execute(
                "INSERT INTO ctxdb_meta.api_keys(key_id,user_id,name,digest,access_mode,permission,metadata) VALUES($1,$2,$3,$4,$5,$6,jsonb_build_object('display_suffix',$7::text))",
                key.key_id,
                user_id,
                body.name,
                key.digest,
                authorization.mode,
                permission,
                key.secret[-6:],
            )
            await self._replace_authorization(conn, key.key_id, authorization)
            row = await conn.fetchrow(self._KEY_SELECT + "WHERE k.key_id=$1", key.key_id)
            await self._audit(conn, principal, request_id, "create_key", user_id=user_id, key_id=key.key_id)
            return IssuedApiKey(self._key_metadata(row), key.secret)

    async def list_keys(
        self, principal: ControlPrincipal, user_id: str, limit: int, offset: int, q: str = ""
    ) -> Page[KeyMetadata]:
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            await self._admin(conn, principal)
            await self._user(conn, user_id)
            clause = "WHERE k.user_id=$1 AND k.revoked_at IS NULL AND ($2='' OR strpos(lower(k.name),lower($2))>0)"
            total = await conn.fetchval("SELECT count(*) FROM ctxdb_meta.api_keys k " + clause, user_id, q)
            rows = await conn.fetch(
                self._KEY_SELECT + clause + " ORDER BY k.created_at,k.key_id LIMIT $3 OFFSET $4",
                user_id,
                q,
                limit,
                offset,
            )
            return Page[KeyMetadata](
                items=[self._key_metadata(row) for row in rows], total=total, limit=limit, offset=offset
            )

    async def update_key(
        self, principal: ControlPrincipal, user_id: str, key_id: str, body: ApiKeyPatch, version: int, request_id: str
    ) -> KeyMetadata:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            await self._admin(conn, principal)
            await self._user(conn, user_id)
            row = await conn.fetchrow(
                self._KEY_SELECT + "WHERE k.user_id=$1 AND k.key_id=$2 FOR UPDATE OF k", user_id, key_id
            )
            if row is None:
                raise ServiceError(404, "not_found", "Key not found")
            if row["version"] != version:
                raise ServiceError(412, "version_conflict", "Key version has changed")
            if row["revoked_at"] is not None:
                raise ServiceError(409, "immutable_key", "Revoked Keys cannot be edited")
            authorization = body.authorization
            if authorization is not None:
                await self._replace_authorization(conn, key_id, authorization)
            permission = authorization.permission.value if isinstance(authorization, AllAuthorization) else None
            await conn.execute(
                "UPDATE ctxdb_meta.api_keys SET name=$2,access_mode=$3,permission=$4,version=version+1,updated_at=now() WHERE key_id=$1",
                key_id,
                body.name if body.name is not None else row["name"],
                authorization.mode if authorization else row["access_mode"],
                permission if authorization else row["permission"],
            )
            updated = await conn.fetchrow(self._KEY_SELECT + "WHERE k.key_id=$1", key_id)
            await self._audit(conn, principal, request_id, "update_key", user_id=user_id, key_id=key_id)
            return self._key_metadata(updated)

    async def revoke_key(self, principal: ControlPrincipal, user_id: str, key_id: str, request_id: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            await self._admin(conn, principal)
            await self._user(conn, user_id)
            row = await conn.fetchrow(
                "SELECT revoked_at FROM ctxdb_meta.api_keys WHERE user_id=$1 AND key_id=$2 FOR UPDATE", user_id, key_id
            )
            if row is None:
                raise ServiceError(404, "not_found", "Key not found")
            if row["revoked_at"] is not None:
                return
            await conn.execute(
                "UPDATE ctxdb_meta.api_keys SET revoked_at=now(),version=version+1,updated_at=now() WHERE key_id=$1",
                key_id,
            )
            await self._audit(conn, principal, request_id, "revoke_key", user_id=user_id, key_id=key_id)

    async def worker_workspaces(self) -> list[Workspace]:
        return await self.discover_workspaces(self.pool, self.instance_id, self.cloud_tenant_id)

    @staticmethod
    async def discover_workspaces(
        reader: asyncpg.Pool | asyncpg.Connection, instance_id: str, cloud_tenant_id: str
    ) -> list[Workspace]:
        await Repository._verify_format(reader)
        await Repository._verify_binding(reader, instance_id, cloud_tenant_id)
        rows = await reader.fetch(
            "SELECT * FROM ctxdb_meta.workspaces WHERE state IN ('active','frozen','deleting') ORDER BY workspace_id"
        )
        return [
            Workspace.model_validate({**dict(row), "instance_id": instance_id, "cloud_tenant_id": cloud_tenant_id})
            for row in rows
        ]

    async def internal_workspace(self, bank_id: str, schema_name: str) -> Workspace:
        await self._require_binding()
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE bank_id=$1 AND schema_name=$2 AND state<>'deleted'",
            bank_id,
            schema_name,
        )
        if row is None:
            raise ServiceError(403, "internal_scope", "Internal operation does not match a registered workspace")
        return self._workspace_model(row)

    async def maintenance_workspace(self, schema_name: str) -> Workspace | None:
        await self._require_binding()
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE schema_name=$1 AND state='active'", schema_name
        )
        return self._workspace_model(row) if row else None

    async def register_admission(
        self, admission_id: str, owner_id: str, workspace_id: str, schema: str, origin: str
    ) -> None:
        """Persist before work starts, serialized with the workspace close gate.

        The caller still checks HTTP/queue-specific state under its regular
        admission lock. This short transaction must commit before that caller
        opens an engine transaction; it is not a lease or a substitute for auth.
        """
        await self._require_binding()
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 FOR KEY SHARE",
                workspace_id,
                schema,
            )
            if row is None or row["state"] == "deleted":
                raise ServiceError(409, "admission_closed", "Workspace admission is closed")
            await conn.execute(
                "INSERT INTO ctxdb_meta.request_admissions (admission_id,workspace_id,owner_id,origin) VALUES ($1,$2,$3,$4)",
                admission_id,
                workspace_id,
                owner_id,
                origin,
            )

    async def register_lifecycle_admission(self, operation: ManagementOperation, admission_id: str) -> None:
        """Reserve the generation until even an uncancellable migration exits.

        A replacement lease does not prove an old DDL thread stopped. Persist
        the barrier before DDL; a crashed executor needs explicit operator fencing.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self.operation_is_owned(
                operation.operation_id,
                operation.lease_token or "",
                operation.action,
                operation.workspace_id,
                connection=conn,
                lock=True,
            ):
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            if not await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR KEY SHARE", operation.workspace_id
            ):
                raise ServiceError(409, "workspace_state", "Workspace generation has ended")
            await conn.execute(
                "INSERT INTO ctxdb_meta.request_admissions(admission_id,workspace_id,owner_id,origin) VALUES($1,$2,$3,'lifecycle')",
                admission_id,
                operation.workspace_id,
                operation.lease_token,
            )

    async def finish_admission(self, admission_id: str, owner_id: str, *, interrupted: bool) -> None:
        await self._require_binding()
        # Unknown work is durable until an operator proves the old executor
        # stopped. Lease expiry or time elapsed is never proof of completion.
        query = (
            "UPDATE ctxdb_meta.request_admissions SET state='interrupted' "
            if interrupted
            else "DELETE FROM ctxdb_meta.request_admissions "
        )
        await self.pool.execute(query + "WHERE admission_id=$1 AND owner_id=$2", admission_id, owner_id)

    async def has_outstanding_admissions(self, workspace_id: str, *, excluding: str | None = None) -> bool:
        await self._require_binding()
        return bool(
            await self.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM ctxdb_meta.request_admissions WHERE workspace_id=$1 AND ($2::text IS NULL OR admission_id<>$2))",
                workspace_id,
                excluding,
            )
        )

    async def get_operation(self, principal: ControlPrincipal, operation_id: str) -> ManagementOperation:
        await self._require_binding()
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE operation_id=$1", operation_id
            )
            if row is None:
                raise ServiceError(404, "not_found", "Operation not found")
            self._tenant(principal)
            return self._operation_model(row)

    async def delete_workspace(
        self,
        principal: ControlPrincipal,
        bank_id: str,
        idempotency_key: str,
        request_id: str,
        *,
        expected_id: str,
        expected_version: int,
    ) -> ManagementOperation:
        workspace_id = expected_id
        await self._require_binding()
        self._tenant(principal)
        async with self.pool.acquire() as conn, conn.transaction():
            # History outlives the workspace row; look up the immutable target
            # before requiring a live directory entry so lost responses replay.
            old = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE workspace_id=$1 AND action='delete_workspace' AND idempotency_key=$2",
                workspace_id,
                idempotency_key,
            )
            if old is not None and old["request_hash"] != request_hash(bank_id):
                raise ServiceError(409, "idempotency_conflict", "Idempotency Key used for another request")
            if old is not None and old["state"] != "failed":
                return self._operation_model(old)
            # FOR UPDATE conflicts with admission FOR KEY SHARE; an ordinary
            # state UPDATE would not provide the same close/drain barrier.
            locked = await conn.fetchrow(
                "SELECT workspace_id FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR UPDATE", workspace_id
            )
            if locked is None:
                raise ServiceError(412, "version_conflict", "Workspace identity has changed")
            old = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE workspace_id=$1 AND action='delete_workspace' AND idempotency_key=$2",
                workspace_id,
                idempotency_key,
            )
            if old:
                if old["state"] == "failed":
                    await self._workspace(conn, principal, workspace_id)
                    old = await self._restart_operation(conn, old)
                return self._operation_model(old)
            workspace = await self._workspace(conn, principal, workspace_id)
            if workspace.bank_id != bank_id or workspace.version != expected_version:
                raise ServiceError(412, "version_conflict", "Workspace identity or version has changed")
            if workspace.state not in {"active", "frozen", "failed"}:
                raise ServiceError(409, "workspace_state", "Workspace cannot be deleted in its current state")
            running = await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.management_operations WHERE workspace_id=$1 AND state IN ('pending','running')",
                workspace_id,
            )
            if running:
                raise ServiceError(409, "operation_in_progress", "A workspace operation is already in progress")
            await conn.execute(
                "UPDATE ctxdb_meta.workspaces SET state='deleting',version=version+1,updated_at=now() WHERE workspace_id=$1",
                workspace_id,
            )
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.management_operations (operation_id,workspace_id,action,target_id,idempotency_key,request_hash,workspace_version) VALUES ($1,$2,'delete_workspace',$6,$3,$4,$5) RETURNING *",
                secrets.token_hex(16),
                workspace_id,
                idempotency_key,
                request_hash(bank_id),
                workspace.version + 1,
                workspace_id,
            )
            await self._audit(conn, principal, request_id, "delete_workspace", workspace_id=workspace_id)
            return self._operation_model(row)

    async def claim_operation(self) -> ManagementOperation | None:
        if not await self._binding_matches():
            return None
        row = await self.pool.fetchrow(
            "WITH candidate AS (SELECT operation_id FROM ctxdb_meta.management_operations WHERE ((state='pending' AND (lease_until IS NULL OR lease_until<=now())) OR (state='running' AND lease_until<now())) ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE ctxdb_meta.management_operations o SET state='running',attempts=attempts+1,lease_token=$1,lease_until=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() FROM candidate c WHERE o.operation_id=c.operation_id RETURNING o.*",
            secrets.token_hex(16),
        )
        return self._operation_model(row) if row else None

    async def renew_operation(self, operation: ManagementOperation) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                return False
            value = await conn.fetchval(
                "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() WHERE operation_id=$1 AND lease_token=$2 AND state='running' AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                operation.lease_token,
            )
            return value == 1

    async def _lock_operation(self, conn: asyncpg.Connection, operation: ManagementOperation) -> bool:
        """Acquire the owner row before checking expiry in a second statement.

        PG can evaluate an UPDATE's time predicate before waiting for a row lock.
        If the lease expires during that wait, an unchanged row need not trigger
        predicate re-evaluation. A separate lock/read makes the following live
        lease check happen after the wait, without keeping a transaction over DDL.
        """
        if not await self._binding_matches(conn):
            return False
        return (
            await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.management_operations WHERE operation_id=$1 AND lease_token=$2 AND state='running' AND action=$3 AND workspace_id=$4 FOR UPDATE",
                operation.operation_id,
                operation.lease_token,
                operation.action,
                operation.workspace_id,
            )
            == 1
        )

    async def operation_is_owned(
        self,
        operation_id: str,
        lease_token: str,
        action: str,
        workspace_id: str,
        *,
        connection: asyncpg.Connection | None = None,
        lock: bool = False,
    ) -> bool:
        """Check a purpose-limited lifecycle owner, optionally fencing a short write.

        Validators use a single read. A queue INSERT may use its existing open
        transaction with ``lock=True`` so a claimant cannot replace the owner
        between validation and commit. Never hold this row lock across native
        migration DDL: concurrent indexes can wait on the holder's snapshot.
        """
        if not await self._binding_matches(connection):
            return False
        if lock and (connection is None or not connection.is_in_transaction()):
            raise ValueError("Operation fencing requires the caller's open transaction")
        if not operation_id or not lease_token:
            return False
        binding = "SELECT 1 FROM ctxdb_meta.management_operations WHERE operation_id=$1 AND lease_token=$2 AND action=$3 AND workspace_id=$4 AND state='running'"
        # clock_timestamp is rechecked after the row-lock wait; now() would
        # remain frozen at transaction start and could accept an expired owner.
        reader = connection if connection is not None else self.pool
        if lock:
            if await reader.fetchval(binding + " FOR SHARE", operation_id, lease_token, action, workspace_id) != 1:
                return False
        return (
            await reader.fetchval(
                binding + " AND lease_until>clock_timestamp()", operation_id, lease_token, action, workspace_id
            )
            == 1
        )

    async def operation_workspace(self, operation: ManagementOperation) -> Workspace:
        await self._require_binding()
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE workspace_id=$1", operation.workspace_id
        )
        if row is None:
            raise ServiceError(404, "not_found", "Workspace not found")
        return self._workspace_model(row)

    async def bank_table_exists(self, schema: str) -> bool:
        return bool(await self.pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.banks"))

    async def file_table_exists(self, schema: str) -> bool:
        return bool(await self.pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.file_storage"))

    async def verify_workspace_schema(self, schema: str, *, connection: asyncpg.Connection | None = None) -> None:
        if connection is None:
            async with self.pool.acquire() as conn:
                await self.verify_workspace_schema(schema, connection=conn)
            return
        owned = await connection.fetchval(
            """
            SELECT nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
              AND NOT EXISTS(SELECT 1 FROM pg_class WHERE relnamespace=n.oid AND relowner<>n.nspowner)
              AND NOT EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace=n.oid AND proowner<>n.nspowner)
              AND NOT EXISTS(SELECT 1 FROM pg_type WHERE typnamespace=n.oid AND typowner<>n.nspowner)
              AND NOT EXISTS(SELECT 1 FROM pg_extension WHERE extnamespace=n.oid)
            FROM pg_namespace n WHERE nspname=$1
        """,
            schema,
        )
        if owned is False:
            raise ServiceError(409, "schema_ownership", "Workspace schema ownership needs operator review")
        if owned is not None and await self._has_external_schema_dependencies(connection, schema):
            raise ServiceError(409, "schema_dependencies", "Workspace has dependencies outside its schema")

    async def complete_operation(self, operation: ManagementOperation, *, error_code: str | None = None) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            # Same lock order as member/Key management: deployment -> operation
            # -> workspace -> Key. Final DROP must not invert grant editing.
            await self._instance_lock(conn)
            if not await self._lock_operation(conn, operation):
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            owned = await conn.fetchval(
                "UPDATE ctxdb_meta.management_operations SET state=$3,error_code=$4,lease_until=NULL,updated_at=clock_timestamp() WHERE operation_id=$1 AND lease_token=$2 AND state='running' AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                operation.lease_token,
                "failed" if error_code else "succeeded",
                error_code,
            )
            if not owned:
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            state = "failed" if error_code else "active" if operation.action == "create_workspace" else "deleted"
            if state == "deleted":
                await self._destroy_workspace(conn, operation.workspace_id)
                return
            await conn.execute(
                "UPDATE ctxdb_meta.workspaces SET state=$2,version=version+1,updated_at=now() WHERE workspace_id=$1",
                operation.workspace_id,
                state,
            )

    async def _destroy_workspace(self, conn: asyncpg.Connection, workspace_id: str) -> None:
        """DDL and final metadata removal commit together under the operation row lock.

        Reusable physical names remain reserved until the immutable owner row,
        durable admissions, queued work and operation fencing prove safe cleanup.
        """
        row = await conn.fetchrow(
            "SELECT schema_name,bank_id,state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR UPDATE", workspace_id
        )
        if (
            row is None
            or row["state"] not in {"deleting", "deleted"}
            or row["schema_name"] != f"ctxdb_ws_{row['bank_id']}"
        ):
            raise ServiceError(409, "workspace_state", "Workspace deletion binding has changed")
        if await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM ctxdb_meta.request_admissions WHERE workspace_id=$1)", workspace_id
        ):
            raise ServiceError(409, "workspace_busy", "Workspace still has admitted work")
        schema = row["schema_name"]
        await self.verify_workspace_schema(schema, connection=conn)
        owner = await conn.fetchval(
            "SELECT pg_get_userbyid(nspowner)=current_user FROM pg_namespace WHERE nspname=$1", schema
        )
        if owner is False:
            raise ServiceError(409, "schema_ownership", "Workspace schema ownership needs operator review")
        if owner is not None:
            if await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.async_operations"):
                if await conn.fetchval(
                    f"SELECT EXISTS(SELECT 1 FROM \"{schema}\".async_operations WHERE status IN ('pending','processing'))"
                ):
                    raise ServiceError(409, "workspace_busy", "Workspace still has queued work")
            await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        # Preserve the key itself and its other grants. An empty selected key is
        # denied, and stale editors must not restore a deleted grant unnoticed.
        await conn.execute(
            "UPDATE ctxdb_meta.api_keys SET version=version+1,updated_at=now() WHERE key_id IN (SELECT key_id FROM ctxdb_meta.key_workspace_permissions WHERE workspace_id=$1)",
            workspace_id,
        )
        await conn.execute("DELETE FROM ctxdb_meta.key_workspace_permissions WHERE workspace_id=$1", workspace_id)
        await conn.execute("DELETE FROM ctxdb_meta.workspaces WHERE workspace_id=$1", workspace_id)

    @staticmethod
    async def _has_external_schema_dependencies(conn: asyncpg.Connection, schema: str) -> bool:
        # CASCADE is limited to our own schema. In particular, a customer's view
        # or foreign key must not be silently dropped with the workspace tables.
        return bool(
            await conn.fetchval(
                """
            WITH owned AS (
              SELECT 'pg_namespace'::regclass AS classid,n.oid AS objid FROM pg_namespace n WHERE n.nspname=$1
              UNION ALL
              SELECT 'pg_class'::regclass AS classid,c.oid AS objid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=$1
              UNION ALL SELECT 'pg_type'::regclass,t.oid FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname=$1
              UNION ALL SELECT 'pg_proc'::regclass,p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname=$1
            )
            SELECT EXISTS(
              SELECT 1 FROM pg_depend d JOIN owned o ON o.classid=d.refclassid AND o.objid=d.refobjid
              LEFT JOIN pg_class c ON d.classid='pg_class'::regclass AND c.oid=d.objid
              LEFT JOIN pg_rewrite r ON d.classid='pg_rewrite'::regclass AND r.oid=d.objid
              LEFT JOIN pg_class v ON v.oid=r.ev_class
              LEFT JOIN pg_constraint k ON d.classid='pg_constraint'::regclass AND k.oid=d.objid
              LEFT JOIN pg_proc p ON d.classid='pg_proc'::regclass AND p.oid=d.objid
              LEFT JOIN pg_type t ON d.classid='pg_type'::regclass AND t.oid=d.objid
              LEFT JOIN pg_trigger g ON d.classid='pg_trigger'::regclass AND g.oid=d.objid
              LEFT JOIN pg_class gt ON gt.oid=g.tgrelid
              LEFT JOIN pg_attrdef a ON d.classid='pg_attrdef'::regclass AND a.oid=d.objid
              LEFT JOIN pg_class at ON at.oid=a.adrelid
              LEFT JOIN pg_policy pol ON d.classid='pg_policy'::regclass AND pol.oid=d.objid
              LEFT JOIN pg_class pr ON pr.oid=pol.polrelid
              LEFT JOIN LATERAL pg_identify_object(d.classid,d.objid,d.objsubid) identified ON true
              LEFT JOIN pg_namespace n ON n.oid=COALESCE(c.relnamespace,v.relnamespace,k.connamespace,p.pronamespace,t.typnamespace,gt.relnamespace,at.relnamespace,pr.relnamespace)
                OR (identified.schema IS NOT NULL AND n.nspname=identified.schema)
              WHERE (n.nspname<>$1 AND n.nspname<>'pg_toast') OR n.oid IS NULL
            )
        """,
                schema,
            )
        )

    async def prune_operations(self) -> int:
        """Bounded terminal history only; unknown work/admissions never expire."""
        await self._require_binding()
        rows = await self.pool.fetch(
            "DELETE FROM ctxdb_meta.management_operations WHERE operation_id IN (SELECT o.operation_id FROM ctxdb_meta.management_operations o WHERE o.state IN ('succeeded','failed') AND o.updated_at<clock_timestamp()-$1::double precision*interval '1 hour' AND (o.state='succeeded' OR NOT EXISTS(SELECT 1 FROM ctxdb_meta.workspaces w WHERE w.workspace_id=o.workspace_id)) ORDER BY o.updated_at LIMIT 100) RETURNING operation_id",
            float(self.operation_retention_hours),
        )
        return len(rows)

    async def defer_operation(self, operation: ManagementOperation, *, reason: str | None = None) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                return
            await conn.execute(
                "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '2 seconds',attempts=GREATEST(attempts-1,0),error_code=$3 WHERE operation_id=$1 AND lease_token=$2 AND state='running' AND lease_until>clock_timestamp()",
                operation.operation_id,
                operation.lease_token,
                reason,
            )

    async def _restart_operation(self, conn: asyncpg.Connection, old: asyncpg.Record) -> asyncpg.Record:
        workspace = await conn.fetchrow(
            "SELECT state,version FROM ctxdb_meta.workspaces WHERE workspace_id=$1", old["workspace_id"]
        )
        if workspace is None or workspace["state"] != "failed":
            raise ServiceError(409, "workspace_state", "Failed operation cannot restart after workspace state changed")
        # A failed newer delete must not make an old failed create restartable.
        if workspace["version"] != old["workspace_version"] + 1:
            raise ServiceError(409, "superseded_operation", "A newer workspace lifecycle superseded this operation")
        row = await conn.fetchrow(
            "UPDATE ctxdb_meta.management_operations SET state='pending',attempts=0,lease_token=NULL,lease_until=NULL,error_code=NULL,workspace_version=$2,updated_at=now() WHERE operation_id=$1 RETURNING *",
            old["operation_id"],
            workspace["version"] + 1,
        )
        await conn.execute(
            "UPDATE ctxdb_meta.workspaces SET state=$2,version=version+1,updated_at=now() WHERE workspace_id=$1",
            old["workspace_id"],
            "creating" if old["action"] == "create_workspace" else "deleting",
        )
        assert row is not None
        return row

    async def fail_operation(self, operation: ManagementOperation) -> None:
        retry = operation.attempts < 3
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            owned = await conn.fetchval(
                "UPDATE ctxdb_meta.management_operations SET state=$3,error_code='workspace_operation_failed',lease_token=NULL,lease_until=clock_timestamp()+$4::double precision*interval '1 second',updated_at=clock_timestamp() WHERE operation_id=$1 AND lease_token=$2 AND state='running' AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                operation.lease_token,
                "pending" if retry else "failed",
                float(2 ** min(operation.attempts, 3)),
            )
            if not owned:
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            if not retry:
                await conn.execute(
                    "UPDATE ctxdb_meta.workspaces SET state='failed',version=version+1,updated_at=now() WHERE workspace_id=$1 AND state<>'deleted'",
                    operation.workspace_id,
                )
