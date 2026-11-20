"""External interleaved client for three verify_beam --serve-only processes.

Excludes live embedding/BGE. A fresh original response is the gold unless a
private historical --gold-dir is supplied. Never writes request or response text.
"""

import argparse
import asyncio
import hashlib
import json
import math
import random
import statistics
from datetime import datetime
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

import aiohttp
from pydantic import BaseModel
from verify_beam import Question, Questions


class Ready(BaseModel):
    endpoint: str
    pid: int
    path: str


class ChunkInclude(BaseModel):
    max_tokens: int = 8192


class RecallInclude(BaseModel):
    entities: None = None
    chunks: ChunkInclude


class TemporalWindow(BaseModel):
    start: datetime
    end: datetime


class RecallBody(BaseModel):
    query: str
    budget: str = "high"
    max_tokens: int = 12288
    query_timestamp: datetime
    include: RecallInclude
    temporal_window: TemporalWindow | None = None


def request_body(question: Question, reference_date: datetime) -> RecallBody:
    body = RecallBody(
        query=question.query,
        budget="high",
        max_tokens=12288,
        query_timestamp=reference_date,
        include=RecallInclude(entities=None, chunks=ChunkInclude(max_tokens=8192)),
    )
    if question.window:
        body.temporal_window = TemporalWindow(start=question.window[0], end=question.window[1])
    return body


class Sample(BaseModel):
    repeat: int
    question_id: str
    path: str
    http_ms: float
    response_sha256: str
    bytes: int


class Summary(BaseModel):
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float


class Report(BaseModel):
    scope: str = "Frozen-input core Recall HTTP; RRF passthrough, no live embedding/BGE or production auth layer"
    gold_source: str
    rounds: int
    warmups_excluded: int
    seed: int
    summary: dict[str, Summary]
    responses_exact: bool
    rows: list[Sample]


class Response(BaseModel):
    http_ms: float
    response_sha256: str
    bytes: int


def digest(raw: bytes) -> str:
    # Recall is an opaque JSON blob here; only object-key order is normalized.
    value = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(value.encode()).hexdigest()


async def fetch(client: aiohttp.ClientSession, endpoint: str, body: RecallBody) -> Response:
    started = perf_counter()
    async with client.post(endpoint, json=body.model_dump(mode="json", exclude_unset=True)) as response:
        raw = await response.read()
        status = response.status
    elapsed = (perf_counter() - started) * 1000
    if status != 200:
        # Do not leak server bodies or credentials into the public summary.
        raise RuntimeError(f"Recall returned HTTP {status}")
    return Response(http_ms=elapsed, response_sha256=digest(raw), bytes=len(raw))


async def run(args: argparse.Namespace) -> None:
    if args.rounds < 1 or args.warmups < 0 or args.take < 1:
        raise ValueError("Require positive rounds/take and nonnegative warmups")
    args.output_dir.mkdir(parents=True, mode=0o700, exist_ok=False)
    ready = {
        "off": Ready.model_validate_json(args.off_ready.read_text()),
        "p3": Ready.model_validate_json(args.p3_ready.read_text()),
        "new": Ready.model_validate_json(args.new_ready.read_text()),
    }
    for name, path in {"off": "legacy", "p3": "arrays", "new": "rank_json"}.items():
        parsed = urlsplit(ready[name].endpoint)
        if ready[name].path != path or parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Use matching loopback verify_beam servers only")
    data = Questions.model_validate_json((args.snapshot_dir / "queries.json").read_text())
    questions = data.queries[: args.take]
    if not questions:
        raise ValueError("No questions selected")
    key = args.api_key_file.read_text().strip()
    gold: dict[str, str] = {}
    rows: list[Sample] = []
    rng = random.Random(args.seed)
    async with aiohttp.ClientSession(
        headers={"Authorization": "Bearer " + key}, timeout=aiohttp.ClientTimeout(total=60)
    ) as client:
        # Capture original answers before measured rounds, never modify/sort the
        # original retrieval. All arrays, scores, texts and budgets stay exact.
        for question in questions:
            body = request_body(question, data.reference_date)
            if args.gold_dir:
                gold[question.id] = digest((args.gold_dir / f"{question.id}-0.json").read_bytes())
            else:
                original = await fetch(client, ready["off"].endpoint, body)
                gold[question.id] = original.response_sha256
        for repeat in range(-args.warmups, args.rounds):
            ordered = questions.copy()
            rng.shuffle(ordered)
            for question in ordered:
                body = request_body(question, data.reference_date)
                order = list(ready)
                rng.shuffle(order)
                for name in order:
                    result = await fetch(client, ready[name].endpoint, body)
                    if result.response_sha256 != gold[question.id]:
                        raise RuntimeError(f"Response differs: {name}, {question.id}, round {repeat}")
                    if repeat >= 0:
                        rows.append(Sample(repeat=repeat, question_id=question.id, path=name, **result.model_dump()))
            print(f"PASS interleaved round {repeat}", flush=True)
    summary: dict[str, Summary] = {}
    for name in ready:
        values = sorted(row.http_ms for row in rows if row.path == name)
        summary[name] = Summary(
            n=len(values),
            mean_ms=statistics.mean(values),
            p50_ms=statistics.median(values),
            p95_ms=values[math.ceil(0.95 * len(values)) - 1],
        )
    report = Report(
        gold_source="private historical responses" if args.gold_dir else "fresh original response before warmup",
        rounds=args.rounds,
        warmups_excluded=args.warmups,
        seed=args.seed,
        summary=summary,
        responses_exact=True,
        rows=rows,
    )
    (args.output_dir / "results.json").write_text(report.model_dump_json(indent=2))
    print(json.dumps({name: item.model_dump() for name, item in summary.items()}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["snapshot-dir", "off-ready", "p3-ready", "new-ready", "api-key-file", "output-dir"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gold-dir", type=Path)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--take", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261120)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
