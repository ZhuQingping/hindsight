"""Changing the deployment brand preserves native SDK resource identities.

Both servers run the same source artifact. Only the environment name changes;
no hosted key-management extension or model call is needed by this story.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from hindsight_client import Hindsight
from hindsight_client_api import ApiClient, Configuration
from hindsight_client_api.api.product_api import ProductApi

from hindsight_system_tests.server import HindsightServer, StubServer, start_hindsight_server


@pytest.fixture(params=["agentstratum", "contextdb"])
def named_server(
    request: pytest.FixtureRequest,
    stub_server: StubServer,
    tmp_path: Path,
) -> Iterator[HindsightServer]:
    server = start_hindsight_server(
        stub_url=stub_server.url,
        log_path=tmp_path / "server.log",
        extra_env={"contextdb_name": request.param},
        database_url=os.environ.get("HINDSIGHT_BRAND_TEST_DATABASE_URL"),
    )
    try:
        yield server
    finally:
        server.stop()


async def test_brand_and_native_sdk_work_without_hosted_management(
    named_server: HindsightServer,
    request: pytest.FixtureRequest,
) -> None:
    name = request.node.callspec.params["named_server"]
    async with ApiClient(Configuration(host=named_server.url)) as transport:
        result = await ProductApi(transport).get_product_config_product_config_get_with_http_info()
        assert result.status_code == 200
        assert {key.lower(): value for key, value in result.headers.items()}["cache-control"] == "no-store"
        assert result.data.to_dict() == {"product_config_version": 1, "contextdb_name": name}

    client = Hindsight(base_url=named_server.url)
    bank_id = f"systest-brand-{uuid4().hex[:12]}"
    try:
        created = await client.acreate_bank(bank_id)
        assert created.bank_id == bank_id
        listed = await client.banks.list_banks()
        assert bank_id in {bank.bank_id for bank in listed.banks}
        models = await client.alist_mental_models(bank_id)
        assert models.items == []
    finally:
        try:
            await client.banks.delete_bank(bank_id)
        finally:
            await client.aclose()
