"""Real Recall HTTP handler tests with a recorded engine boundary; no DB/model calls."""

import builtins
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from hindsight_api.api.http import create_app
from hindsight_api.engine.chunk_ids import build_chunk_id
from hindsight_api.engine.response_models import ChunkInfo, MemoryFact, RecallResult


def app_fixture():
    bank = "profile_bank"
    cid = build_chunk_id(bank, "session", 0)
    raw = json.dumps(
        [
            {"speaker": "A", "dia_id": "D1:1", "text": "I have practiced art for seven years."},
            {"speaker": "B", "dia_id": "D1:2", "text": "That is wonderful."},
        ]
    )
    engine_result = RecallResult(
        results=[
            MemoryFact(id="fact1", text="A practices art.", fact_type="world", document_id="session", chunk_id=cid)
        ],
        chunks={cid: ChunkInfo(chunk_text=raw, chunk_index=0, truncated=False)},
    )
    memory = MagicMock()
    memory._operation_validator = None
    memory.audit_logger = None
    memory.resolve_bank_alias = AsyncMock(side_effect=lambda bank_id, **kwargs: bank_id)
    memory.recall_async = AsyncMock(return_value=engine_result)
    memory.attachments_for_memories = AsyncMock(return_value={})
    memory.resolve_attachments = AsyncMock(return_value={})
    memory._recall_document_dates = AsyncMock(return_value={"session": "2023-01-01T00:00:00+00:00"})
    return create_app(memory, initialize_memory=False), memory, bank, cid


@pytest.mark.asyncio
async def test_default_http_matches_explicit_default_and_never_runs_selection():
    app, memory, bank, _ = app_fixture()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = {"query": "art", "include": {"entities": None, "chunks": {}}}
        before = await client.post(f"/v1/default/banks/{bank}/memories/recall", json=body)
        after = await client.post(
            f"/v1/default/banks/{bank}/memories/recall", json={**body, "recall_profile": "default"}
        )
    assert before.status_code == after.status_code == 200, (before.text, after.text)
    assert before.json() == after.json()
    baseline = json.loads((Path(__file__).parent / "fixtures/recall-default-before-profile.json").read_text())
    assert before.json() == baseline["response"]
    assert "recall_context" not in before.json()
    memory._recall_document_dates.assert_not_called()
    assert memory.recall_async.await_args.kwargs["include_chunks"] is True
    assert memory.recall_async.await_args.kwargs["max_chunk_tokens"] == 8192


@pytest.mark.asyncio
async def test_locomo_http_only_returns_selected_context_and_keeps_facts():
    app, memory, bank, cid = app_fixture()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/v1/default/banks/{bank}/memories/recall",
            json={
                "query": "How long art?",
                "max_tokens": 8192,
                "recall_profile": "locomo",
                "include": {"entities": None},
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()
    packed = body["recall_context"]
    assert packed["profile"] == "locomo" and packed["version"] == "message_windows_v1"
    assert "seven years" in packed["text"]
    assert packed["included_chunk_ids"] == [cid]
    assert body.get("chunks") is None and body["results"][0]["id"] == "fact1"
    assert packed["tokens"] <= 8192 and packed["chunk_tokens"] <= 4000
    assert memory.recall_async.await_args.kwargs["max_chunk_tokens"] == 65536
    assert memory.recall_async.await_args.kwargs["max_tokens"] == 8192
    assert memory._recall_document_dates.await_args.args == (bank, ["session"])


@pytest.mark.asyncio
async def test_optional_selector_dependency_is_not_required_for_default(monkeypatch):
    app, memory, bank, _ = app_fixture()
    original_import = builtins.__import__

    def without_selector(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "hindsight_api.engine.recall_profiles" and "locomo" in fromlist:
            raise ImportError("optional dependency unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_selector)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        default = await client.post(f"/v1/default/banks/{bank}/memories/recall", json={"query": "art"})
        memory.recall_async.reset_mock()
        profile = await client.post(
            f"/v1/default/banks/{bank}/memories/recall", json={"query": "art", "recall_profile": "locomo"}
        )
    assert default.status_code == 200
    assert profile.status_code == 503
    memory.recall_async.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra",
    [
        {"recall_profile": "beam"},
        {"recall_profile": "typo"},
        {"recall_profile": "locomo", "query": " "},
        {"recall_profile": "locomo", "include": {"chunks": {}}},
    ],
)
async def test_profile_errors_do_not_call_retrieval(extra):
    app, memory, bank, _ = app_fixture()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(f"/v1/default/banks/{bank}/memories/recall", json={"query": "art", **extra})
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)
    memory.recall_async.assert_not_called()


@pytest.mark.asyncio
async def test_missing_session_date_is_not_replaced_with_ingestion_time():
    app, memory, bank, _ = app_fixture()
    memory._recall_document_dates.side_effect = ValueError("locomo requires a retained event_date")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/default/banks/{bank}/memories/recall", json={"query": "art", "recall_profile": "locomo"}
        )
    assert response.status_code == 422, response.text
    assert "recall_context" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("stamp", [None, "", "2023-01-01T00:00:00", "invalid"])
