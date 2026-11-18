"""Rerank contract and throttling on local HTTP only; no real model calls."""

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

spec = importlib.util.spec_from_file_location("rerank_preview_test", Path(__file__).parents[1] / "rerank_preview.py")
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)


@pytest.mark.asyncio
async def test_rerank_requests_are_serial_paced_and_secret_free(tmp_path: Path) -> None:
    starts = []
    active = 0
    maximum = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal active, maximum
        assert request.headers["Authorization"] == "Bearer TEST_ONLY_SECRET"
        body = await request.json()
        assert set(body) == {"model", "query", "documents"}
        starts.append(time.monotonic())
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.005)
        active -= 1
        return web.json_response(
            {
                "id": "fixture",
                "model": body["model"],
                "usage": {"total_tokens": 10},
                "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}],
            }
        )

    app = web.Application()
    app.router.add_post("/rerank", handler)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            client = r.Client(session, str(server.make_url("/rerank")), "TEST_ONLY_SECRET", interval_s=0.03)
            replies = await asyncio.gather(
                *(
                    client.score(r.Request(model="fixture", query="q", documents=["a", "b"]), tmp_path / f"{i}.json")
                    for i in range(3)
                )
            )
    assert maximum == 1 and all(b - a >= 0.029 for a, b in zip(starts, starts[1:]))
    assert all(reply.results[0].index == 1 for reply in replies)
    assert all("TEST_ONLY_SECRET" not in file.read_text() for file in tmp_path.glob("*.json"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429])
async def test_auth_or_long_rate_limit_stops_without_fallback(tmp_path: Path, status: int) -> None:
    calls = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal calls
        calls += 1
        return web.json_response({"error": "TEST_ONLY_SECRET"}, status=status, headers={"Retry-After": "301"})

    app = web.Application()
    app.router.add_post("/rerank", handler)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            client = r.Client(session, str(server.make_url("/rerank")), "TEST_ONLY_SECRET", interval_s=0.01)
            with pytest.raises(RuntimeError, match=str(status)):
                await client.score(r.Request(model="fixture", query="q", documents=["a"]), tmp_path / "call.json")
    record = json.loads((tmp_path / "call.json").read_text())
    assert calls == 1 and record["attempts"][0]["http_status"] == status
    assert "TEST_ONLY_SECRET" not in (tmp_path / "call.json").read_text()


@pytest.mark.asyncio
async def test_incomplete_candidate_scores_are_rejected(tmp_path: Path) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"id": "fixture", "model": "fixture", "results": [{"index": 0, "relevance_score": 0.5}]}
        )

    app = web.Application()
    app.router.add_post("/rerank", handler)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            client = r.Client(session, str(server.make_url("/rerank")), "TEST_ONLY_SECRET", interval_s=0.01)
            with pytest.raises(ValueError, match="exactly one"):
                await client.score(r.Request(model="fixture", query="q", documents=["a", "b"]), tmp_path / "call.json")


def test_reordering_preserves_all_facts_and_original_chunk_order() -> None:
    recall = r.h.core.RecallReply(
        results=[r.h.core.Fact(id="a", text="first"), r.h.core.Fact(id="b", text="second")],
        chunks={"original": r.h.core.Chunk(text="unchanged")},
    )
    reply = r.Reply(
        id="fixture",
        model="fixture",
        results=[r.RankItem(index=1, relevance_score=0.9), r.RankItem(index=0, relevance_score=0.1)],
    )
    ranked = r.reorder(recall, reply)
    assert [f.id for f in ranked.results] == ["b", "a"]
    assert [f.id for f in recall.results] == ["a", "b"]
    assert ranked.chunks == recall.chunks
