"""Synthetic identities and metadata preparation."""

from __future__ import annotations

from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    BusinessPrincipal,
    Permission,
    Role,
    User,
    UserCreate,
    Workspace,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository

ADMIN_SECRET = "ctx_admin_" + "a" * 32 + "_" + "b" * 43


ADMIN = BusinessPrincipal("a" * 32, "0" * 32, Role.ADMIN, "all", frozenset(), Permission.READ_WRITE)


async def ready_workspace(repository: Repository, name: str = "Demo") -> Workspace:
    workspace = await repository.create_workspace(ADMIN, WorkspaceCreate(name=name), "request-create")
    return await repository.finish_workspace_creation(workspace, ADMIN, "request-create")


async def admin_actor(repository: Repository) -> BusinessPrincipal:
    return await repository.authenticate_admin(ADMIN_SECRET)


async def space_user(repository: Repository, workspace_id: str, name: str = "Application") -> User:
    return await repository.create_user(await admin_actor(repository), UserCreate(name=name), "user")


def key_input(bank_id: str) -> ApiKeyCreate:
    return ApiKeyCreate(name="test", authorization={"mode": "selected", "workspaces": [{"bank_id": bank_id}]})
