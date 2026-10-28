"""Route existing MCP tools by their actual Bank without rewriting native tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.tools.base import Tool, ToolResult
from hindsight_api.extensions.mcp import MCPExtension

from .authorization import authenticated_request
from .config import Settings, repository_for
from .database_checks import metadata_errors
from .diagnostics import business_operation_json
from .models import ServiceError
from .routing import bank_list, bank_target, multi_bank_discovery
from .security import bearer_credential
from .tenant import ContextDBTenantExtension
from .usage import record_knowledge, usage_call

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine


class ContextDBMCPExtension(MCPExtension):
    def register_tools(self, mcp: FastMCP, memory: MemoryEngine) -> None:
        ContextDBMCPRouting(memory, Settings.from_environment()).install(mcp)


class ContextDBMCPRouting:
    def __init__(self, memory: MemoryEngine, settings: Settings) -> None:
        self.memory = memory
        self.settings = settings

    def install(self, mcp: FastMCP) -> None:
        # Native list_tools filters both the inner provider result and the final
        # middleware result. The authorization scope must surround that public
        # operation, not end when on_list_tools returns. Keep the native filter.
        original_list_tools = mcp.list_tools

        async def list_tools(*, run_middleware: bool = True) -> Sequence[Tool]:
            if not run_middleware:
                return await original_list_tools(run_middleware=False)
            return await self._list_tools(lambda: original_list_tools(run_middleware=True))

        original_call_tool = mcp.call_tool

        async def call_tool(
            name: str, arguments: dict[str, Any] | None = None, **kwargs: Any
        ) -> ToolResult | mt.CreateTaskResult:
            if not kwargs.get("run_middleware", True):
                return await original_call_tool(name, arguments, **kwargs)
            # Native audit configuration is resolved outside the middleware too.
            return await self._call_tool(name, arguments or {}, lambda: original_call_tool(name, arguments, **kwargs))

        object.__setattr__(mcp, "list_tools", list_tools)
        object.__setattr__(mcp, "call_tool", call_tool)

    async def _list_tools(self, call_next: Callable[[], Awaitable[Sequence[Tool]]]) -> Sequence[Tool]:
        from hindsight_api.api.mcp import _current_bank_id

        request = get_http_request()
        credential = bearer_credential(request.scope["headers"])
        try:
            with metadata_errors():
                repository = await repository_for(self.memory, self.settings)
                principal = await repository.authenticate(credential)
                spaces = await repository.visible_workspaces(principal)
            if not spaces:
                return []
            path_bank = request.scope.get("contextdb.mcp_path_bank")
            if path_bank:
                spaces = [space for space in spaces if space.bank_id == path_bank]
            # Root discovery is the union of each authorized space's native
            # configuration ceiling AND permissions, never the first space's
            # ceiling applied to every other space. Each call is request-local.
            request.scope["contextdb.mcp_discovery"] = False
            tools: dict[str, Tool] = {}
            for workspace in spaces:
                token = _current_bank_id.set(workspace.bank_id)
                try:
                    with bank_target(workspace.bank_id, schema_name=workspace.schema_name), multi_bank_discovery(False):
                        for tool in await call_next():
                            tools.setdefault(tool.name, tool)
                finally:
                    _current_bank_id.reset(token)
            return list(tools.values())
        except ServiceError as error:
            raise ToolError(error.message) from None

    async def _call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        call_next: Callable[[], Awaitable[ToolResult | mt.CreateTaskResult]],
    ) -> ToolResult | mt.CreateTaskResult:
        request = get_http_request()
        request.scope["contextdb.mcp_discovery"] = False
        try:
            with metadata_errors():
                repository = await repository_for(self.memory, self.settings)
            credential = bearer_credential(request.scope["headers"])
            # Obtain the CURRENT message's credential, never the initialize
            # task's ContextVars. TenantExtension rechecks the HTTP credential.
            if name == "list_banks":
                from pydantic import BaseModel, Field

                class ListArguments(BaseModel):
                    query: str | None = None
                    limit: int = Field(default=100, ge=0, le=1000)
                    offset: int = Field(default=0, ge=0)

                pagination = ListArguments.model_validate(arguments)
                page = await bank_list(
                    self.memory,
                    repository,
                    credential,
                    query=pagination.query,
                    limit=pagination.limit,
                    offset=pagination.offset,
                    bank_id=request.scope.get("contextdb.mcp_path_bank"),
                )
                serialized = page.model_dump_json()
                # Native list_banks returns str: FastMCP 3 wraps its structured
                # output under result while retaining the JSON text content.
                return ToolResult(content=serialized, structured_content={"result": serialized})
            path_bank = request.scope.get("contextdb.mcp_path_bank")
            supplied = arguments.get("bank_id")
            if path_bank and supplied is not None and supplied != path_bank:
                raise ServiceError(403, "bank_mismatch", "Single-Bank MCP cannot switch its Bank")
            from hindsight_api.api.mcp import get_current_bank_id

            # Native multi-bank clients may provide X-Bank-Id as a session
            # default instead of repeating bank_id in each tool argument.
            bank_id = path_bank or supplied or request.headers.get("x-bank-id") or get_current_bank_id()
            if not isinstance(bank_id, str):
                raise ServiceError(400, "bank_required", "Specify bank_id or use /mcp/{bank_id}")
            tenant = self.memory.tenant_extension
            if not isinstance(tenant, ContextDBTenantExtension):
                raise RuntimeError("ContextDB MCP requires its tenant extension")
            with metadata_errors():
                principal = await repository.authenticate(credential, bank_id, record_use=True)
            assert credential is not None
            from hindsight_api.api.mcp import _current_bank_id

            with (
                bank_target(
                    bank_id,
                    clear_memories=name == "clear_memories",
                    schema_name=principal.schema_name,
                ),
                authenticated_request(credential, principal, bank_id, self.settings),
                usage_call(
                    self.memory,
                    principal,
                    bank_id,
                    "memory" if name == "recall" else "knowledge_page" if name == "search_knowledge_base" else None,
                ) as usage,
            ):
                bank_token = _current_bank_id.set(bank_id)
                try:
                    result = await call_next()
                    if name == "search_knowledge_base" and isinstance(result, ToolResult):
                        payload = result.structured_content
                        if payload is None:
                            texts = [block.text for block in result.content if isinstance(block, mt.TextContent)]
                            payload = texts[0] if len(texts) == 1 else None
                        record_knowledge(usage, payload)
                    if (
                        principal.role.value != "admin"
                        and name in {"get_operation", "list_operations"}
                        and isinstance(result, ToolResult)
                    ):
                        return _business_status_result(result)
                    return result
                finally:
                    _current_bank_id.reset(bank_token)
        except ServiceError as error:
            raise ToolError(error.message) from None


def _business_status_result(result: ToolResult) -> ToolResult:
    """Cover both single-bank dictionaries and multi-bank JSON-string results."""
    import json

    content = []
    try:
        for block in result.content:
            if isinstance(block, mt.TextContent):
                content.append(block.model_copy(update={"text": business_operation_json(block.text)}))
            else:
                content.append(block)
        structured = result.structured_content
        if structured is not None:
            if set(structured) == {"result"} and isinstance(structured["result"], str):
                structured = {"result": business_operation_json(structured["result"])}
            else:
                structured = json.loads(business_operation_json(json.dumps(structured)))
        return ToolResult(content=content, structured_content=structured)
    except ValueError:
        raise ToolError("Task status response unavailable") from None
