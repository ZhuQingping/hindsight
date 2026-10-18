"""Synthetic credential sentinels cover REST/MCP diagnostic projection."""

import json

import mcp.types as mt
import pytest
from fastmcp.tools.base import ToolResult
from hindsight_ext_contextdb.admission import _include_payload
from hindsight_ext_contextdb.diagnostics import business_operation_json
from hindsight_ext_contextdb.mcp import _business_status_result
from hindsight_ext_contextdb.models import ServiceError


@pytest.mark.parametrize("value", ["true", "1", "on", "yes", "TRUE", "TrUe", "%74rue", "%6fn", "YES"])
def test_native_bool_truthy_decoding(value):
    assert _include_payload({"query_string": f"include_payload={value}".encode()})


@pytest.mark.parametrize("value", ["false", "0", "off", "no", "FALSE", "%66alse"])
def test_native_bool_false_decoding(value):
    assert not _include_payload({"query_string": f"include_payload={value}".encode()})


@pytest.mark.parametrize(
    "query",
    [
        "include_payload=",
        "include_payload=wat",
        "include_payload=true&include_payload=false",
        "include_payload=false&%69nclude_payload=true",
    ],
)
def test_ambiguous_or_invalid_diagnostic_query(query):
    with pytest.raises(ServiceError) as error:
        _include_payload({"query_string": query.encode()})
    assert error.value.status == 400


def diagnostic_payload():
    return {
        "operations": [
            {
                "operation_type": "webhook_delivery",
                "status": "failed",
                "task_payload": {"secret": "SIGNING_SENTINEL"},
                "result_metadata": {"body": "AUTH_SENTINEL"},
                "error_message": "AUTH_SENTINEL",
                "details": {"credential": "AUTH_SENTINEL"},
            },
            {
                "operation_type": "batch_retain",
                "status": "completed",
                "result_metadata": {"document_id": "business-result"},
                "error_message": None,
            },
        ],
        "total": 2,
        "limit": 20,
        "offset": 0,
    }


def test_only_webhook_diagnostics_are_projected():
    payload = diagnostic_payload()
    result = business_operation_json(json.dumps(payload))
    assert "SENTINEL" not in result
    decoded = json.loads(result)
    assert decoded["total"] == 2
    assert decoded["operations"][0]["status"] == "failed"
    assert decoded["operations"][0]["result_metadata"] is None
    assert decoded["operations"][1] == payload["operations"][1]


@pytest.mark.parametrize("multi_bank", [True, False])
def test_mcp_text_and_structured_content_have_identical_safe_status(multi_bank):
    payload = diagnostic_payload()
    text = json.dumps(payload)
    result = ToolResult(
        content=[mt.TextContent(type="text", text=text)], structured_content={"result": text} if multi_bank else payload
    )
    safe = _business_status_result(result)
    assert "SENTINEL" not in str(safe.content) + str(safe.structured_content)
    assert "business-result" in str(safe.content) + str(safe.structured_content)


@pytest.mark.parametrize("permission", ["read", "read_write"])
async def test_rest_gate_and_projection_on_synthetic_task(permission, monkeypatch, caplog):
    from contextlib import asynccontextmanager
    from dataclasses import dataclass
    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI
    from hindsight_ext_contextdb import admission
    from hindsight_ext_contextdb.admission import AdmittedRequest, WorkspaceAdmissionMiddleware
    from hindsight_ext_contextdb.models import Role

    bank = "a" * 32
    operator = "synthetic-admin"

    class SyntheticRepository:
        async def authenticate(self, credential, bank_id):
            return SimpleNamespace(role=Role.ADMIN if credential == operator else Role.MEMBER)

        async def authenticate_admin(self, credential):
            if credential != operator:
                raise ServiceError(403, "admin_required", "The operations administrator Key is required")

    async def repository_for(memory, settings):
        return SyntheticRepository()

    monkeypatch.setattr(admission, "repository_for", repository_for)

    @dataclass
    class SyntheticGuard:
        memory: object = None
        settings: object = None

        @asynccontextmanager
        async def enter(self, credential, bank_id):
            yield AdmittedRequest("ctxdb_ws_" + bank_id, bank_id)

    app = FastAPI()
    from starlette.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=0)
    task = diagnostic_payload()["operations"][0]

    @app.get("/v1/default/banks/{bank_id}/operations/{operation_id}")
    async def status(bank_id: str, operation_id: str, include_payload: bool = False):
        return {**task, "operation_id": operation_id, "task_payload": task["task_payload"] if include_payload else None}

    @app.get("/v1/default/banks/{bank_id}/operations")
    async def listing(bank_id: str):
        return diagnostic_payload()

    @app.get("/v1/default/banks/{bank_id}/audit-logs")
    async def audit(bank_id: str):
        return {"request": {"secret": "SIGNING_SENTINEL"}}

    url = f"/v1/default/banks/{bank}/operations/op"
    wrapped = WorkspaceAdmissionMiddleware(app, SyntheticGuard())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=wrapped), base_url="http://test") as client:
        for truth in ("true", "1", "yes", "on", "TrUe", "%74rue", "%6fn"):
            denied = await client.get(url + "?include_payload=" + truth, headers={"Authorization": permission})
            assert denied.status_code == 403
            assert "SENTINEL" not in denied.text
        for false in (None, "false", "0", "off", "no", "%66alse"):
            response = await client.get(
                url + ("?include_payload=" + false if false else ""), headers={"Authorization": permission}
            )
            assert response.status_code == 200
            assert "SENTINEL" not in response.text
            assert response.json()["status"] == "failed"
            assert int(response.headers["Content-Length"]) == len(response.content)
        for query in ("true&include_payload=false", "false&include_payload=true", "wat", ""):
            response = await client.get(url + "?include_payload=" + query, headers={"Authorization": permission})
            assert response.status_code == 400
            assert "SENTINEL" not in response.text
        response = await client.get(url + "?include_payload=true", headers={"Authorization": operator})
        assert response.status_code == 200 and "SIGNING_SENTINEL" in response.text and "AUTH_SENTINEL" in response.text
        response = await client.get(f"/v1/default/banks/{bank}/operations", headers={"Authorization": permission})
        assert "SENTINEL" not in response.text and "business-result" in response.text
        assert (
            await client.get(f"/v1/default/banks/{bank}/audit-logs", headers={"Authorization": permission})
        ).status_code == 403
        assert (
            "SIGNING_SENTINEL"
            in (await client.get(f"/v1/default/banks/{bank}/audit-logs", headers={"Authorization": operator})).text
        )
    assert "SENTINEL" not in caplog.text
