"""Transport policy remains effective after removing request execution tracking."""

import json
from typing import cast
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import ApiKeyCreate, UserCreate
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.routing import target_bank
from hindsight_ext_contextdb.transport import WorkspaceAuthorizationMiddleware, _bank_config_json

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace
from .support.native_doubles import PoolHost


async def test_rest_native_hooks_reuse_one_authentication_without_holding_a_metadata_connection(repository, configured):
    workspace = await ready_workspace(repository)
    pool = repository.pool
    proxy = Mock(wraps=pool)
    proxy.fetchrow = AsyncMock(wraps=pool.fetchrow)
    repository.pool = proxy
    app = FastAPI()

    @app.get("/v1/default/banks/{bank_id}/probe")
    async def probe(bank_id: str):
        assert target_bank() == bank_id
        assert await repository.authenticate(ADMIN_SECRET, bank_id) is await repository.authenticate(
            ADMIN_SECRET, bank_id
        )
        # All pool slots remain available. There is no hidden request-long lock.
        return {"free": pool.get_idle_size()}

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(proxy)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get(
            f"/v1/default/banks/{workspace.bank_id}/probe", headers={"Authorization": ADMIN_SECRET}
        )
    assert response.status_code == 200
    assert response.json()["free"] > 0
    assert proxy.fetchrow.await_count == 1
    assert target_bank() is None


@pytest.mark.parametrize(
    "path", ["export", "transfer/export", "document-transfer/export", "audit-logs", "audit-logs/stats"]
)
async def test_business_keys_cannot_read_operator_archives_or_audit(repository, configured, path):
    workspace = await ready_workspace(repository)
    user = await repository.create_user(ADMIN, UserCreate(name="app"), "create")
    key = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="all", authorization={"mode": "all"}), "key"
    )
    app = FastAPI()

    @app.get("/v1/default/banks/{bank_id}/{tail:path}")
    async def sensitive(bank_id: str, tail: str):
        return {"secret": "OPERATOR_SENTINEL"}

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        url = f"/v1/default/banks/{workspace.bank_id}/{path}"
        response = await client.get(url, headers={"Authorization": key.secret})
        assert response.status_code == 403 and "OPERATOR_SENTINEL" not in response.text
        assert (await client.get(url, headers={"Authorization": ADMIN_SECRET})).json()["secret"] == "OPERATOR_SENTINEL"


@pytest.mark.parametrize("suffix", ["import", "clone", "transfer/import", "aliases", "aliases/other"])
async def test_even_admin_cannot_bypass_mapping_through_native_lifecycle_paths(repository, configured, suffix):
    workspace = await ready_workspace(repository)
    app = FastAPI()

    @app.post("/v1/default/banks/{bank_id}/{tail:path}")
    async def bypass(bank_id: str, tail: str):
        pytest.fail("Lifecycle bypass reached the native endpoint")

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.post(
            f"/v1/default/banks/{workspace.bank_id}/{suffix}", headers={"Authorization": ADMIN_SECRET}
        )
    assert response.status_code == 403


