"""Test-only MCP lifecycle trace; never logs arguments or authentication data."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from hindsight_api import MemoryEngine
from hindsight_api.extensions.mcp import MCPExtension

logger = logging.getLogger("contextdb.cancellation.probe")


class CancellationTrace(Middleware):
    def __init__(self) -> None:
        self.trace_id = os.environ["CONTEXTDB_TEST_CANCEL_TRACE_ID"]

    async def on_call_tool(self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]) -> Any:
        name = context.message.name
        logger.info("ContextDB test tool %s %s started", self.trace_id, name)
        try:
            return await call_next(context)
        except asyncio.CancelledError:
            logger.info("ContextDB test tool %s %s cancelled", self.trace_id, name)
            raise
        finally:
            logger.info("ContextDB test tool %s %s exited", self.trace_id, name)


class CancellationProbe(MCPExtension):
    def register_tools(self, mcp: FastMCP, memory: MemoryEngine) -> None:
        # Observe the real public tools; do not add a writable test-only tool or
        # change retain's asynchronous contract to manufacture an HTTP hold.
        mcp.add_middleware(CancellationTrace())
