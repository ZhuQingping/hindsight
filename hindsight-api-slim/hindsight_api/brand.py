"""Public product identity; Python package and SDK identifiers stay internal."""

import os
from typing import Literal

from .brand_defaults import (
    PRODUCT_NAME as PRODUCT_NAME,
)
from .brand_defaults import (
    RERANKER_BANK_HEADER as RERANKER_BANK_HEADER,
)
from .brand_defaults import (
    WEBHOOK_EVENT_HEADER as WEBHOOK_EVENT_HEADER,
)
from .brand_defaults import (
    WEBHOOK_SIGNATURE_HEADER as WEBHOOK_SIGNATURE_HEADER,
)
from .brand_defaults import (
    WEBHOOK_SIGNATURE_V2_HEADER as WEBHOOK_SIGNATURE_V2_HEADER,
)
from .product_config import ProductConfig, display_config


def api_title() -> str:
    """Deployment display identity; installation/protocol tokens stay fixed."""
    return f"{display_config().display_name} HTTP API"


def service_name(kind: Literal["api", "worker"]) -> str:
    """Stable telemetry resource identity; display overrides must not split monitoring history.

    Explicit legacy slugs retain their existing service-name behavior. A new display-only
    deployment keeps the compatibility identity, while banners/titles use display_config.
    """
    identity = ProductConfig(contextdb_name=os.environ.get("contextdb_name", PRODUCT_NAME))
    return f"{identity.contextdb_name}-{kind}"


def mcp_server_name() -> str:
    return f"{display_config().display_name}-mcp-server"