async def test_mcp_transport_sets_path_target_without_installing_fault_or_executor_callbacks(repository, configured):
    app = FastAPI()

    @app.post("/mcp/{bank_id}/")
    async def message(bank_id: str):
        return {"ok": True}

    async def observed(scope, receive, send):
        assert scope["contextdb.mcp_path_bank"] == "example"
        assert "hindsight.request_context_restore" not in scope
        assert "hindsight.request_context_failure" not in scope
        await app(scope, receive, send)

    wrapped = WorkspaceAuthorizationMiddleware(observed, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        assert (await client.post("/mcp/example/")).json() == {"ok": True}


@pytest.mark.parametrize(
    "visible,expected",
    [
        pytest.param({}, {}, id="no-visible-fields"),
        pytest.param(
            {"retain_chunk_size": 1800, "recall_budget_max": 500},
            {"retain_chunk_size": 1800},
            id="visible-default-is-not-an-override",
        ),
        pytest.param({"enable_observations": False}, {"enable_observations": False}, id="observations-only"),
        pytest.param(
            {"retain_chunk_size": 1800, "enable_observations": False},
            {"retain_chunk_size": 1800, "enable_observations": False},
            id="both-visible",
        ),
    ],
)
def test_config_projection_obeys_native_visible_fields(visible: dict[str, object], expected: dict[str, object]) -> None:
    payload = {
        "bank_id": "example",
        "config": visible,
        "overrides": {
            "retain_chunk_size": 1800,
            "enable_observations": False,
            "llm_api_key": "SYNTHETIC_HIDDEN_CREDENTIAL",
        },
    }
    projected = json.loads(_bank_config_json(json.dumps(payload).encode()))
    assert projected == {"bank_id": "example", "config": visible, "overrides": expected}
    # Native/default fields are not fabricated as Bank overrides.
    assert payload["overrides"]["llm_api_key"] == "SYNTHETIC_HIDDEN_CREDENTIAL"


@pytest.mark.parametrize(
    "method,member,visible",
    [
        pytest.param("GET", True, {}, id="business-read"),
        pytest.param("GET", False, {"retain_chunk_size": 1800}, id="admin-read"),
        pytest.param("PATCH", False, {"retain_chunk_size": 1800}, id="admin-update"),
        pytest.param("DELETE", False, {}, id="admin-reset"),
    ],
)
async def test_config_transport_filters_chunks_without_another_auth_query(
    repository: Repository, configured: Settings, method: str, member: bool, visible: dict[str, object]
) -> None:
    workspace = await ready_workspace(repository)
    credential = ADMIN_SECRET
    if member:
        user = await repository.create_user(ADMIN, UserCreate(name="Config reader"), "create")
        key = await repository.create_key(
            ADMIN, user.user_id, ApiKeyCreate(name="all", authorization={"mode": "all", "permission": "read"}), "key"
        )
        credential = key.secret
    proxy = Mock(wraps=repository.pool)
    proxy.fetchrow = AsyncMock(wraps=repository.pool.fetchrow)
    repository.pool = proxy
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1)

    @app.api_route("/v1/default/banks/{bank_id}/config", methods=[method])
    async def native_config(bank_id: str, request: Request) -> StreamingResponse:
        assert "accept-encoding" not in request.headers
        # The native layer may authenticate again; transport-scoped reuse must
        # still avoid another lookup, and projection must not replay any hook.
        await repository.authenticate(credential, bank_id)
        payload = json.dumps({"bank_id": bank_id, "config": visible, "overrides": {"retain_chunk_size": 1800}}).encode()
        return StreamingResponse(
            iter([payload[:20], payload[20:]]), media_type="application/json", headers={"X-Native": "kept"}
        )

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(proxy)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.request(
            method,
            f"/v1/default/banks/{workspace.bank_id}/config",
            headers={"Authorization": credential, "Accept-Encoding": "gzip"},
        )
    assert response.status_code == 200
    assert response.json() == {"bank_id": workspace.bank_id, "config": visible, "overrides": visible}
    assert response.headers["X-Native"] == "kept"
    assert "content-encoding" not in response.headers
    assert int(response.headers["content-length"]) == len(response.content)
    assert proxy.fetchrow.await_count == 1


@pytest.mark.parametrize(
    "payload,media_type",
    [
        pytest.param(b"not JSON: SYNTHETIC_HIDDEN_CREDENTIAL", "application/json", id="invalid-json"),
        pytest.param(b"[]", "application/json", id="array"),
        pytest.param(b'{"bank_id":"example","config":[]}', "application/json", id="invalid-shape"),
        pytest.param(b"SYNTHETIC_HIDDEN_CREDENTIAL", "text/plain", id="not-json-content-type"),
    ],
)
async def test_invalid_config_success_never_returns_unfiltered_body(
    repository: Repository, configured: Settings, payload: bytes, media_type: str
) -> None:
    workspace = await ready_workspace(repository)
    app = FastAPI()

    @app.get("/v1/default/banks/{bank_id}/config")
    async def native_config(bank_id: str) -> Response:
        return Response(payload, media_type=media_type)

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get(
            f"/v1/default/banks/{workspace.bank_id}/config", headers={"Authorization": ADMIN_SECRET}
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "Bank configuration response unavailable"}
    assert "SYNTHETIC_HIDDEN_CREDENTIAL" not in response.text


