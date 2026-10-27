"""Versioned display discovery through the generated SDK, with stable native identities."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from contextbase_client import ContextBase
from contextbase_client_api import ApiClient, Configuration
from contextbase_client_api.api.product_api import ProductApi
from hindsight_system_tests.server import HindsightServer, StubServer, start_hindsight_server


@pytest.fixture(params=["ContextBase", "Atlas Grove"])
def display_server(
    request: pytest.FixtureRequest, stub_server: StubServer, tmp_path: Path
) -> Iterator[HindsightServer]:
    server = start_hindsight_server(
        stub_url=stub_server.url,
        log_path=tmp_path / "server.log",
        extra_env={"contextdb_name": "contextbase", "product_display_name": request.param},
        database_url=os.environ.get("HINDSIGHT_BRAND_TEST_DATABASE_URL"),
    )
    try:
        yield server
    finally:
        server.stop()


async def test_display_v2_keeps_v1_and_customer_ids(
    display_server: HindsightServer, request: pytest.FixtureRequest
) -> None:
    name = request.node.callspec.params["display_server"]
    async with ApiClient(Configuration(host=display_server.url)) as transport:
        api = ProductApi(transport)
        legacy = await api.get_product_config_product_config_get_with_http_info()
        assert legacy.data.to_dict() == {"product_config_version": 1, "contextdb_name": "contextbase"}
        display = await api.get_display_config_product_config_v2_get_with_http_info()
        assert display.data.to_dict() == {
            "product_config_version": 2,
            "contextdb_name": "contextbase",
            "display_name": name,
        }
        assert {key.lower(): value for key, value in display.headers.items()}["cache-control"] == "no-store"
    client = ContextBase(base_url=display_server.url)
    bank_id = f"agentstratum-contextbase-hindsight-中文-{uuid4().hex[:8]}"
    try:
        created = await client.acreate_bank(bank_id, name="agentstratum/contextbase/hindsight")
        assert created.bank_id == bank_id
        listing = await client.banks.list_banks(q=bank_id)
        saved = next(bank for bank in listing.banks if bank.bank_id == bank_id)
        assert saved.name == "agentstratum/contextbase/hindsight"
    finally:
        try:
            await client.banks.delete_bank(bank_id)
        finally:
            await client.aclose()
