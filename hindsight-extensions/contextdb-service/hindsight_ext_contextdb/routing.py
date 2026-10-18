"""Request-local Bank selection and a shared REST/MCP multi-schema list adapter."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

from hindsight_api.api.http import BankListItem, BankListResponse
from hindsight_api.models import RequestContext

from .models import ServiceError

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository

_content_clear: ContextVar[bool] = ContextVar("contextdb_content_clear", default=False)

_target_bank: ContextVar[str | None] = ContextVar("contextdb_target_bank", default=None)


_multi_bank_discovery: ContextVar[bool] = ContextVar("contextdb_multi_bank_discovery", default=False)


def is_multi_bank_discovery() -> bool:
    return _multi_bank_discovery.get()


@contextmanager
def multi_bank_discovery(enabled: bool) -> Iterator[None]:
    token = _multi_bank_discovery.set(enabled)
    try:
        yield
    finally:
        _multi_bank_discovery.reset(token)


def target_bank() -> str | None:
    return _target_bank.get()


def content_clear() -> bool:
    return _content_clear.get()


@contextmanager
def bank_target(bank_id: str, *, clear_memories: bool = False) -> Iterator[None]:
    from hindsight_api.engine.memory_engine import _current_schema

    token = _target_bank.set(bank_id)
    clear_token = _content_clear.set(clear_memories)
    # Core memoizes schema on each RequestContext. Lists use a new context for
    # each Bank and restore the caller's schema even when a nested read fails.
    schema_token = _current_schema.set(None)
    try:
        yield
    finally:
        _current_schema.reset(schema_token)
        _target_bank.reset(token)
        _content_clear.reset(clear_token)


async def bank_list(
    memory: MemoryEngine,
    repository: Repository,
    credential: str | None,
    *,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
    workspace_id: str | None = None,
) -> BankListResponse:
    if limit < 0 or offset < 0 or limit > 1000:
        raise ServiceError(400, "invalid_pagination", "limit must be 0..1000 and offset nonnegative")
    principal = await repository.authenticate(credential)
    if workspace_id is not None:
        principal = await repository.select_workspace(principal, workspace_id)
    spaces = await repository.visible_workspaces(principal)
    if workspace_id is not None:
        spaces = [space for space in spaces if space.bank_id == workspace_id]
    from hindsight_api.engine.retain import bank_utils

    catalog: list[BankListItem] = []
    backend = await memory._get_backend()
    for workspace in spaces:
        with bank_target(workspace.bank_id):
            # The native helper owns profile/watermark SQL. Authenticate a fresh
            # context per schema, then rank its lightweight rows; do not count
            # every Bank's facts or resolve every Bank's config for a small page.
            await memory._authenticate_tenant(RequestContext(api_key=credential))
            rows = await bank_utils.list_banks_among(backend, [workspace.bank_id], search_query=query)
            catalog.extend(BankListItem.model_validate(row) for row in rows)
    catalog.sort(
        key=lambda bank: (bank.last_write_at or bank.created_at or "1970-01-01T00:00:00+00:00", bank.bank_id),
        reverse=True,
    )
    banks: list[BankListItem] = []
    for item in catalog[offset : offset + limit]:
        with bank_target(item.bank_id):
            # Reauthenticate during hydration. If permissions changed, fail
            # closed rather than filling the response from the old catalog.
            page = BankListResponse.model_validate(
                await memory.list_banks(limit=1, offset=0, request_context=RequestContext(api_key=credential))
            )
            banks.extend(page.banks)
    return BankListResponse(banks=banks, total=len(catalog), limit=limit, offset=offset)
