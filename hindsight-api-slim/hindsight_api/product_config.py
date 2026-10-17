"""Non-secret deployment naming shared by the native HTTP API and MCP."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    product_config_version: Literal[1] = 1
    contextdb_name: str = Field(default="agentstratum", pattern=r"^[a-z][a-z0-9-]{0,39}$", max_length=40)


def product_config() -> ProductConfig:
    # Do not normalize: display and protocol names must use exactly the same value.
    return ProductConfig(contextdb_name=os.environ.get("contextdb_name", "agentstratum"))
