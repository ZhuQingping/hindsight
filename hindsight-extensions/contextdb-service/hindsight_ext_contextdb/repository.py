"""Transactional tenant metadata; lifecycle safety remains independent of user grants."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import replace

import asyncpg
from pydantic import TypeAdapter

from . import METADATA_FORMAT_ID, METADATA_VERSION
from .authorization import permission_scopes
from .bootstrap import SYSTEM_ADMIN_NAME
from .database_checks import verify_background_write_policy, verify_binding, verify_format
from .models import (
    AllAuthorization,
    ApiKeyCreate,
    ApiKeyPatch,
    Authorization,
    BusinessPrincipal,
    IssuedApiKey,
    KeyMetadata,
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

_STORED_GRANTS = TypeAdapter(list[StoredWorkspaceGrant])


def _grant_projection(*, targeted: bool) -> str:
    predicate = " AND ($2::text IS NULL OR w.bank_id=$2)" if targeted else ""
    return (
        "COALESCE((SELECT jsonb_agg(jsonb_build_object('workspace_id',g.workspace_id,'bank_id',w.bank_id,'permission',g.permission,'workspace_name',w.bank_id) ORDER BY g.workspace_id) "
        "FROM ctxdb_meta.key_workspace_permissions g JOIN ctxdb_meta.workspaces w USING(workspace_id) "
        f"WHERE g.key_id=k.key_id{predicate}),'[]'::jsonb) AS grants "
    )


class Repository:
    def __init__(
        self,
        pool: asyncpg.Pool,
        instance_id: str,
        cloud_tenant_id: str,
        pepper: str,
    ) -> None:
        self.pool = pool
        self.instance_id = instance_id
        self.cloud_tenant_id = cloud_tenant_id
        self.pepper = pepper

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
        await verify_format(self.pool)
        await verify_binding(self.pool, self.instance_id, self.cloud_tenant_id)
        await verify_background_write_policy(self.pool)
        if not await self.pool.fetchval(
            "SELECT count(*)=1 AND bool_and(u.status='active' AND k.revoked_at IS NULL AND k.access_mode='all' AND k.permission='read_write') FROM ctxdb_meta.users u LEFT JOIN ctxdb_meta.api_keys k USING(user_id) WHERE u.role='admin'"
        ):
            raise RuntimeError("ContextDB requires one active system administrator and Key; run offline initialization")

    @staticmethod
    def _workspace_model(row: asyncpg.Record) -> Workspace:
        return Workspace.model_validate({**dict(row), "name": row["bank_id"]})

    @staticmethod
    def _key_metadata(row: asyncpg.Record) -> KeyMetadata:
        authorization = (
            AllAuthorization(mode="all", permission=row["permission"])
            if row["access_mode"] == "all"
            else StoredSelectedAuthorization(workspaces=_STORED_GRANTS.validate_json(row["grants"]))
        )
        return KeyMetadata.model_validate(
            {**dict(row), "authorization": authorization, "display_key": row["display_key"]}
        )

    # Display only a validated credential suffix from metadata; never fabricate
    # one from the public key ID or its non-reversible digest.
    _GRANTS = _grant_projection(targeted=False)
    _KEY_SELECT = (
        "SELECT k.*,"
        + _GRANTS
        + ",CASE WHEN k.metadata->>'display_suffix' ~ '^[A-Za-z0-9_-]{6}$' THEN 'ctx_live_***'||(k.metadata->>'display_suffix') ELSE NULL END AS display_key FROM ctxdb_meta.api_keys k "
    )
    _WORKSPACE_SELECT = "SELECT w.* FROM ctxdb_meta.workspaces w "

    def _tenant(self, principal: BusinessPrincipal) -> None:
        if principal.role != Role.ADMIN:
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
        principal: BusinessPrincipal,
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
            principal.key_id,
            action,
        )

    async def _workspace(
        self, conn: asyncpg.Connection, principal: BusinessPrincipal, workspace_id: str, *, exclusive: bool = False
    ) -> Workspace:
        await self._require_binding(conn)
        self._tenant(principal)
        row = await conn.fetchrow(
            self._WORKSPACE_SELECT
            + "WHERE w.workspace_id=$1 "
            + ("FOR UPDATE OF w" if exclusive else "FOR NO KEY UPDATE OF w"),
            workspace_id,
        )
        if row is None:
            raise ServiceError(404, "not_found", "Workspace not found")
        return self._workspace_model(row)

    async def create_workspace(self, principal: BusinessPrincipal, body: WorkspaceCreate, request_id: str) -> Workspace:
        """Reserve a strict new identity; no connection is held across native DDL."""
        self._tenant(principal)
        name = workspace_name(body.name)
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            if await conn.fetchval("SELECT 1 FROM ctxdb_meta.workspaces WHERE bank_id=$1", name):
                raise ServiceError(409, "name_conflict", "Workspace name already exists")
            if await conn.fetchval("SELECT to_regnamespace($1)", f"ctxdb_ws_{name}") is not None:
                raise ServiceError(
                    409, "schema_conflict", "Workspace schema already exists; operator review is required"
                )
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.workspaces(workspace_id,schema_name,bank_id,description,state) VALUES($1,$2,$3,$4,'creating') RETURNING *",
                secrets.token_hex(16),
                f"ctxdb_ws_{name}",
                name,
                body.description,
            )
            return self._workspace_model(row)

    async def finish_workspace_creation(
        self, workspace: Workspace, principal: BusinessPrincipal, request_id: str
    ) -> Workspace:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            row = await conn.fetchrow(
                "UPDATE ctxdb_meta.workspaces SET state='active',version=version+1,updated_at=now(),metadata=metadata-'error_code' WHERE workspace_id=$1 AND state='creating' AND version=$2 RETURNING *",
                workspace.workspace_id,
                workspace.version,
            )
            if row is None:
                raise ServiceError(409, "workspace_state", "Workspace initialization state changed")
            await self._audit(conn, principal, request_id, "create_workspace", workspace_id=workspace.workspace_id)
            return self._workspace_model(row)

    async def fail_workspace(self, workspace: Workspace) -> None:
        """Preserve the same name/identity; never turn cancellation into safe cleanup."""
        await self._require_binding()
        await self.pool.execute(
            "UPDATE ctxdb_meta.workspaces SET state='failed',version=version+1,updated_at=now(),metadata=jsonb_set(metadata,'{error_code}','\"workspace_operation_failed\"'::jsonb) WHERE workspace_id=$1 AND state=$2 AND version=$3",
            workspace.workspace_id,
            workspace.state,
            workspace.version,
        )

    async def get_workspace(self, principal: BusinessPrincipal, workspace_id: str) -> Workspace:
        async with self.pool.acquire() as conn, conn.transaction():
            return await self._workspace(conn, principal, workspace_id)

    async def get_workspace_by_name(self, principal: BusinessPrincipal, name: str) -> Workspace:
        self._tenant(principal)
        key = name
        async with self.pool.acquire() as conn, conn.transaction(readonly=True):
            await self._require_binding(conn)
            row = await conn.fetchrow(self._WORKSPACE_SELECT + "WHERE w.bank_id=$1", key)
            if row is None:
                raise ServiceError(404, "not_found", "Workspace not found")
            return self._workspace_model(row)

    async def list_workspaces(
        self, principal: BusinessPrincipal, limit: int, offset: int, q: str = ""
    ) -> Page[Workspace]:
        self._tenant(principal)
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            clause = "WHERE ($1='' OR strpos(w.bank_id,lower($1))>0)"
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
        from .authorization import authenticated_principal

        admitted = authenticated_principal(credential, bank_id, self.instance_id, self.cloud_tenant_id, self.pepper)
        if admitted is not None:
            return admitted
        key_id = credential_key_id(credential)
        if key_id is None or credential is None:
            raise ServiceError(401, "invalid_key", "A valid API Key is required")
        # One statement verifies deployment, live user/Key and target grant in
        # the same snapshot. Targeted calls never aggregate unrelated grants.
        row = await self.pool.fetchrow(
            "WITH binding AS (SELECT count(*)=1 AND bool_and(singleton AND instance_id=$3 AND cloud_tenant_id=$4 AND metadata_version=$5 AND format_id=$6) AS valid FROM ctxdb_meta.deployment_info) "
            "SELECT k.*,u.role AS user_role,b.valid AS binding_valid,w.workspace_id,w.schema_name,w.state,"
            + _grant_projection(targeted=True)
            + "FROM binding b LEFT JOIN ctxdb_meta.api_keys k ON k.key_id=$1 AND k.revoked_at IS NULL LEFT JOIN ctxdb_meta.users u ON u.user_id=k.user_id AND u.status='active' LEFT JOIN ctxdb_meta.workspaces w ON w.bank_id=$2",
            key_id,
            bank_id,
            self.instance_id,
            self.cloud_tenant_id,
            METADATA_VERSION,
            METADATA_FORMAT_ID,
        )
        if not row["binding_valid"]:
            raise ServiceError(403, "deployment_mismatch", "Database does not belong to this deployment")
        valid = hmac.compare_digest(key_digest(credential, self.pepper), row["digest"] or bytes(32))
        if row["key_id"] is None or row["user_role"] is None or not valid:
            raise ServiceError(401, "invalid_key", "A valid API Key is required")
        grants = _STORED_GRANTS.validate_json(row["grants"])
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
            principal = self._selected_principal(principal, row)
        return principal

    @staticmethod
    def _selected_principal(principal: BusinessPrincipal, row: asyncpg.Record | None) -> BusinessPrincipal:
        if row is None or row["workspace_id"] is None or row["state"] != "active":
            raise ServiceError(403, "bank_forbidden", "Key cannot access this workspace")
        workspace_id = row["workspace_id"]
        if principal.access_mode != "all" and workspace_id not in principal.workspace_ids:
            raise ServiceError(403, "bank_forbidden", "Key cannot access this workspace")
        permission = principal.permission
        if principal.access_mode == "selected":
            permission = next(
                (grant.permission for grant in principal.workspace_permissions if grant.workspace_id == workspace_id),
                Permission.READ,
            )
        return replace(
            principal,
            workspace_id=workspace_id,
            schema_name=row["schema_name"],
            permission=permission,
            scopes=permission_scopes(permission),
        )

    async def visible_workspaces(self, principal: BusinessPrincipal) -> list[Workspace]:
        await self._require_binding()
        rows = await self.pool.fetch(
            "SELECT * FROM ctxdb_meta.workspaces WHERE state='active' AND ($1::boolean OR workspace_id=ANY($2::text[])) ORDER BY workspace_id",
            principal.access_mode == "all",
            list(principal.workspace_ids),
        )
        return [self._workspace_model(row) for row in rows]

    async def authenticate_admin(self, credential: str | None) -> BusinessPrincipal:
        principal = await self.authenticate(credential)
        if principal.role != Role.ADMIN:
            raise ServiceError(403, "admin_required", "The operations administrator Key is required")
        return principal

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

    async def create_user(self, principal: BusinessPrincipal, body: UserCreate, request_id: str) -> User:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            self._tenant(principal)
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

    async def list_users(self, principal: BusinessPrincipal, limit: int, offset: int, q: str = "") -> Page[User]:
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            self._tenant(principal)
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
        principal: BusinessPrincipal,
        user_id: str,
        body: UserPatch,
        version: int | None,
        request_id: str,
        *,
        delete: bool = False,
    ) -> User:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            self._tenant(principal)
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
            # Resolve all names in one snapshot under the deployment-row lock.
            # Persist immutable IDs so deleting/reusing a name cannot transfer grants.
            grants = authorization.workspaces
            rows = await conn.fetch(
                "SELECT bank_id,workspace_id FROM ctxdb_meta.workspaces WHERE bank_id=ANY($1::text[]) AND state='active'",
                [grant.bank_id for grant in grants],
            )
            identities = {row["bank_id"]: row["workspace_id"] for row in rows}
            for grant in grants:
                workspace_id = identities.get(grant.bank_id)
                if workspace_id is None:
                    raise ServiceError(400, "invalid_workspace", "Selected workspace must exist and be ready")
                if grant.workspace_id is not None and grant.workspace_id != workspace_id:
                    raise ServiceError(
                        409,
                        "workspace_generation_changed",
                        "Selected workspace was replaced; refresh the workspace picker",
                    )
            await conn.execute(
                "INSERT INTO ctxdb_meta.key_workspace_permissions(key_id,workspace_id,permission) SELECT $1,t.workspace_id,t.permission FROM unnest($2::text[],$3::text[]) AS t(workspace_id,permission)",
                key_id,
                [identities[grant.bank_id] for grant in grants],
                [grant.permission.value for grant in grants],
            )

    async def create_key(
        self, principal: BusinessPrincipal, user_id: str, body: ApiKeyCreate, request_id: str
    ) -> IssuedApiKey:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            self._tenant(principal)
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
        self, principal: BusinessPrincipal, user_id: str, limit: int, offset: int, q: str = ""
    ) -> Page[KeyMetadata]:
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            await self._require_binding(conn)
            self._tenant(principal)
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
        self, principal: BusinessPrincipal, user_id: str, key_id: str, body: ApiKeyPatch, version: int, request_id: str
    ) -> KeyMetadata:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            self._tenant(principal)
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

    async def revoke_key(self, principal: BusinessPrincipal, user_id: str, key_id: str, request_id: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            self._tenant(principal)
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
        await verify_format(reader)
        await verify_binding(reader, instance_id, cloud_tenant_id)
        rows = await reader.fetch(
            "SELECT * FROM ctxdb_meta.workspaces WHERE state IN ('active','deleting') ORDER BY workspace_id"
        )
        return [Workspace.model_validate({**dict(row), "name": row["bank_id"]}) for row in rows]

    async def internal_workspace(self, bank_id: str, schema_name: str) -> Workspace:
        await self._require_binding()
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE bank_id=$1 AND schema_name=$2",
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

    async def delete_workspace(
        self, principal: BusinessPrincipal, bank_id: str, request_id: str, *, expected_id: str, expected_version: int
    ) -> Workspace:
        """Close new access using an identity-bound ordinary management condition."""
        self._tenant(principal)
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            row = await conn.fetchrow(self._WORKSPACE_SELECT + "WHERE w.bank_id=$1 FOR UPDATE OF w", bank_id)
            if row is None:
                raise ServiceError(404, "not_found", "Workspace not found")
            workspace = self._workspace_model(row)
            if workspace.workspace_id != expected_id or workspace.version != expected_version:
                raise ServiceError(412, "version_conflict", "Workspace changed; refresh before deleting")
            if workspace.state not in {"active", "failed"}:
                raise ServiceError(
                    409,
                    "workspace_state",
                    "Workspace management is already in progress; verify the original request before cleanup",
                )
            row = await conn.fetchrow(
                "UPDATE ctxdb_meta.workspaces SET state='deleting',version=version+1,updated_at=now() WHERE workspace_id=$1 RETURNING *",
                workspace.workspace_id,
            )
            return self._workspace_model(row)

    async def finish_workspace_deletion(
        self, workspace: Workspace, principal: BusinessPrincipal, request_id: str
    ) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._instance_lock(conn)
            current = await self._workspace(conn, principal, workspace.workspace_id, exclusive=True)
            if current.state != "deleting" or current.version != workspace.version:
                raise ServiceError(409, "workspace_state", "Workspace deletion state changed")
            await self._destroy_workspace(conn, workspace.workspace_id)
            await self._audit(conn, principal, request_id, "delete_workspace", workspace_id=workspace.workspace_id)

    async def bank_exists(self, workspace: Workspace) -> bool:
        async with self.pool.acquire() as conn:
            if not await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name='banks' AND column_name='bank_id')",
                workspace.schema_name,
            ):
                return False
            return bool(
                await conn.fetchval(
                    f'SELECT EXISTS(SELECT 1 FROM "{workspace.schema_name}".banks WHERE bank_id=$1)', workspace.bank_id
                )
            )

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

    async def _destroy_workspace(self, conn: asyncpg.Connection, workspace_id: str) -> None:
        """Commit schema, selected grants and directory cleanup in one transaction."""
        row = await conn.fetchrow(
            "SELECT schema_name,bank_id,state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR UPDATE", workspace_id
        )
        if row is None or row["state"] != "deleting" or row["schema_name"] != f"ctxdb_ws_{row['bank_id']}":
            raise ServiceError(409, "workspace_state", "Workspace deletion binding has changed")
        schema = row["schema_name"]
        await self.verify_workspace_schema(schema, connection=conn)
        if await conn.fetchval("SELECT to_regnamespace($1)", schema) is not None:
            await conn.execute(f'DROP SCHEMA "{schema}" CASCADE')
        # Other Key grants survive. Stale authorization editors must refresh.
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
