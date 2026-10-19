"""Non-secret deployment naming. Display names never select data or credentials."""

import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .brand_defaults import DEPLOYMENT_SLUG, DISPLAY_NAME, LEGACY_SLUG


class ProductConfig(BaseModel):
    """Unchanged v1 wire contract for existing strict clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_config_version: Literal[1] = 1
    contextdb_name: str = Field(default=LEGACY_SLUG, pattern=r"^[a-z][a-z0-9-]{0,39}$", max_length=40)


class DisplayConfig(BaseModel):
    """Versioned display contract; the slug retains its original validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    product_config_version: Literal[2] = 2
    contextdb_name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$", max_length=40)
    # Restrict to header-safe printable names: X-Product-Name guards old tabs.
    # No trimming/case folding; Python and TypeScript enforce the same grammar.
    display_name: str = Field(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9 ._-]{0,78}[A-Za-z0-9])?$", max_length=80)


def product_config() -> ProductConfig:
    return ProductConfig(contextdb_name=os.environ.get("contextdb_name", DEPLOYMENT_SLUG))


def display_config() -> DisplayConfig:
    legacy = os.environ.get("contextdb_name")
    return DisplayConfig(
        contextdb_name=product_config().contextdb_name,
        display_name=os.environ.get("product_display_name", legacy if legacy is not None else DISPLAY_NAME),
    )