async def test_native_date_reader_rejects_missing_or_naive_dates(monkeypatch, stamp):
    from contextlib import asynccontextmanager

    from hindsight_api.engine import memories, memory_engine
    from hindsight_api.models import RequestContext

    memory = memory_engine.MemoryEngine.__new__(memory_engine.MemoryEngine)
    memory._authenticate_tenant = AsyncMock()
    memory._tag_scope = AsyncMock(return_value=None)
    memory._get_backend = AsyncMock(return_value=MagicMock())
    memory._backend = MagicMock()
    conn = MagicMock()
    conn.parse_json.side_effect = json.loads
    store = MagicMock()
    store.get_document_with_counts = AsyncMock(
        return_value={
            "tags": [],
            "retain_params": json.dumps({"event_date": stamp}),
            "created_at": "2099-01-01T00:00:00+00:00",
        }
    )

    @asynccontextmanager
    async def acquire(_):
        yield conn

    monkeypatch.setattr(memory_engine, "acquire_with_retry", acquire)
    monkeypatch.setattr(memories, "get_memories", lambda: store)
    with pytest.raises(ValueError):
        await memory._recall_document_dates("bank", ["doc"], request_context=RequestContext())
    memory._authenticate_tenant.assert_awaited_once()
    assert store.get_document_with_counts.await_args.kwargs["bank_id"] == "bank"


@pytest.mark.asyncio
async def test_native_date_reader_enforces_tags_and_preserves_original_timestamp(monkeypatch):
    from contextlib import asynccontextmanager

    from hindsight_api.engine import memories, memory_engine
    from hindsight_api.engine.search.tags import TagGroupLeaf
    from hindsight_api.models import RequestContext

    memory = memory_engine.MemoryEngine.__new__(memory_engine.MemoryEngine)
    memory._authenticate_tenant = AsyncMock()
    memory._tag_scope = AsyncMock(return_value=[TagGroupLeaf(tags=["allowed"])])
    memory._get_backend = AsyncMock(return_value=MagicMock())
    memory._backend = MagicMock()
    conn = MagicMock()
    conn.parse_json.side_effect = json.loads
    stamp = "2023-01-01T00:00:00+00:00"
    row = {"tags": ["denied"], "retain_params": json.dumps({"event_date": stamp})}
    store = MagicMock()
    store.get_document_with_counts = AsyncMock(return_value=row)

    @asynccontextmanager
    async def acquire(_):
        yield conn

    monkeypatch.setattr(memory_engine, "acquire_with_retry", acquire)
    monkeypatch.setattr(memories, "get_memories", lambda: store)
    with pytest.raises(ValueError, match="scope"):
        await memory._recall_document_dates("bank", ["doc"], request_context=RequestContext())
    row["tags"] = ["allowed"]
    assert await memory._recall_document_dates("bank", ["doc", "doc"], request_context=RequestContext()) == {
        "doc": stamp
    }
    assert store.get_document_with_counts.await_count == 2


@pytest.mark.asyncio
async def test_locomo_fact_document_stays_in_scope_when_no_chunk_is_returned():
    app, memory, bank, _ = app_fixture()
    memory.recall_async.return_value.chunks = None
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/default/banks/{bank}/memories/recall", json={"query": "art", "recall_profile": "locomo"}
        )
    assert response.status_code == 200, response.text
    context = response.json()["recall_context"]
    assert json.loads(context["text"])["facts"][0]["document"] == "session"
    assert json.loads(context["text"])["chunks"] == []
    assert memory._recall_document_dates.await_args.args == (bank, ["session"])


def test_profile_response_keeps_typed_openapi_serialization_schema():
    from hindsight_api.api.http import RecallRequest, RecallResponse
    schema = RecallResponse.model_json_schema(mode="serialization")
    assert "results" in schema["properties"]
    assert "recall_context" in schema["properties"]
    assert RecallRequest(query="art").recall_profile == "default"
    assert "default" not in RecallRequest.model_json_schema()["properties"]["recall_profile"]