@pytest.mark.parametrize("status", [403, 404, 500])
async def test_config_native_errors_keep_status_body_and_headers(
    repository: Repository, configured: Settings, status: int
) -> None:
    workspace = await ready_workspace(repository)
    app = FastAPI()
    payload = b'{"detail":"Native rejection"}'

    @app.get("/v1/default/banks/{bank_id}/config")
    async def native_config(bank_id: str) -> Response:
        return Response(payload, status_code=status, media_type="application/json", headers={"X-Native": "kept"})

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get(
            f"/v1/default/banks/{workspace.bank_id}/config", headers={"Authorization": ADMIN_SECRET}
        )
    assert response.status_code == status
    assert response.content == payload
    assert response.headers["X-Native"] == "kept"


async def test_config_projection_does_not_filter_unrelated_native_responses(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    payload = {"bank_id": workspace.bank_id, "config": {}, "overrides": {"retain_chunk_size": 1800}}
    app = FastAPI()

    @app.get("/v1/default/banks/{bank_id}/probe")
    async def unrelated(bank_id: str) -> Response:
        return Response(json.dumps(payload), media_type="application/json")

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get(
            f"/v1/default/banks/{workspace.bank_id}/probe", headers={"Authorization": ADMIN_SECRET}
        )
    assert response.status_code == 200
    assert response.json() == payload


@pytest.mark.parametrize("permission", ["admin", "read", "read_write"])
async def test_chunk_route_reuses_native_codec_authorization_and_context(repository, configured, permission):
    from hindsight_api.engine.chunk_ids import build_chunk_id

    workspace = await ready_workspace(repository, "mysql_ops")
    credential = ADMIN_SECRET
    if permission != "admin":
        user = await repository.create_user(ADMIN, UserCreate(name="Chunk reader"), "user")
        issued = await repository.create_key(
            ADMIN,
            user.user_id,
            ApiKeyCreate(
                name="chunk",
                authorization={
                    "mode": "selected",
                    "workspaces": [
                        {"bank_id": workspace.bank_id, "permission": permission},
                    ],
                },
            ),
            "key",
        )
        credential = issued.secret
    chunk_id = build_chunk_id(workspace.bank_id, "doc_part_~_1", 0)
    app = FastAPI()

    @app.get("/v1/default/chunks/{requested:path}")
    async def read(requested: str):
        assert target_bank() == workspace.bank_id
        principal = await repository.authenticate(credential, target_bank())
        assert principal.schema_name == workspace.schema_name
        return {"chunk_id": requested, "bank_id": target_bank()}

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/v1/default/chunks/" + chunk_id, headers={"Authorization": credential})
    assert response.status_code == 200
    assert response.json() == {"chunk_id": chunk_id, "bank_id": workspace.bank_id}
    assert target_bank() is None


@pytest.mark.parametrize(
    "chunk_id", ["bad", "mysql_ops_doc_0", "bank_doc_x", "bank_doc_-1", "bank_doc_00", "bank__0", "bank_doc~5fx_0"]
)
async def test_ambiguous_or_malformed_chunk_ids_are_not_forwarded(repository, configured, chunk_id):
    app = FastAPI()

    @app.get("/v1/default/chunks/{requested:path}")
    async def read(requested: str):
        pytest.fail("An invalid chunk must not enter a native schema")

    wrapped = WorkspaceAuthorizationMiddleware(app, cast(MemoryEngine, PoolHost(repository.pool)), configured)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        response = await client.get("/v1/default/chunks/" + chunk_id, headers={"Authorization": ADMIN_SECRET})
    assert response.status_code == 404
    assert target_bank() is None
