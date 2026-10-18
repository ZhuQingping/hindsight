"""Route existing MCP tools by their actual Bank without rewriting native tools."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult
from hindsight_api.extensions.mcp import MCPExtension

from .admission import restore_admission
from .config import Settings, repository_for
from .diagnostics import business_operation_json
from .models import ServiceError
from .routing import bank_list, bank_target, multi_bank_discovery
from .security import bearer_credential
from .tenant import ContextDBTenantExtension

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine


class ContextDBMCPExtension(MCPExtension):
    def register_tools(self, mcp: FastMCP, memory: MemoryEngine) -> None:
        mcp.add_middleware(ContextDBMCPRouting(memory, Settings.from_environment()))


class ContextDBMCPRouting(Middleware):
    def __init__(self, memory: MemoryEngine, settings: Settings) -> None:
        self.memory = memory
        self.settings = settings

    async def on_list_tools(
        self, context: MiddlewareContext[mt.ListToolsRequest], call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]]
    ) -> Sequence[Tool]:
        from hindsight_api.api.mcp import _current_bank_id

        request = get_http_request()
        credential = bearer_credential(request.scope["headers"])
        repository = await repository_for(self.memory, self.settings)
        try:
            principal = await repository.authenticate(credential)
            spaces = await repository.visible_workspaces(principal, readable=False)
            if not spaces:
                return []
            # Native FastMCP 3 wraps list_tools outside its middleware, then
            # filters again after this ContextVar scope has exited. Keep only
            # the current HTTP message's discovery intent in its trusted scope.
            request.scope["contextdb.mcp_discovery"] = True
            default = request.scope.get("contextdb.mcp_path_bank") or spaces[0].bank_id
            token = _current_bank_id.set(default)
            try:
                with bank_target(default), multi_bank_discovery(not request.scope.get("contextdb.mcp_path_bank")):
                    return await call_next(context)
            finally:
                _current_bank_id.reset(token)
        except ServiceError as error:
            raise ToolError(error.message) from None

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        request = get_http_request()
        request.scope["contextdb.mcp_discovery"] = False
        repository = await repository_for(self.memory, self.settings)
        credential = bearer_credential(request.scope["headers"])
        try:
            # Obtain the CURRENT message's credential, never the initialize
            # task's ContextVars. Native identity restoration remains enabled.
            principal = await repository.authenticate(credential)
            if context.message.name == "list_banks":
                from pydantic import BaseModel, Field

                class ListArguments(BaseModel):
                    query: str | None = None
                    limit: int = Field(default=100, ge=0, le=1000)
                    offset: int = Field(default=0, ge=0)

                arguments = ListArguments.model_validate(context.message.arguments or {})
                page = await bank_list(
                    self.memory,
                    repository,
                    credential,
                    query=arguments.query,
                    limit=arguments.limit,
                    offset=arguments.offset,
                    workspace_id=request.scope.get("contextdb.mcp_path_bank"),
                )
                serialized = page.model_dump_json()
                # Native list_banks returns str: FastMCP 3 wraps its structured
                # output under result while retaining the JSON text content.
                return ToolResult(content=serialized, structured_content={"result": serialized})
            arguments = context.message.arguments or {}
            path_bank = request.scope.get("contextdb.mcp_path_bank")
            supplied = arguments.get("bank_id")
            if path_bank and supplied is not None and supplied != path_bank:
                raise ServiceError(403, "bank_mismatch", "Single-Bank MCP cannot switch its Bank")
            from hindsight_api.api.mcp import get_current_bank_id

            # Native multi-bank clients may provide X-Bank-Id as a session
            # default instead of repeating bank_id in each tool argument.
            bank_id = path_bank or supplied or get_current_bank_id()
            if not isinstance(bank_id, str):
                raise ServiceError(400, "bank_required", "Specify bank_id or use /mcp/{bank_id}")
            tenant = self.memory.tenant_extension
            if not isinstance(tenant, ContextDBTenantExtension) or tenant.admission_guard is None:
                raise RuntimeError("ContextDB MCP requires the transport admission extension")
            from hindsight_api.api.mcp import _current_bank_id

            with bank_target(bank_id, clear_memories=context.message.name == "clear_memories"):
                async with tenant.admission_guard.enter(credential or "", bank_id) as admitted:
                    bank_token = _current_bank_id.set(bank_id)
                    original = request.scope.get("hindsight.request_context_failure")

                    def report_failure() -> None:
                        admitted.failed = True

                    request.scope["hindsight.request_context_failure"] = report_failure
                    try:
                        with restore_admission(admitted):
                            result = await call_next(context)
                            if principal.role.value != "admin" and context.message.name in {
                                "get_operation",
                                "list_operations",
                            }:
                                return _business_status_result(result)
                            return result
                    finally:
                        _current_bank_id.reset(bank_token)
                        if original is None:
                            request.scope.pop("hindsight.request_context_failure", None)
                        else:
                            request.scope["hindsight.request_context_failure"] = original
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
