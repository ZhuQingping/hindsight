"""Bank transport contracts over disposable PG metadata and counted engine calls."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from hindsight_api import MemoryEngine
from hindsight_api.api.http import BankTemplateManifest
from hindsight_api.config_resolver import ConfigResolver
from hindsight_api.engine.memories.base import StoreWriteUnavailable
from hindsight_api.extensions import AuthenticationError
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError

from hindsight_ext_contextdb.bank_rest import create_bank_app
from hindsight_ext_contextdb.models import ApiKeyCreate, UserCreate
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.transport import WorkspaceAuthorizationMiddleware

from ..lifecycle_http import create_workspace
from .support.identities import ADMIN, ADMIN_SECRET

PROFILE = {"name": "Display", "mission": "", "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3}}


@pytest.fixture
async def banks(management, configured):
    host = management.memory
    host.audit_logger = None
    host._config_resolver = ConfigResolver(backend=Mock())
    host._config_resolver._load_bank_config = AsyncMock(side_effect=AssertionError("No Bank exists during preflight"))
    host.update_bank.return_value = PROFILE
    host.delete_bank.return_value = {"memory_units_deleted": 2, "entities_deleted": 3, "documents_deleted": 4}
    app = create_bank_app(host, configured)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test/v1/default/banks", headers=management.headers
    ) as client:
        yield client


async def test_conditional_create_is_atomic_and_legacy_description_survives(banks, management, repository):
    responses = await asyncio.gather(
        *(banks.put("/concurrent", json={"name": "Display"}, headers={"If-None-Match": "*"}) for _ in range(2))
    )
    assert sorted(response.status_code for response in responses) == [200, 412]
    assert management.memory.update_bank.await_count == 1
    assert management.memory.tenant_extension.context.run_migration.await_count == 1
    detail = await management.client.get("/workspaces/concurrent", headers=management.headers)
    assert detail.json()["state"] == "active"
    old = await create_workspace(
        management.client, json={"name": "legacy", "description": "Keep this description"}, headers=management.headers
    )
    assert old.status_code == 200 and old.json()["description"] == "Keep this description"
    assert (await banks.put("/legacy", json={})).status_code == 200
    assert (await management.client.get("/workspaces/legacy", headers=management.headers)).json()[
        "description"
    ] == "Keep this description"


async def test_active_updates_are_external_update_only(banks, management):
    assert (await banks.put("/update", json={})).status_code == 200
    for method in (banks.put, banks.patch):
        response = await method("/update", json={"name": "Renamed", "mission": "Help"})
        assert response.status_code == 200, response.text
        call = management.memory.update_bank.call_args.kwargs
        assert call["create_if_missing"] is False and call["request_context"].internal is False
    assert management.memory.tenant_extension.context.run_migration.await_count == 1
    assert (await banks.patch("/missing", json={})).status_code == 404


@pytest.mark.parametrize("state", ["creating", "deleting", "failed"])
async def test_nonactive_put_is_not_a_retry(banks, management, repository, state):
    assert (await banks.put("/state", json={})).status_code == 200
    await repository.pool.execute("UPDATE ctxdb_meta.workspaces SET state=$1 WHERE bank_id='state'", state)
    before = management.memory.update_bank.await_count
    assert (await banks.put("/state", json={})).status_code == 409
    assert (await banks.put("/state", json={}, headers={"If-None-Match": "*"})).status_code == 412
    assert management.memory.update_bank.await_count == before


async def test_condition_parsing_and_schema_conflict(banks, repository):
    for headers in ({"If-None-Match": '"tag"'}, [("If-None-Match", "*"), ("If-None-Match", "*")]):
        assert (await banks.put("/invalid", json={}, headers=headers)).status_code == 400
    await repository.pool.execute("CREATE SCHEMA ctxdb_ws_orphan")
    response = await banks.put("/orphan", json={}, headers={"If-None-Match": "*"})
    assert response.status_code == 409 and response.json()["code"] == "schema_conflict"


async def test_delete_conditions_counts_and_same_name_recreation(banks, management):
    assert (await banks.put("/delete_me", json={})).status_code == 200
    resource = await management.client.get("/workspaces/delete_me", headers=management.headers)
    etag = resource.headers["etag"]
    assert (await banks.delete("/delete_me")).status_code == 428
    assert (await banks.delete("/delete_me", headers={"If-Match": "*"})).status_code == 400
    assert (await banks.delete("/delete_me", headers=[("If-Match", etag), ("If-Match", etag)])).status_code == 400
    assert (await banks.delete("/delete_me", headers={"If-Match": '"' + "0" * 32 + ':1"'})).status_code == 412
    with patch.object(Repository, "bank_exists", AsyncMock(return_value=True)):
        response = await banks.delete("/delete_me", headers={"If-Match": etag})
    assert response.status_code == 200 and response.json()["deleted_count"] == 9
    assert management.memory.delete_bank.await_count == 1
    assert (await banks.put("/delete_me", json={})).status_code == 200
    assert (await banks.delete("/delete_me", headers={"If-Match": etag})).status_code == 412
    assert management.memory.delete_bank.await_count == 1


async def test_auth_validation_unknown_fields_and_no_secret_echo(banks, management, repository):
    response = await banks.put("/bad_json", content="not JSON", headers={"Authorization": ""})
    assert response.status_code == 401 and ADMIN_SECRET not in response.text
    user = await repository.create_user(ADMIN, UserCreate(name="Reader"), "test")
    for permission in ("read", "read_write"):
        key = await repository.create_key(
            ADMIN,
            user.user_id,
            ApiKeyCreate(name=permission, authorization={"mode": "all", "permission": permission}),
            "test",
        )
        for method in (banks.put, banks.patch, banks.delete):
            assert (await method("/not_admin", headers={"Authorization": key.secret})).status_code == 403
    assert (await banks.put("/bad_json", content="not JSON")).status_code == 422
    response = await banks.put("/ignored?surprise=1", json={"name": "Display", "typo": "discarded"})
    assert response.status_code == 200 and "typo" in response.headers["x-ignored-params"]
    assert "surprise" in response.headers["x-ignored-params"]
    assert management.memory.update_bank.call_args.kwargs["name"] == "Display"


async def test_dispatch_preserves_trace_metrics_gzip_unknown_fields_and_audit_off(management, configured, monkeypatch):
    from hindsight_api.api import observability

    from hindsight_ext_contextdb import bank_rest

    host = management.memory
    host.audit_logger = Mock()
    host.audit_logger.should_log = AsyncMock(return_value=True)
    span_ids = []

    async def update(*args, **kwargs):
        span_ids.append(trace.get_current_span().get_span_context().trace_id)
        return PROFILE

    host.update_bank.side_effect = update
    metrics = Mock()
    metrics.record_http_request.side_effect = lambda *args: nullcontext()
    monkeypatch.setattr(observability, "get_metrics_collector", lambda: metrics)
    monkeypatch.setattr(
        bank_rest, "get_config", lambda: SimpleNamespace(gzip_min_size=1, extension_passthrough_headers=[])
    )
    native = FastAPI()

    @native.put("/v1/default/banks/{bank_id}")
    async def original(bank_id: str):
        pytest.fail("The native Bank operation must not execute a second time")

    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Match the host: instrument first, then install the extension middleware.
    FastAPIInstrumentor.instrument_app(native, tracer_provider=provider, exclude_spans=["receive", "send"])
    native.add_middleware(WorkspaceAuthorizationMiddleware, memory=cast(MemoryEngine, host), settings=configured)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=native), base_url="http://test") as client:
            response = await client.put(
                "/v1/default/banks/observed?unknown=1",
                json={"name": "Label", "extra": True},
                headers={**management.headers, "traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"},
            )
        assert response.status_code == 200
        assert response.headers["content-encoding"] == "gzip"
        assert {"unknown", "extra"} <= set(response.headers["x-ignored-params"].split(", "))
        metrics.record_http_request.assert_called_once()
        assert span_ids == [int("1" * 32, 16)]
        server_spans = [span for span in exporter.get_finished_spans() if span.kind == trace.SpanKind.SERVER]
        assert len(server_spans) == 1 and server_spans[0].context.trace_id == span_ids[0]
        host.audit_logger.should_log.assert_not_awaited()
        host.audit_logger.log_fire_and_forget.assert_not_called()
    finally:
        provider.shutdown()


@pytest.mark.parametrize("phase", ["create", "update", "delete"])
@pytest.mark.parametrize(
    "fault,status", [(RuntimeError, 500), (OSError, 500), (StoreWriteUnavailable, 503), (AuthenticationError, 401)]
)
async def test_native_errors_keep_json_status_and_retry_contract(banks, management, phase, fault, status):
    name = "fault"
    if phase != "create":
        assert (await banks.put("/" + name, json={})).status_code == 200
    if phase == "delete":
        resource = await management.client.get("/workspaces/" + name, headers=management.headers)
        management.memory.delete_bank.side_effect = fault("synthetic engine fault")
        with patch.object(Repository, "bank_exists", AsyncMock(return_value=True)):
            response = await banks.delete("/" + name, headers={"If-Match": resource.headers["etag"]})
    else:
        management.memory.update_bank.side_effect = fault("synthetic engine fault")
        response = await banks.put("/" + name, json={})
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    assert "detail" in response.json()
    assert (response.headers.get("retry-after") == "30") is (status == 503)
    if status == 500:
        assert "synthetic engine fault" not in response.text
    if status == 401:
        assert response.json()["detail"] == str(AuthenticationError("synthetic engine fault"))
    assert response.json().get("code") != "metadata_unavailable"


async def test_wrapped_store_error_and_metadata_failure_remain_distinct(banks, management):
    error = RuntimeError("wrapped")
    error.__cause__ = StoreWriteUnavailable("temporarily busy")
    management.memory.update_bank.side_effect = error
    assert (await banks.put("/wrapped", json={})).status_code == 503
    with patch.object(
        Repository, "authenticate_admin", AsyncMock(side_effect=asyncpg.PostgresError("metadata offline"))
    ):
        response = await banks.put("/metadata", json={})
    assert response.status_code == 503 and response.json()["code"] == "metadata_unavailable"


async def test_failed_bank_creation_keeps_identity_until_conditional_cleanup(banks, management):
    management.memory.tenant_extension.context.run_migration.side_effect = RuntimeError("migration failed")
    assert (await banks.put("/failed_create", json={}, headers={"If-None-Match": "*"})).status_code == 500
    snapshot = await management.client.get("/workspaces/failed_create", headers=management.headers)
    assert snapshot.status_code == 200 and snapshot.json()["state"] == "failed"
    assert (await banks.put("/failed_create", json={}, headers={"If-None-Match": "*"})).status_code == 412
    removed = await banks.delete("/failed_create", headers={"If-Match": snapshot.headers["etag"]})
    assert removed.status_code == 200 and removed.json()["deleted_count"] == 0
    assert (await management.client.get("/workspaces/failed_create", headers=management.headers)).status_code == 404


@pytest.mark.parametrize(
    "field,bad_value,status",
    [("retain_chunk_size", 0, 400), ("retain_structured_chunk_size", 0, 400), ("retain_chunk_size", "invalid", 422)],
)
async def test_invalid_creation_config_has_no_persistent_effects(
    banks, management, repository, field, bad_value, status
):
    response = await banks.put("/invalid_config", json={field: bad_value}, headers={"If-None-Match": "*"})
    assert response.status_code == status, response.text
    assert field in str(response.json()["detail"])
    detail = await management.client.get("/workspaces/invalid_config", headers=management.headers)
    assert detail.status_code == 404
    # The management API exposes identity; only PG can prove no schema was created.
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_invalid_config')") is None
    management.memory.tenant_extension.context.run_migration.assert_not_awaited()
    management.memory.update_bank.assert_not_awaited()
    assert (await banks.put("/invalid_config", json={field: 1000}, headers={"If-None-Match": "*"})).status_code == 200
    management.memory._config_resolver._load_bank_config.assert_not_awaited()


@pytest.mark.parametrize("fault", [asyncpg.CannotConnectNowError, asyncpg.InterfaceError, OSError])
@pytest.mark.parametrize(
    "operation,method",
    [
        ("create", "create_workspace"),
        ("create", "verify_workspace_schema"),
        ("create", "finish_workspace_creation"),
        ("delete", "delete_workspace"),
        ("delete", "verify_workspace_schema"),
        ("delete", "bank_exists"),
        ("delete", "finish_workspace_deletion"),
        ("update", "authenticate"),
    ],
)
async def test_lifecycle_metadata_fault_keeps_unavailable_classification(banks, management, operation, method, fault):
    headers = {}
    if operation != "create":
        assert (await banks.put("/metadata_fault", json={})).status_code == 200
        resource = await management.client.get("/workspaces/metadata_fault", headers=management.headers)
        headers = {"If-Match": resource.headers["etag"]}
    original = Repository.authenticate

    async def unavailable_target(self, credential, bank_id=None, **kwargs):
        if bank_id is not None:
            raise fault("synthetic metadata failure")
        return await original(self, credential, bank_id, **kwargs)

    injected = (
        unavailable_target if method == "authenticate" else AsyncMock(side_effect=fault("synthetic metadata failure"))
    )
    with patch.object(Repository, method, injected):
        if operation == "delete":
            response = await banks.delete("/metadata_fault", headers=headers)
        else:
            response = await banks.put("/metadata_fault", json={"name": "Display"})
    assert response.status_code == 503, response.text
    assert response.json()["code"] == "metadata_unavailable"
    assert "synthetic metadata failure" not in response.text
    assert response.json()["request_id"]


@pytest.mark.parametrize("template", ["none", "valid", "invalid-value", "invalid-schema"])
async def test_creation_preflight_projects_defaults_without_target_access(banks, management, monkeypatch, template):
    from hindsight_ext_contextdb import bank_contract

    resolver = management.memory._config_resolver
    resolver.tenant_extension = Mock(spec=type(management.memory.tenant_extension))
    resolver._persist_bank_config = AsyncMock(side_effect=AssertionError("Preflight must not persist"))
    validate = AsyncMock(wraps=resolver.validate_bank_config_updates)
    resolver.validate_bank_config_updates = validate
    manifest = BankTemplateManifest.model_validate({"version": "1", "bank": {"retain_chunk_size": 1500}})
    loader = Mock(return_value=manifest if template == "valid" else None)
    if template == "invalid-value":
        loader.side_effect = ValueError("malformed server template")
    if template == "invalid-schema":
        loader.side_effect = ValidationError.from_exception_data(
            "BankTemplateManifest", [{"type": "missing", "loc": ("version",), "input": {}}]
        )
    monkeypatch.setattr(bank_contract, "load_default_bank_template_manifest", loader)
    response = await banks.put("/projected", json={"retain_chunk_size": 1000})
    assert response.status_code == 200, response.text
    assert validate.await_count == (2 if template == "valid" else 1)
    assert validate.call_args.kwargs["projected_bank_overrides"] == (
        {"retain_chunk_size": 1500} if template == "valid" else {}
    )
    assert all(call.kwargs["check_permissions"] is False for call in validate.call_args_list)
    resolver._load_bank_config.assert_not_awaited()
    resolver._persist_bank_config.assert_not_awaited()
    # No target/context is passed: no tenant or field-permission hooks run early.
    assert not resolver.tenant_extension.mock_calls
    assert management.memory.update_bank.call_args.kwargs["config_updates"] == {"retain_chunk_size": 1000}


@pytest.mark.parametrize("phase", ["migration", "engine"])
@pytest.mark.parametrize("fault", [asyncpg.CannotConnectNowError, asyncpg.InterfaceError, OSError])
async def test_native_database_fault_is_not_reclassified_as_metadata(banks, management, phase, fault):
    target = (
        management.memory.tenant_extension.context.run_migration
        if phase == "migration"
        else management.memory.update_bank
    )
    target.side_effect = fault("synthetic native fault")
    response = await banks.put("/native_fault", json={})
    assert response.status_code == 500, response.text
    assert response.json().get("code") != "metadata_unavailable"
    assert "synthetic native fault" not in response.text
    detail = await management.client.get("/workspaces/native_fault", headers=management.headers)
    assert detail.status_code == 200 and detail.json()["state"] == "failed"


@pytest.mark.parametrize("description", ["", "普通空间描述", "界" * 512])
async def test_bank_description_is_management_metadata_with_original_creation_condition(banks, management, description):
    created = await banks.put(
        "/described",
        json={"name": "Label", "mission": "Model mission", "description": description},
        headers={"If-None-Match": "*"},
    )
    assert created.status_code == 200, created.text
    detail = await management.client.get("/workspaces/described", headers=management.headers)
    assert detail.json()["description"] == description
    assert created.headers["X-ContextDB-Workspace-ETag"] == detail.headers["etag"]
    assert "description" not in created.json()  # Native profile response remains unchanged.
    call = management.memory.update_bank.call_args.kwargs
    assert call["config_updates"]["reflect_mission"] == "Model mission"
    assert "description" not in call["config_updates"]
    assert (
        await banks.put("/described", json={"description": "other"}, headers={"If-None-Match": "*"})
    ).status_code == 412
    for method in (banks.put, banks.patch):
        assert (await method("/described", json={"description": ""})).status_code == 400
    assert (await management.client.get("/workspaces/described", headers=management.headers)).json()[
        "description"
    ] == description


@pytest.mark.parametrize("description", [None, 3, [], "界" * 513])
async def test_invalid_description_is_rejected_before_persistent_allocation(banks, management, repository, description):
    rejected = await banks.put(
        "/invalid_description", json={"description": description}, headers={"If-None-Match": "*"}
    )
    assert rejected.status_code == 422
    assert (
        await management.client.get("/workspaces/invalid_description", headers=management.headers)
    ).status_code == 404
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_invalid_description')") is None
    management.memory.update_bank.assert_not_awaited()
    management.memory.tenant_extension.context.run_migration.assert_not_awaited()


async def test_retired_workspace_write_routes_have_no_persistent_effect(management, repository):
    for method, path in (("POST", "/workspaces"), ("DELETE", "/workspaces/retired")):
        response = await management.client.request(method, path, json={"name": "retired"}, headers=management.headers)
        assert response.status_code == 405
    assert (await repository.list_workspaces(ADMIN, 10, 0)).total == 0
    management.memory.update_bank.assert_not_awaited()
    management.memory.delete_bank.assert_not_awaited()
