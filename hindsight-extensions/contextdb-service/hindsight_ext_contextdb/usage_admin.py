"""Offline usage-table upgrade/reset; never migrates native public tables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import asyncpg

from .bootstrap import read_credential
from .config import Settings
from .environment import service_env
from .models import ServiceError
from .repository import Repository
from .usage_repository import UsageRepository, UsageTarget, upgrade_usage_table


async def maintain_usage(
    command: Literal["upgrade-usage", "reset-usage"], credential_path: Path, bank_id: str | None
) -> int:
    settings = Settings.from_environment()
    url = service_env("API_DATABASE_URL")
    if not url:
        raise ValueError("Set HINDSIGHT_API_DATABASE_URL for the deployment database")
    credential = read_credential(credential_path)
    pool = await asyncpg.create_pool(url, min_size=1, max_size=1, timeout=10)
    assert pool is not None
    try:
        directory = Repository(pool, settings.instance_id, settings.cloud_tenant_id, settings.pepper)
        await directory.verify_schema()
        principal = await directory.authenticate_admin(credential.secret)
        if command == "reset-usage":
            if bank_id is None:
                raise ValueError("reset-usage requires --bank-id")
            workspace = await directory.get_workspace_by_name(principal, bank_id)
            await UsageRepository(pool).reset(
                UsageTarget(workspace.workspace_id, workspace.bank_id, workspace.schema_name)
            )
            return 1
        count = 0
        offset = 0
        while True:
            page = await directory.list_workspaces(principal, limit=32, offset=offset)
            for workspace in page.items:
                if workspace.state not in {"creating", "active"}:
                    raise ServiceError(409, "workspace_state", "Resolve failed/deleting workspaces before upgrading")
                # Existing native schemas must already be upgraded by the normal
                # deployment procedure. This controlled offline step creates or upgrades only its own table.
                async with pool.acquire() as conn:
                    await upgrade_usage_table(conn, workspace.schema_name)
                count += 1
            offset += len(page.items)
            if not page.items or offset >= page.total:
                return count
    finally:
        await pool.close()
