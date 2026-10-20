"""Thin pytest adapters around independently testable resource owners."""

from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from hindsight_client_api.models.create_knowledge_page_response import (
    CreateKnowledgePageResponse,
)
from hindsight_system_tests import LLMStub
from hindsight_system_tests.server import StubServer

from ..paths import ROOT
from .support.clients import MemberClients, clients_owner
from .support.deployment import ContextDBDeployment, DeploymentOptions, deployment_owner
from .support.knowledge import create_nonempty_page
from .support.ui import AdminUI, ui_owner


@pytest.fixture(scope="session", params=["embedded-worker", "standalone-worker"])
def contextdb_deployment(
    request: pytest.FixtureRequest, stub_server: StubServer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[ContextDBDeployment]:
    with deployment_owner(
        DeploymentOptions(worker_mode=request.param), stub_server.url, tmp_path_factory.mktemp("contextdb-blackbox")
    ) as deployment:
        yield deployment


@pytest.fixture
async def contextdb_clients(contextdb_deployment: ContextDBDeployment) -> AsyncIterator[MemberClients]:
    async with clients_owner(contextdb_deployment) as clients:
        yield clients


@pytest.fixture
async def nonempty_page(contextdb_clients: MemberClients, llm: LLMStub) -> CreateKnowledgePageResponse:
    return await create_nonempty_page(contextdb_clients, llm)


@pytest.fixture(scope="session")
def contextdb_admin_ui(
    contextdb_deployment: ContextDBDeployment, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AdminUI]:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "hindsight-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the production UI and configure CONTEXTDB_UI_SERVER / CONTEXTDB_TEST_NODE_BIN")
    with ui_owner(contextdb_deployment, server, node, tmp_path_factory.mktemp("contextdb-production-ui")) as ui:
        yield ui
