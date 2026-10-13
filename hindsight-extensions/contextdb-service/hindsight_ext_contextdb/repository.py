"""Transactional PG metadata access. No SQL belongs in the HTTP router.

Member/Key mutations lock the workspace before its members/Keys. This fixed order is
also the serialization point for the last-administrator invariant, avoiding an
advisory lock and two concurrent demotions both observing another admin.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg

from .models import (
    ApiKeyCreate,
    BusinessPrincipal,
    ControlPrincipal,
    Instance,
    InstanceCreate,
    IssuedApiKey,
    KeyMetadata,
    ManagementOperation,
    Member,
    MemberCreate,
    MemberPatch,
    Page,
    Role,
    Scope,
    ServiceError,
    Workspace,
    WorkspaceCreate,
    WorkspacePatch,
)
from .security import issue_key, key_digest, user_key_id


def request_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Repository:
    def __init__(self, pool: asyncpg.Pool, instance_id: str, cloud_tenant_id: str, pepper: str) -> None:
        self.pool = pool
        self.instance_id = instance_id
        self.cloud_tenant_id = cloud_tenant_id
        self.pepper = pepper

    async def verify_schema(self) -> None:
        versions = await self.pool.fetch("SELECT version FROM ctxdb_meta.schema_versions ORDER BY version")
        if [row["version"] for row in versions] != [1]:
            raise RuntimeError("Unsupported ContextDB metadata schema; run the deployment migration first")

    def _tenant(self, principal: ControlPrincipal) -> None:
        if principal.cloud_tenant_id != self.cloud_tenant_id:
            raise ServiceError(403, "tenant_mismatch", "Control credential does not belong to this deployment")

    async def create_instance(self, principal: ControlPrincipal, body: InstanceCreate) -> Instance:
        self._tenant(principal)
        if body.instance_id != self.instance_id:
            raise ServiceError(403, "instance_mismatch", "Only this deployment can be registered")
        async with self.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "INSERT INTO ctxdb_meta.instances (instance_id,cloud_tenant_id,name,created_by) "
                "VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                self.instance_id,
                self.cloud_tenant_id,
                body.name,
                principal.actor_subject,
            )
            row = await conn.fetchrow("SELECT * FROM ctxdb_meta.instances WHERE instance_id=$1", self.instance_id)
            if row is None or row["cloud_tenant_id"] != self.cloud_tenant_id:
                raise ServiceError(409, "instance_conflict", "Deployment registration conflicts with existing metadata")
            if row["name"] != body.name:
                raise ServiceError(409, "instance_conflict", "Instance is already registered with a different name")
            return Instance.model_validate(dict(row))

    async def get_instance(self, principal: ControlPrincipal, instance_id: str) -> Instance:
        self._tenant(principal)
        if instance_id != self.instance_id:
            raise ServiceError(404, "not_found", "Instance not found")
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.instances WHERE instance_id=$1 AND cloud_tenant_id=$2",
            self.instance_id,
            self.cloud_tenant_id,
        )
        if row is None:
            raise ServiceError(404, "not_found", "Register the deployment before creating workspaces")
        return Instance.model_validate(dict(row))

    async def _workspace(
        self,
        conn: asyncpg.Connection,
        principal: ControlPrincipal,
        workspace_id: str,
        *,
        admin: bool = False,
        target_member_id: str | None = None,
        exclusive: bool = False,
    ) -> Workspace:
        self._tenant(principal)
        row = await conn.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND instance_id=$2 "
            "AND cloud_tenant_id=$3 " + ("FOR UPDATE" if exclusive else "FOR NO KEY UPDATE"),
            workspace_id,
            self.instance_id,
            self.cloud_tenant_id,
        )
        if row is None or row["state"] == "deleted":
            raise ServiceError(404, "not_found", "Workspace not found")
        actor = await conn.fetchrow(
            "SELECT member_id,role FROM ctxdb_meta.workspace_members "
            "WHERE workspace_id=$1 AND iam_subject=$2 AND status='active'",
            workspace_id,
            principal.actor_subject,
        )
        if actor is None:
            raise ServiceError(404, "not_found", "Workspace not found")
        if actor["role"] != Role.ADMIN and (admin or (target_member_id and actor["member_id"] != target_member_id)):
            raise ServiceError(403, "forbidden", "Workspace administrator or target member is required")
        return Workspace.model_validate(dict(row))

    async def _audit(
        self,
        conn: asyncpg.Connection,
        principal: ControlPrincipal,
        request_id: str,
        action: str,
        *,
        workspace_id: str | None = None,
        member_id: str | None = None,
        key_id: str | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO ctxdb_meta.audit_events "
            "(request_id,instance_id,cloud_tenant_id,workspace_id,member_id,key_id,control_key_id,"
            "actor_subject,action,result) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'success')",
            request_id,
            self.instance_id,
            self.cloud_tenant_id,
            workspace_id,
            member_id,
            key_id,
            principal.control_key_id,
            principal.actor_subject,
            action,
        )

    async def create_workspace(
        self,
        principal: ControlPrincipal,
        body: WorkspaceCreate,
        idempotency_key: str,
        request_id: str,
    ) -> ManagementOperation:
        self._tenant(principal)
        await self.get_instance(principal, self.instance_id)
        digest = request_hash(body.model_dump_json())
        workspace_id, member_id, operation_id = secrets.token_hex(16), secrets.token_hex(16), secrets.token_hex(16)
        async with self.pool.acquire() as conn, conn.transaction():
            # The single instance row serializes create retries before any schema is
            # registered. Unlike a hash-only lookup this closes the absent-row race.
            await conn.fetchrow(
                "SELECT instance_id FROM ctxdb_meta.instances WHERE instance_id=$1 FOR UPDATE", self.instance_id
            )
            old = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE instance_id=$1 AND actor_subject=$2 "
                "AND action='create_workspace' AND target_id='' AND idempotency_key=$3",
                self.instance_id,
                principal.actor_subject,
                idempotency_key,
            )
            if old is not None:
                if old["request_hash"] != digest:
                    raise ServiceError(409, "idempotency_conflict", "Idempotency Key was used for a different request")
                if old["state"] == "failed":
                    await self._workspace(conn, principal, old["workspace_id"], admin=True)
                    old = await self._restart_operation(conn, old)
                return ManagementOperation.model_validate(dict(old))
            await conn.execute(
                "INSERT INTO ctxdb_meta.workspaces (workspace_id,instance_id,cloud_tenant_id,schema_name,name,description,state) "
                "VALUES ($1,$2,$3,$4,$5,$6,'creating')",
                workspace_id,
                self.instance_id,
                self.cloud_tenant_id,
                f"ctxdb_ws_{workspace_id}",
                body.name,
                body.description,
            )
            await conn.execute(
                "INSERT INTO ctxdb_meta.workspace_members (member_id,workspace_id,member_name,iam_subject,role) "
                "VALUES ($1,$2,'Initial administrator',$3,'admin')",
                member_id,
                workspace_id,
                principal.actor_subject,
            )
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.management_operations "
                "(operation_id,workspace_id,instance_id,actor_subject,action,target_id,idempotency_key,request_hash) "
                "VALUES ($1,$2,$3,$4,'create_workspace','',$5,$6) RETURNING *",
                operation_id,
                workspace_id,
                self.instance_id,
                principal.actor_subject,
                idempotency_key,
                digest,
            )
            await self._audit(conn, principal, request_id, "create_workspace", workspace_id=workspace_id)
            return ManagementOperation.model_validate(dict(row))

    async def get_workspace(self, principal: ControlPrincipal, workspace_id: str) -> Workspace:
        async with self.pool.acquire() as conn, conn.transaction():
            return await self._workspace(conn, principal, workspace_id)

    async def list_workspaces(self, principal: ControlPrincipal, limit: int, offset: int) -> Page[Workspace]:
        self._tenant(principal)
        clause = (
            "FROM ctxdb_meta.workspaces w JOIN ctxdb_meta.workspace_members m USING(workspace_id) "
            "WHERE w.instance_id=$1 AND w.cloud_tenant_id=$2 AND w.state<>'deleted' "
            "AND m.iam_subject=$3 AND m.status='active'"
        )
        async with self.pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
            total = await conn.fetchval(
                "SELECT count(*) " + clause, self.instance_id, self.cloud_tenant_id, principal.actor_subject
            )
            rows = await conn.fetch(
                "SELECT w.* " + clause + " ORDER BY w.created_at,w.workspace_id LIMIT $4 OFFSET $5",
                self.instance_id,
                self.cloud_tenant_id,
                principal.actor_subject,
                limit,
                offset,
            )
            return Page[Workspace](
                items=[Workspace.model_validate(dict(row)) for row in rows], total=total, limit=limit, offset=offset
            )

    async def update_workspace(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        body: WorkspacePatch,
        version: int,
        request_id: str,
    ) -> Workspace:
        async with self.pool.acquire() as conn, conn.transaction():
            workspace = await self._workspace(
                conn, principal, workspace_id, admin=True, exclusive=body.state is not None
            )
            if workspace.version != version:
                raise ServiceError(412, "version_conflict", "Workspace version has changed")
            if workspace.state not in {"active", "frozen"}:
                raise ServiceError(409, "workspace_state", "Workspace is not ready for updates")
            row = await conn.fetchrow(
                "UPDATE ctxdb_meta.workspaces SET name=COALESCE($2,name),description=COALESCE($3,description),"
                "state=COALESCE($4,state),version=version+1 WHERE workspace_id=$1 RETURNING *",
                workspace_id,
                body.name,
                body.description,
                body.state,
            )
            await self._audit(conn, principal, request_id, "update_workspace", workspace_id=workspace_id)
            return Workspace.model_validate(dict(row))

    async def create_member(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        body: MemberCreate,
        request_id: str,
    ) -> Member:
        async with self.pool.acquire() as conn, conn.transaction():
            workspace = await self._workspace(conn, principal, workspace_id, admin=True)
            if workspace.state not in {"active", "frozen"}:
                raise ServiceError(409, "workspace_state", "Workspace is not ready for member management")
            if body.iam_subject and await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.workspace_members WHERE workspace_id=$1 AND iam_subject=$2",
                workspace_id,
                body.iam_subject,
            ):
                raise ServiceError(409, "member_conflict", "Login identity is already bound in this workspace")
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.workspace_members (member_id,workspace_id,member_name,iam_subject,role) "
                "VALUES ($1,$2,$3,$4,$5) RETURNING *",
                secrets.token_hex(16),
                workspace_id,
                body.member_name,
                body.iam_subject,
                body.role,
            )
            member = Member.model_validate(dict(row))
            await self._audit(
                conn, principal, request_id, "create_member", workspace_id=workspace_id, member_id=member.member_id
            )
            return member

    async def get_member(self, principal: ControlPrincipal, workspace_id: str, member_id: str) -> Member:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._workspace(conn, principal, workspace_id, target_member_id=member_id)
            return await self._member(conn, workspace_id, member_id)

    async def _member(
        self,
        conn: asyncpg.Connection,
        workspace_id: str,
        member_id: str,
        *,
        include_deleted: bool = False,
    ) -> Member:
        row = await conn.fetchrow(
            "SELECT * FROM ctxdb_meta.workspace_members WHERE workspace_id=$1 AND member_id=$2 "
            "AND (status<>'deleted' OR $3)",
            workspace_id,
            member_id,
            include_deleted,
        )
        if row is None:
            raise ServiceError(404, "not_found", "Member not found")
        return Member.model_validate(dict(row))

    async def list_members(
        self, principal: ControlPrincipal, workspace_id: str, limit: int, offset: int
    ) -> Page[Member]:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._workspace(conn, principal, workspace_id, admin=True)
            total = await conn.fetchval(
                "SELECT count(*) FROM ctxdb_meta.workspace_members WHERE workspace_id=$1 AND status<>'deleted'",
                workspace_id,
            )
            rows = await conn.fetch(
                "SELECT * FROM ctxdb_meta.workspace_members WHERE workspace_id=$1 AND status<>'deleted' "
                "ORDER BY created_at,member_id LIMIT $2 OFFSET $3",
                workspace_id,
                limit,
                offset,
            )
            return Page[Member](
                items=[Member.model_validate(dict(row)) for row in rows], total=total, limit=limit, offset=offset
            )

    async def update_member(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        member_id: str,
        body: MemberPatch,
        version: int | None,
        request_id: str,
        *,
        delete: bool = False,
    ) -> Member:
        async with self.pool.acquire() as conn, conn.transaction():
            workspace = await self._workspace(conn, principal, workspace_id, admin=True)
            if workspace.state not in {"active", "frozen"}:
                raise ServiceError(409, "workspace_state", "Workspace is not ready for member management")
            member = await self._member(conn, workspace_id, member_id, include_deleted=delete)
            if delete and member.status == "deleted":
                return member
            if version is not None and member.version != version:
                raise ServiceError(412, "version_conflict", "Member version has changed")
            role = body.role or member.role
            status = "deleted" if delete else body.status or member.status
            if role == Role.ADMIN and not member.iam_subject:
                raise ServiceError(409, "missing_login", "Administrator requires a verified login binding")
            if member.role == Role.ADMIN and member.status == "active" and (role != Role.ADMIN or status != "active"):
                remaining = await conn.fetchval(
                    "SELECT count(*) FROM ctxdb_meta.workspace_members WHERE workspace_id=$1 "
                    "AND member_id<>$2 AND role='admin' AND status='active'",
                    workspace_id,
                    member_id,
                )
                if not remaining:
                    raise ServiceError(409, "last_admin", "The last active administrator cannot be removed")
            row = await conn.fetchrow(
                "UPDATE ctxdb_meta.workspace_members SET member_name=COALESCE($3,member_name),role=$4,status=$5,"
                "version=version+1 WHERE workspace_id=$1 AND member_id=$2 RETURNING *",
                workspace_id,
                member_id,
                body.member_name,
                role,
                status,
            )
            await self._audit(
                conn,
                principal,
                request_id,
                "delete_member" if delete else "update_member",
                workspace_id=workspace_id,
                member_id=member_id,
            )
            return Member.model_validate(dict(row))

    async def create_key(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        member_id: str,
        body: ApiKeyCreate,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> IssuedApiKey:
        now = datetime.now(timezone.utc)
        if body.expires_at <= now or body.expires_at > now + timedelta(days=365):
            raise ServiceError(400, "invalid_expiry", "Key expiry must be in the future and within 365 days")
        async with self.pool.acquire() as conn, conn.transaction():
            workspace = await self._workspace(conn, principal, workspace_id, target_member_id=member_id)
            member = await self._member(conn, workspace_id, member_id)
            if workspace.state not in {"active", "frozen"} or member.status != "active":
                raise ServiceError(409, "inactive_target", "Workspace/member is not ready for Key issuance")
            if idempotency_key:
                old = await conn.fetchrow(
                    "SELECT key_id,request_hash FROM ctxdb_meta.key_requests WHERE workspace_id=$1 AND member_id=$2 "
                    "AND actor_subject=$3 AND idempotency_key=$4",
                    workspace_id,
                    member_id,
                    principal.actor_subject,
                    idempotency_key,
                )
                if old:
                    if old["request_hash"] != request_hash(body.model_dump_json()):
                        raise ServiceError(
                            409, "idempotency_conflict", "Idempotency-Key was used with another Key request"
                        )
                    raise ServiceError(
                        409, "key_already_issued", f"Key already issued: {old['key_id']}; secret cannot be replayed"
                    )
            key = issue_key(self.pepper)
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.api_keys (key_id,workspace_id,member_id,name,digest,scopes,expires_at,created_by) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
                key.key_id,
                workspace_id,
                member_id,
                body.name,
                key.digest,
                [scope.value for scope in body.scopes],
                body.expires_at,
                principal.actor_subject,
            )
            if idempotency_key:
                await conn.execute(
                    "INSERT INTO ctxdb_meta.key_requests (workspace_id,member_id,actor_subject,idempotency_key,request_hash,key_id) "
                    "VALUES ($1,$2,$3,$4,$5,$6)",
                    workspace_id,
                    member_id,
                    principal.actor_subject,
                    idempotency_key,
                    request_hash(body.model_dump_json()),
                    key.key_id,
                )
            await self._audit(
                conn,
                principal,
                request_id,
                "create_key",
                workspace_id=workspace_id,
                member_id=member_id,
                key_id=key.key_id,
            )
            return IssuedApiKey(KeyMetadata.model_validate(dict(row)), key.secret)

    async def list_keys(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        member_id: str,
        limit: int,
        offset: int,
    ) -> Page[KeyMetadata]:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._workspace(conn, principal, workspace_id, target_member_id=member_id)
            await self._member(conn, workspace_id, member_id)
            total = await conn.fetchval(
                "SELECT count(*) FROM ctxdb_meta.api_keys WHERE workspace_id=$1 AND member_id=$2",
                workspace_id,
                member_id,
            )
            rows = await conn.fetch(
                "SELECT key_id,workspace_id,member_id,name,scopes,expires_at,revoked_at,created_by,created_at,last_used_at "
                "FROM ctxdb_meta.api_keys WHERE workspace_id=$1 AND member_id=$2 "
                "ORDER BY created_at,key_id LIMIT $3 OFFSET $4",
                workspace_id,
                member_id,
                limit,
                offset,
            )
            return Page[KeyMetadata](
                items=[KeyMetadata.model_validate(dict(row)) for row in rows], total=total, limit=limit, offset=offset
            )

    async def revoke_key(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        member_id: str,
        key_id: str,
        request_id: str,
    ) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            await self._workspace(conn, principal, workspace_id, target_member_id=member_id)
            await self._member(conn, workspace_id, member_id)
            row = await conn.fetchrow(
                "UPDATE ctxdb_meta.api_keys SET revoked_at=COALESCE(revoked_at,now()) "
                "WHERE workspace_id=$1 AND member_id=$2 AND key_id=$3 RETURNING key_id",
                workspace_id,
                member_id,
                key_id,
            )
            if row is None:
                raise ServiceError(404, "not_found", "Key not found")
            await self._audit(
                conn, principal, request_id, "revoke_key", workspace_id=workspace_id, member_id=member_id, key_id=key_id
            )

    async def authenticate(self, credential: str | None, *, record_use: bool = False) -> BusinessPrincipal:
        key_id = user_key_id(credential)
        if key_id is None or credential is None:
            raise ServiceError(401, "invalid_key", "A valid member Key is required")
        row = await self.pool.fetchrow(
            "SELECT k.key_id,k.member_id,k.workspace_id,k.digest,k.scopes,w.schema_name "
            "FROM ctxdb_meta.api_keys k JOIN ctxdb_meta.workspace_members m "
            "ON m.workspace_id=k.workspace_id AND m.member_id=k.member_id "
            "JOIN ctxdb_meta.workspaces w ON w.workspace_id=k.workspace_id "
            "WHERE k.key_id=$1 AND k.revoked_at IS NULL AND k.expires_at>now() "
            "AND m.status='active' AND w.state='active' AND w.instance_id=$2 AND w.cloud_tenant_id=$3",
            key_id,
            self.instance_id,
            self.cloud_tenant_id,
        )
        expected = row["digest"] if row else bytes(32)
        valid = hmac.compare_digest(key_digest(credential, self.pepper), expected)
        if row is None or not valid:
            raise ServiceError(401, "invalid_key", "A valid member Key is required")
        if record_use:
            # Only the transport/tenant authentication records use. Operation
            # validators may recheck state several times but do not amplify writes.
            await self.pool.execute("UPDATE ctxdb_meta.api_keys SET last_used_at=now() WHERE key_id=$1", key_id)
        return BusinessPrincipal(
            row["key_id"],
            row["member_id"],
            row["workspace_id"],
            row["schema_name"],
            frozenset(Scope(scope) for scope in row["scopes"]),
        )

    async def worker_workspaces(self) -> list[Workspace]:
        return await self.discover_workspaces(self.pool, self.instance_id, self.cloud_tenant_id)

    @staticmethod
    async def discover_workspaces(
        reader: asyncpg.Pool | asyncpg.Connection,
        instance_id: str,
        cloud_tenant_id: str,
    ) -> list[Workspace]:
        # Standalone worker entrypoints do not invoke every extension startup hook.
        # Discovery must fail closed on a missing/unknown metadata version too.
        versions = await reader.fetch("SELECT version FROM ctxdb_meta.schema_versions ORDER BY version")
        if [row["version"] for row in versions] != [1]:
            raise RuntimeError("Unsupported ContextDB metadata schema; run the deployment migration first")
        rows = await reader.fetch(
            "SELECT * FROM ctxdb_meta.workspaces WHERE instance_id=$1 AND cloud_tenant_id=$2 "
            "AND state IN ('active','frozen','deleting') ORDER BY workspace_id",
            instance_id,
            cloud_tenant_id,
        )
        return [Workspace.model_validate(dict(row)) for row in rows]

    async def internal_workspace(self, bank_id: str, schema_name: str) -> Workspace:
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 "
            "AND instance_id=$3 AND cloud_tenant_id=$4 AND state<>'deleted'",
            bank_id,
            schema_name,
            self.instance_id,
            self.cloud_tenant_id,
        )
        if row is None:
            raise ServiceError(403, "internal_scope", "Internal operation does not match a registered workspace")
        return Workspace.model_validate(dict(row))

    async def maintenance_workspace(self, schema_name: str) -> Workspace | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE schema_name=$1 AND instance_id=$2 "
            "AND cloud_tenant_id=$3 AND state='active'",
            schema_name,
            self.instance_id,
            self.cloud_tenant_id,
        )
        return Workspace.model_validate(dict(row)) if row else None

    async def register_admission(
        self, admission_id: str, owner_id: str, workspace_id: str, schema: str, origin: str
    ) -> None:
        """Persist before work starts, serialized with the workspace close gate.

        The caller still checks HTTP/queue-specific state under its regular
        admission lock. This short transaction must commit before that caller
        opens an engine transaction; it is not a lease or a substitute for auth.
        """
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 "
                "AND instance_id=$3 AND cloud_tenant_id=$4 FOR KEY SHARE",
                workspace_id,
                schema,
                self.instance_id,
                self.cloud_tenant_id,
            )
            if row is None or row["state"] == "deleted":
                raise ServiceError(409, "admission_closed", "Workspace admission is closed")
            await conn.execute(
                "INSERT INTO ctxdb_meta.request_admissions "
                "(admission_id,instance_id,workspace_id,owner_id,origin) VALUES ($1,$2,$3,$4,$5)",
                admission_id,
                self.instance_id,
                workspace_id,
                owner_id,
                origin,
            )

    async def finish_admission(self, admission_id: str, owner_id: str, *, interrupted: bool) -> None:
        # Interrupted/unknown work is deliberately NOT reclaimed on a timer.
        # Operator recovery requires proof the old API/Worker and its work
        # sessions are stopped. Normal completion removes only its own record.
        query = (
            "UPDATE ctxdb_meta.request_admissions SET state='interrupted' "
            if interrupted
            else "DELETE FROM ctxdb_meta.request_admissions "
        )
        await self.pool.execute(
            query + "WHERE admission_id=$1 AND owner_id=$2 AND instance_id=$3",
            admission_id,
            owner_id,
            self.instance_id,
        )

    async def has_outstanding_admissions(self, workspace_id: str) -> bool:
        return bool(
            await self.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM ctxdb_meta.request_admissions WHERE workspace_id=$1 AND instance_id=$2)",
                workspace_id,
                self.instance_id,
            )
        )

    async def get_operation(self, principal: ControlPrincipal, operation_id: str) -> ManagementOperation:
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE operation_id=$1 AND instance_id=$2",
                operation_id,
                self.instance_id,
            )
            if row is None:
                raise ServiceError(404, "not_found", "Operation not found")
            # The initial creator can inspect their own failed/create/delete task;
            # a removed member must not inherit another actor's historical task.
            if row["actor_subject"] != principal.actor_subject:
                await self._workspace(conn, principal, row["workspace_id"], admin=True)
            self._tenant(principal)
            return ManagementOperation.model_validate(dict(row))

    async def delete_workspace(
        self,
        principal: ControlPrincipal,
        workspace_id: str,
        idempotency_key: str,
        request_id: str,
    ) -> ManagementOperation:
        self._tenant(principal)
        async with self.pool.acquire() as conn, conn.transaction():
            # Serialize before reading the idempotency record: concurrent first
            # DELETEs otherwise both observe absence and the loser sees deleting.
            # Keep the historical row lockable after deletion, so retries still
            # replay the original task without treating deleted as a new target.
            locked = await conn.fetchrow(
                "SELECT workspace_id FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND instance_id=$2 "
                "AND cloud_tenant_id=$3 FOR UPDATE",
                workspace_id,
                self.instance_id,
                self.cloud_tenant_id,
            )
            if locked is None:
                raise ServiceError(404, "not_found", "Workspace not found")
            old = await conn.fetchrow(
                "SELECT * FROM ctxdb_meta.management_operations WHERE instance_id=$1 AND workspace_id=$2 "
                "AND actor_subject=$3 AND action='delete_workspace' AND idempotency_key=$4",
                self.instance_id,
                workspace_id,
                principal.actor_subject,
                idempotency_key,
            )
            if old:
                if old["state"] == "failed":
                    await self._workspace(conn, principal, workspace_id, admin=True)
                    old = await self._restart_operation(conn, old)
                return ManagementOperation.model_validate(dict(old))
            workspace = await self._workspace(conn, principal, workspace_id, admin=True)
            if workspace.state not in {"active", "frozen", "failed"}:
                raise ServiceError(409, "workspace_state", "Workspace cannot be deleted in its current state")
            # Deletion must not race a previous create/migration lease. A failed
            # create may be retried, but it must not activate a space after delete.
            running = await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.management_operations WHERE workspace_id=$1 AND state IN ('pending','running')",
                workspace_id,
            )
            if running:
                raise ServiceError(409, "operation_in_progress", "A workspace operation is already in progress")
            await conn.execute(
                "UPDATE ctxdb_meta.workspaces SET state='deleting',version=version+1 WHERE workspace_id=$1",
                workspace_id,
            )
            row = await conn.fetchrow(
                "INSERT INTO ctxdb_meta.management_operations "
                "(operation_id,workspace_id,instance_id,actor_subject,action,target_id,idempotency_key,request_hash,"
                "workspace_version) VALUES ($1,$2,$3,$4,'delete_workspace',$2,$5,$6,$7) RETURNING *",
                secrets.token_hex(16),
                workspace_id,
                self.instance_id,
                principal.actor_subject,
                idempotency_key,
                request_hash(workspace_id),
                workspace.version + 1,
            )
            await self._audit(conn, principal, request_id, "delete_workspace", workspace_id=workspace_id)
            return ManagementOperation.model_validate(dict(row))

    async def claim_operation(self) -> ManagementOperation | None:
        row = await self.pool.fetchrow(
            "WITH candidate AS (SELECT operation_id FROM ctxdb_meta.management_operations "
            "WHERE instance_id=$1 AND ((state='pending' AND (lease_until IS NULL OR lease_until<=now())) "
            "OR (state='running' AND lease_until<now())) "
            "ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1) "
            "UPDATE ctxdb_meta.management_operations o SET state='running',attempts=attempts+1,"
            "lease_token=$2,lease_until=clock_timestamp()+interval '60 seconds',updated_at=clock_timestamp() "
            "FROM candidate c WHERE o.operation_id=c.operation_id RETURNING o.*",
            self.instance_id,
            secrets.token_hex(16),
        )
        return ManagementOperation.model_validate(dict(row)) if row else None

    async def renew_operation(self, operation: ManagementOperation) -> bool:
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                return False
            value = await conn.fetchval(
                "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '60 seconds',"
                "updated_at=clock_timestamp() WHERE operation_id=$1 AND instance_id=$2 AND lease_token=$3 "
                "AND state='running' AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                self.instance_id,
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
        return (
            await conn.fetchval(
                "SELECT 1 FROM ctxdb_meta.management_operations WHERE operation_id=$1 AND instance_id=$2 "
                "AND lease_token=$3 AND state='running' AND action=$4 AND workspace_id=$5 FOR UPDATE",
                operation.operation_id,
                self.instance_id,
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
        if lock and (connection is None or not connection.is_in_transaction()):
            raise ValueError("Operation fencing requires the caller's open transaction")
        if not operation_id or not lease_token:
            return False
        binding = (
            "SELECT 1 FROM ctxdb_meta.management_operations WHERE operation_id=$1 AND instance_id=$2 "
            "AND lease_token=$3 AND action=$4 AND workspace_id=$5 AND state='running'"
        )
        reader = connection if connection is not None else self.pool
        if lock:
            # As with UPDATE, a SELECT's time predicate can be checked before
            # its row-lock wait. Acquire only the binding here, then recheck live
            # time below while the caller's short transaction owns that lock.
            if (
                await reader.fetchval(
                    binding + " FOR SHARE", operation_id, self.instance_id, lease_token, action, workspace_id
                )
                != 1
            ):
                return False
        # Unlike now(), clock_timestamp() does not freeze at transaction start:
        # an expired lease must not pass merely because a caller began earlier.
        return (
            await reader.fetchval(
                binding + " AND lease_until>clock_timestamp()",
                operation_id,
                self.instance_id,
                lease_token,
                action,
                workspace_id,
            )
            == 1
        )

    async def operation_workspace(self, operation: ManagementOperation) -> Workspace:
        row = await self.pool.fetchrow(
            "SELECT * FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND instance_id=$2 AND cloud_tenant_id=$3",
            operation.workspace_id,
            self.instance_id,
            self.cloud_tenant_id,
        )
        if row is None:
            raise ServiceError(404, "not_found", "Workspace not found")
        return Workspace.model_validate(dict(row))

    async def bank_table_exists(self, schema: str) -> bool:
        # Called only with the registered, server-generated workspace schema.
        # An initialization failure before core DDL is an empty teardown target,
        # not an UndefinedTable error which makes deletion retry forever.
        return bool(await self.pool.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.banks"))

    async def complete_operation(self, operation: ManagementOperation, *, error_code: str | None = None) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            owned = await conn.fetchval(
                "UPDATE ctxdb_meta.management_operations SET state=$4,error_code=$5,lease_until=NULL,"
                "updated_at=clock_timestamp() "
                "WHERE operation_id=$1 AND instance_id=$2 AND lease_token=$3 AND state='running' "
                "AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                self.instance_id,
                operation.lease_token,
                "failed" if error_code else "succeeded",
                error_code,
            )
            if not owned:
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            state = "failed" if error_code else "active" if operation.action == "create_workspace" else "deleted"
            await conn.execute(
                "UPDATE ctxdb_meta.workspaces SET state=$2,version=version+1 WHERE workspace_id=$1 AND instance_id=$3",
                operation.workspace_id,
                state,
                self.instance_id,
            )

    async def defer_operation(self, operation: ManagementOperation, *, reason: str | None = None) -> None:
        # A deleting space with unfinished native tasks is not an error. Leave a
        # short lease so the next sweep can retry without hot-looping immediately.
        async with self.pool.acquire() as conn, conn.transaction():
            if not await self._lock_operation(conn, operation):
                return
            await conn.execute(
                "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '2 seconds',"
                "attempts=GREATEST(attempts-1,0),error_code=$4 "
                "WHERE operation_id=$1 AND instance_id=$2 AND lease_token=$3 AND state='running' "
                "AND lease_until>clock_timestamp()",
                operation.operation_id,
                self.instance_id,
                operation.lease_token,
                reason,
            )

    async def _restart_operation(self, conn: asyncpg.Connection, old: asyncpg.Record) -> asyncpg.Record:
        workspace = await conn.fetchrow(
            "SELECT state,version FROM ctxdb_meta.workspaces WHERE workspace_id=$1", old["workspace_id"]
        )
        if workspace is None or workspace["state"] != "failed":
            raise ServiceError(409, "workspace_state", "Failed operation cannot restart after workspace state changed")
        # Completing the current task increments its workspace version once.
        # Merely testing failed is insufficient: a newer failed delete has the
        # same state as an old failed create, but a different lifecycle intent.
        if workspace["version"] != old["workspace_version"] + 1:
            raise ServiceError(409, "superseded_operation", "A newer workspace lifecycle superseded this operation")
        row = await conn.fetchrow(
            "UPDATE ctxdb_meta.management_operations SET state='pending',attempts=0,lease_token=NULL,"
            "lease_until=NULL,error_code=NULL,workspace_version=$2,updated_at=now() "
            "WHERE operation_id=$1 RETURNING *",
            old["operation_id"],
            workspace["version"] + 1,
        )
        await conn.execute(
            "UPDATE ctxdb_meta.workspaces SET state=$2,version=version+1 WHERE workspace_id=$1",
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
                "UPDATE ctxdb_meta.management_operations SET state=$4,error_code='workspace_operation_failed',"
                "lease_token=NULL,lease_until=clock_timestamp()+$5::double precision*interval '1 second',"
                "updated_at=clock_timestamp() "
                "WHERE operation_id=$1 AND instance_id=$2 AND lease_token=$3 AND state='running' "
                "AND lease_until>clock_timestamp() RETURNING 1",
                operation.operation_id,
                self.instance_id,
                operation.lease_token,
                "pending" if retry else "failed",
                float(2 ** min(operation.attempts, 3)),
            )
            if not owned:
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
            if not retry:
                await conn.execute(
                    "UPDATE ctxdb_meta.workspaces SET state='failed',version=version+1 WHERE workspace_id=$1",
                    operation.workspace_id,
                )
