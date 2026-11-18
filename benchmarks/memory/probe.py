"""Independent CPU or read-only live-recall probes over frozen questions; never answer or judge."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.util
import json
import resource
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import aiohttp
from pydantic import BaseModel, Field

spec = importlib.util.spec_from_file_location("_memory_probe_preview", Path(__file__).with_name("rerank_preview.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("Missing rerank helpers")
r = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = r
spec.loader.exec_module(r)
a = r.h.module_from_file("_memory_probe_analysis", Path(__file__).with_name("analysis.py"))
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
WEIGHT_SHA = "d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286"


class ProbeConfig(BaseModel):
    mode: str
    source_run_id: str
    source_manifest_sha256: str
    questions: list[str]
    packing: r.h.core.PackingSettings
    recall: r.h.core.RecallSettings
    declared_memory: r.h.core.MemoryProfile
    live_configuration_note: str = "Source profile is a declaration; actual deployment must be archived separately."
    model_path: str | None = None
    model_revision: str | None = None
    model_weights_sha256: str | None = None
    device: str | None = None
    precision: str | None = None
    threads: int = 4
    batch_size: int = 8
    max_length: int = 512
    repeats: int = 3
    dependencies: dict[str, str] = Field(default_factory=dict)
    load_s: float | None = None
    warmup_s: float | None = None
    max_rss_bytes: int | None = None
    source_hashes: dict[str, str]


class Scores(BaseModel):
    elapsed_s: float
    values: list[float]


class Outcome(BaseModel):
    question_id: str
    fact_count: int
    context_tokens: int
    recall_ms: float | None = None
    max_input_pair_tokens: int | None = None
    input_pair_tokens: int | None = None
    repetitions: list[Scores] = Field(default_factory=list)
    stable_order: bool | None = None
    facts: list[r.FactComparison]


def initialize(source: Path, output: Path, qids: list[str], mode: str) -> ProbeConfig:
    manifest = a.manifest_at(source)
    valid = {r.h.amb_id(q) for c in manifest.conversations for q in c.questions}
    if not qids or len(qids) != len(set(qids)) or not set(qids) <= valid:
        raise ValueError("Choose unique question IDs from the frozen scope")
    output.mkdir(parents=True, exist_ok=False)
    names = ["probe.py", "rerank_preview.py", "analysis.py", "runner.py", "support.py"]
    for name in names:
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    config = ProbeConfig(
        mode=mode,
        source_run_id=manifest.run_id,
        source_manifest_sha256=r.h.core.file_sha(source / "manifest.json"),
        questions=qids,
        packing=manifest.config.packing.model_dump(),
        recall=manifest.config.recall.model_dump(),
        declared_memory=manifest.config.memory_profile.model_dump(),
        source_hashes={name: r.h.core.file_sha(Path(__file__).with_name(name)) for name in names},
    )
    r.h.core.save_model(output / "manifest.json", config)
    return config


def record(source: Path, output: Path, qid: str, reply: Any, **details: Any) -> Outcome:
    manifest = a.manifest_at(source)
    c = next(c for c in manifest.conversations if any(r.h.amb_id(q) == qid for q in c.questions))
    old = r.h.unseal(source / f"retrievals/{qid}.json", r.h.RetrievalRecord, manifest)
    packed = r.h.core.pack_context(reply, c, manifest.config.packing)
    ranks = {f.id: i + 1 for i, f in enumerate(reply.results)}
    new = {f.id: f for f in reply.results}
    facts = [
        r.FactComparison(
            id=f.id,
            text=f.text,
            old_rank=i + 1,
            new_rank=ranks[f.id],
            score=float((new[f.id].model_extra or {}).get("score", 0)),
            old_included=f.id in old.packing.included_fact_ids,
            new_included=f.id in packed.included_fact_ids,
        )
        for i, f in enumerate(old.recall.results)
        if f.id in ranks
    ]
    result = Outcome(
        question_id=qid, fact_count=len(reply.results), context_tokens=packed.tokens, facts=facts, **details
    )
    r.h.core.save_model(output / f"{qid}-recall.json", reply)
    r.h.core.save_model(output / f"{qid}-packing.json", packed)
    r.h.core.save_model(output / f"{qid}-comparison.json", result)
    print(result.model_dump_json(exclude={"facts", "repetitions"}), flush=True)
    return result


def local(source: Path, output: Path, config: ProbeConfig, model_path: Path) -> None:
    import numpy as np
    import torch
    from hindsight_api.engine.local_device import align_local_model_weights
    from sentence_transformers import CrossEncoder
    from sentence_transformers.cross_encoder.model import PairInput

    if model_path.name != REVISION or r.h.core.file_sha(model_path / "model.safetensors") != WEIGHT_SHA:
        raise ValueError("Expected the pinned official BGE snapshot and verified weights")
    config.model_path = str(model_path.resolve())
    config.model_revision = REVISION
    config.model_weights_sha256 = WEIGHT_SHA
    config.device, config.precision = "cpu", "float32"
    config.dependencies = {
        name: importlib.metadata.version(name)
        for name in ["torch", "transformers", "sentence-transformers", "huggingface-hub"]
    }
    torch.set_num_threads(config.threads)
    torch.set_num_interop_threads(1)
    started = time.perf_counter()
    model = CrossEncoder(
        str(model_path),
        device="cpu",
        local_files_only=True,
        max_length=config.max_length,
        model_kwargs={"dtype": torch.float32, "low_cpu_mem_usage": False},
    )
    align_local_model_weights(model.model, label="isolated BGE CPU probe")
    if model.model is None:
        raise RuntimeError("Model did not load")
    model.model.eval()
    config.load_s = time.perf_counter() - started
    r.h.core.save_model(output / "manifest.json", config)
    manifest = a.manifest_at(source)
    for qid in config.questions:
        q = next(q for c in manifest.conversations for q in c.questions if r.h.amb_id(q) == qid)
        old = r.h.unseal(source / f"retrievals/{qid}.json", r.h.RetrievalRecord, manifest)
        texts = [f.text for f in old.recall.results]
        pairs: list[PairInput] = [[q.question, text] for text in texts]
        lengths = [len(model.tokenizer(q.question, text, truncation=False)["input_ids"]) for text in texts]
        if not lengths or max(lengths) > config.max_length:
            raise ValueError("Refusing input truncation")
        if config.warmup_s is None:
            start = time.perf_counter()
            model.predict(
                pairs, batch_size=config.batch_size, show_progress_bar=False, activation_fn=torch.nn.Sigmoid()
            )
            config.warmup_s = time.perf_counter() - start
        times = []
        orders = []
        for _ in range(config.repeats):
            start = time.perf_counter()
            scores = np.asarray(
                model.predict(
                    pairs, batch_size=config.batch_size, show_progress_bar=False, activation_fn=torch.nn.Sigmoid()
                )
            ).reshape(-1)
            elapsed = time.perf_counter() - start
            if len(scores) != len(texts) or not np.isfinite(scores).all():
                raise ValueError("Incomplete or non-finite rerank scores")
            times.append(Scores(elapsed_s=elapsed, values=scores.tolist()))
            orders.append(sorted(range(len(scores)), key=lambda i: (-float(scores[i]), i)))
        response = r.Reply(
            id=f"local-{qid}",
            model="bge-reranker-v2-m3",
            results=[r.RankItem(index=i, relevance_score=s) for i, s in enumerate(times[0].values)],
        )
        r.h.core.save_model(output / f"{qid}-scores.json", response)
        ranked = r.reorder(old.recall, response)
        score_by_id = {f.id: score for f, score in zip(old.recall.results, times[0].values)}
        ranked = ranked.model_copy(
            update={"results": [f.model_copy(update={"score": score_by_id[f.id]}) for f in ranked.results]}
        )
        record(
            source,
            output,
            qid,
            ranked,
            repetitions=times,
            max_input_pair_tokens=max(lengths),
            input_pair_tokens=sum(lengths),
            stable_order=all(o == orders[0] for o in orders),
        )
    config.max_rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    r.h.core.save_model(output / "manifest.json", config)


async def recall(source: Path, output: Path, config: ProbeConfig) -> None:
    manifest = a.manifest_at(source)
    # Force the transport's read-only Bank guard, even if the source originally ingested.
    readonly = manifest.config.model_copy(update={"reuse_banks": {c.id: c.bank_id for c in manifest.conversations}})
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=readonly.request_timeout_s), trust_env=False
    ) as s:
        http = r.h.core.BankHTTP(s, readonly, readonly.credential.resolve())
        for qid in config.questions:
            c, q = next((c, q) for c in manifest.conversations for q in c.questions if r.h.amb_id(q) == qid)
            body = r.h.core.RecallBody(
                query=q.question,
                budget=config.recall.budget,
                max_tokens=config.recall.max_tokens,
                query_timestamp=c.reference_date,
                include=r.h.core.RecallInclude(chunks=r.h.core.ChunkBudget(max_tokens=config.recall.max_chunk_tokens)),
            )
            r.h.core.save_model(output / f"{qid}-request.json", body)
            start = time.perf_counter()
            reply = await http.request(
                "POST", f"/v1/default/banks/{c.bank_id}/memories/recall", r.h.core.RecallReply, body
            )
            record(source, output, qid, reply, recall_ms=(time.perf_counter() - start) * 1000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["local", "recall"])
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--questions", nargs="+", required=True)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if min(args.threads, args.batch_size, args.repeats) < 1 or (args.mode == "local" and not args.model_path):
        parser.error("Use positive settings and supply --model-path for local mode")
    config = initialize(args.source, args.output, args.questions, args.mode)
    config.threads = args.threads
    config.batch_size = args.batch_size
    config.repeats = args.repeats
    if args.mode == "local":
        local(args.source, args.output, config, args.model_path)
    else:
        asyncio.run(recall(args.source, args.output, config))
    r.h.core.save_model(args.output / "manifest.json", config)
    hashes = {
        str(p.relative_to(args.output)): r.h.core.file_sha(p)
        for p in args.output.rglob("*")
        if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts
    }
    (args.output / "checksums.json").write_text(json.dumps(hashes, indent=2) + "\n")


if __name__ == "__main__":
    main()
