"""Rate-limited fact reranking over saved recalls; no Bank writes or reader/judge calls."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

spec = importlib.util.spec_from_file_location("_rerank_preview_runner", Path(__file__).with_name("runner.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("Cannot load benchmark helpers")
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)


class RankItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    index: int = Field(ge=0)
    relevance_score: float = Field(allow_inf_nan=False)


class Usage(BaseModel):
    total_tokens: int = Field(ge=0)


class Reply(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    model: str
    results: list[RankItem]
    usage: Usage | None = None


class Request(h.core.StrictModel):
    model: str
    query: str
    documents: list[str]


class Attempt(h.core.StrictModel):
    started_at: str
    http_status: int | None = None
    elapsed_ms: float | None = None
    retry_after_s: float | None = None
    error: str | None = None


class Call(h.core.StrictModel):
    request: Request
    response: Reply | None = None
    attempts: list[Attempt] = Field(default_factory=list)


class Provenance(h.core.StrictModel):
    source: str
    source_manifest_sha256: str
    model: str
    endpoint: str
    credential_file: str
    questions: list[str]
    concurrency: int = 1
    min_request_interval_s: float
    packing: h.core.PackingSettings
    chunk_order: str = "unchanged baseline response order"
    candidate_inputs: str = "fact.text only; no QA gold or evidence"
    new_accuracy: str = "not measured"
    source_checkpoint_sha256: dict[str, str]
    code_sha256: dict[str, str]


class FactComparison(h.core.StrictModel):
    id: str
    text: str
    old_rank: int
    new_rank: int
    score: float
    old_included: bool
    new_included: bool


class Comparison(h.core.StrictModel):
    question_id: str
    question: str
    packing: h.core.Packed
    facts: list[FactComparison]


class Summary(h.core.StrictModel):
    question_id: str
    candidates: int
    context_tokens: int
    included_facts: int
    total_tokens: int | None


class Client:
    def __init__(self, session: aiohttp.ClientSession, endpoint: str, secret: str, interval_s: float = 30) -> None:
        self.session, self.endpoint, self.secret = session, endpoint, secret
        self.interval_s = interval_s
        self.last_start = 0.0
        self.lock: asyncio.Lock | None = None

    async def score(self, request: Request, path: Path) -> Reply:
        if path.exists():
            raise ValueError("Do not overwrite an existing rerank call")
        # One client belongs to one experiment/event loop. Serialize entire requests
        # and pace starts, including a 429 retry; no concurrent burst is possible.
        if self.lock is None:
            self.lock = asyncio.Lock()
        async with self.lock:
            record = Call(request=request)
            for number in range(2):
                await asyncio.sleep(max(0, self.last_start + self.interval_s - time.monotonic()))
                self.last_start = time.monotonic()
                attempt = Attempt(started_at=h.core.now())
                record.attempts.append(attempt)
                h.core.save_model(path, record)
                try:
                    async with self.session.post(
                        self.endpoint,
                        json=request.model_dump(),
                        headers={"Authorization": "Bearer " + self.secret},
                    ) as response:
                        raw = (await response.text()).replace(self.secret, "[redacted]")
                        attempt.http_status = response.status
                        attempt.elapsed_ms = (time.monotonic() - self.last_start) * 1000
                        if response.status == 429:
                            try:
                                delay = max(30.0, float(response.headers.get("Retry-After", "30")))
                            except ValueError:
                                delay = 60.0
                            attempt.retry_after_s = delay
                            h.core.save_model(path, record)
                            if number == 0 and delay <= 300:
                                print(json.dumps({"stage": "rate_limited", "wait_s": delay}), flush=True)
                                await asyncio.sleep(delay)
                                continue
                        if response.status != 200:
                            raise RuntimeError(f"Rerank HTTP {response.status}; stopped without model fallback")
                        reply = Reply.model_validate_json(raw)
                    if reply.model != request.model:
                        raise ValueError("Unexpected reranker model in response")
                    if sorted(item.index for item in reply.results) != list(range(len(request.documents))):
                        raise ValueError("Reranker must return exactly one score for every candidate")
                    record.response = reply
                    h.core.save_model(path, record)
                    return reply
                except BaseException as error:
                    attempt.error = type(error).__name__
                    h.core.save_model(path, record)
                    raise
            raise RuntimeError("Rerank attempt limit exhausted")


def reorder(recall: Any, reply: Reply) -> Any:
    order = sorted(reply.results, key=lambda item: (-item.relevance_score, item.index))
    # Preserve every fact, all fields and the original chunk order. This experiment
    # changes fact ranking only; no gold answers/evidence enter the reranker.
    return recall.model_copy(update={"results": [recall.results[item.index] for item in order]})


async def run(source: Path, output: Path, questions: list[str], key_file: Path, interval_s: float = 30) -> None:
    manifest = h.load_manifest(source)
    indexed = {h.amb_id(q): (c, q) for c in manifest.conversations for q in c.questions}
    if len(set(questions)) != len(questions) or any(qid not in indexed for qid in questions):
        raise ValueError("Question scope must be unique and present in the frozen baseline")
    endpoint = "https://api.modelarts-maas.com/v1/rerank"
    model = "bge-reranker-v2-m3"
    secret = h.core.PrivateKey.model_validate_json(key_file.read_text()).secret
    code_names = ("rerank_preview.py", "runner.py", "support.py")
    provenance = Provenance(
        source=str(source.resolve()),
        source_manifest_sha256=h.core.file_sha(source / "manifest.json"),
        model=model,
        endpoint=endpoint,
        credential_file=str(key_file),
        questions=questions,
        min_request_interval_s=interval_s,
        packing=manifest.config.packing,
        source_checkpoint_sha256={qid: h.core.file_sha(source / f"retrievals/{qid}.json") for qid in questions},
        code_sha256={name: h.core.file_sha(Path(__file__).with_name(name)) for name in code_names},
    )
    output.mkdir(parents=True, exist_ok=False)
    h.core.save_model(output / "manifest.json", provenance)
    for name in code_names:
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    summaries = []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90), trust_env=True) as session:
        client = Client(session, endpoint, secret, interval_s)
        for qid in questions:
            conversation, question = indexed[qid]
            baseline = h.unseal(source / f"retrievals/{qid}.json", h.RetrievalRecord, manifest)
            reply = await client.score(
                Request(model=model, query=question.question, documents=[f.text for f in baseline.recall.results]),
                output / f"{qid}-call.json",
            )
            ranked = reorder(baseline.recall, reply)
            packed = h.core.pack_context(ranked, conversation, manifest.config.packing)
            ranks = {f.id: number + 1 for number, f in enumerate(ranked.results)}
            scores = {baseline.recall.results[item.index].id: item.relevance_score for item in reply.results}
            audit = Comparison(
                question_id=qid,
                question=question.question,
                packing=packed,
                facts=[
                    FactComparison(
                        id=f.id,
                        text=f.text,
                        old_rank=i + 1,
                        new_rank=ranks[f.id],
                        score=scores[f.id],
                        old_included=f.id in baseline.packing.included_fact_ids,
                        new_included=f.id in packed.included_fact_ids,
                    )
                    for i, f in enumerate(baseline.recall.results)
                ],
            )
            h.core.save_model(output / f"{qid}-comparison.json", audit)
            summary = Summary(
                question_id=qid,
                candidates=len(ranked.results),
                context_tokens=packed.tokens,
                included_facts=len(packed.included_fact_ids),
                total_tokens=reply.usage.total_tokens if reply.usage else None,
            )
            summaries.append(summary.model_dump(mode="json"))
            print(summary.model_dump_json(), flush=True)
    (output / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--questions", nargs="+", required=True)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    if args.interval < 30:
        parser.error("Live preview interval must be at least 30 seconds")
    asyncio.run(run(args.source, args.output, args.questions, args.key_file, args.interval))


if __name__ == "__main__":
    main()
