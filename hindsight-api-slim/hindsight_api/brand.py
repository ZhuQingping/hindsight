"""Public product identity; Python package and SDK identifiers stay internal."""

from typing import Literal

from .product_config import product_config

PRODUCT_NAME = "agentstratum"
WEBHOOK_EVENT_HEADER = "X-Agentstratum-Event"
WEBHOOK_SIGNATURE_HEADER = "X-Agentstratum-Signature"
WEBHOOK_SIGNATURE_V2_HEADER = "X-Agentstratum-Signature-V2"
RERANKER_BANK_HEADER = "X-Agentstratum-Bank-Id"


def api_title() -> str:
    """Deployment display identity; installation/protocol tokens stay fixed."""
    return f"{product_config().contextdb_name} HTTP API"


def service_name(kind: Literal["api", "worker"]) -> str:
    return f"{product_config().contextdb_name}-{kind}"


def mcp_server_name() -> str:
    return f"{product_config().contextdb_name}-mcp-server"
