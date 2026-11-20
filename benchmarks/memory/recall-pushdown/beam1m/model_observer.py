"""Explicit test controls for the isolated native benchmark, never a product hook.

BGE pairs and output scores are never changed. With BEAM_QUERY_VECTOR_SNAPSHOT,
the hook times an actual remote embedding request, then supplies the declared
frozen vector to retrieval. This separates PG equivalence from upstream numeric
variation; it must be disclosed when reporting end-to-end latency.
"""

import hashlib
import json
import os
import struct
from pathlib import Path
from time import perf_counter

from hindsight_api.engine.cross_encoder import LocalSTCrossEncoder
from hindsight_api.engine.embeddings import Embeddings
from hindsight_api.engine.search.reranking import CrossEncoderReranker, RerankResult
from hindsight_api.engine.search.types import MergedCandidate
from pydantic import BaseModel


class SnapshotQuestion(BaseModel):
    id: str
    query: str


class SnapshotQuestions(BaseModel):
    queries: list[SnapshotQuestion]


class SnapshotVectors(BaseModel):
    ids: list[str]
    vectors: list[list[float]]


class EmbeddingCall(BaseModel):
    query_hashes: list[str]
    live_vector_hashes: list[str]
    used_vector_hashes: list[str]
    live_embedding_ms: float
    retrieval_input_pinned: bool
    live_vectors: list[list[float]] | None = None
    used_vectors: list[list[float]] | None = None


class RankedInput(BaseModel):
    id: str
    rrf_score: float
    rrf_rank: int
    source_ranks: dict[str, int]


class CandidateCall(BaseModel):
    query_sha256: str
    candidates: list[RankedInput]


class ModelCall(BaseModel):
    query_sha256: str
    pairs: int
    input_sha256: str
    output_sha256: str
    elapsed_ms: float


def vector_hash(vector: list[float]) -> str:
    # PG vector stores float32: compare the values PG actually searches.
    return hashlib.sha256(struct.pack(f"<{len(vector)}f", *vector)).hexdigest()


def write_private(path: Path, value: str, *, append: bool = True) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a" if append else "w") as output:
        output.write(value + "\n")


def install(path: Path) -> None:
    frozen_by_text: dict[str, list[float]] = {}
    snapshot_dir = os.environ.get("BEAM_QUERY_VECTOR_SNAPSHOT")
    diagnostic = bool(os.environ.get("BEAM_DIAGNOSTIC_CAPTURE"))
    if snapshot_dir:
        root = Path(snapshot_dir)
        questions = SnapshotQuestions.model_validate_json((root / "queries.json").read_text())
        vectors: dict[str, list[float]] = {}
        for file in root.glob("embeddings-*.json"):
            batch = SnapshotVectors.model_validate_json(file.read_text())
            vectors.update(zip(batch.ids, batch.vectors, strict=True))
        frozen_by_text = {q.query: vectors[q.id] for q in questions.queries}
    original_predict = LocalSTCrossEncoder._predict
    original_embedding = Embeddings.encode_query
    original_rerank = CrossEncoderReranker.rerank

    async def embedding_observed(self: Embeddings, texts: list[str]) -> list[list[float]]:
        started = perf_counter()
        live = await original_embedding(self, texts)
        elapsed_ms = (perf_counter() - started) * 1000
        # Unknown text fails explicitly; do not silently mix controlled and live
        # retrieval inputs in the same benchmark.
        used = [frozen_by_text[text] for text in texts] if frozen_by_text else live
        if len(live) != len(used) or any(len(a) != len(b) for a, b in zip(live, used, strict=True)):
            raise RuntimeError("Live embedding shape differs from the declared snapshot")
        record = EmbeddingCall(
            query_hashes=[hashlib.sha256(t.encode()).hexdigest() for t in texts],
            live_vector_hashes=[vector_hash(v) for v in live],
            used_vector_hashes=[vector_hash(v) for v in used],
            live_embedding_ms=elapsed_ms,
            retrieval_input_pinned=bool(frozen_by_text),
            live_vectors=live if diagnostic else None,
            used_vectors=used if diagnostic else None,
        )
        write_private(path.with_suffix(".embedding.jsonl"), record.model_dump_json(exclude_none=True))
        return used

    async def rerank_observed(
        self: CrossEncoderReranker, query: str, candidates: list[MergedCandidate]
    ) -> RerankResult:
        if diagnostic:
            record = CandidateCall(
                query_sha256=hashlib.sha256(query.encode()).hexdigest(),
                candidates=[
                    RankedInput(id=c.id, rrf_score=c.rrf_score, rrf_rank=c.rrf_rank, source_ranks=c.source_ranks)
                    for c in candidates
                ],
            )
            write_private(path.with_suffix(".candidates.jsonl"), record.model_dump_json())
        return await original_rerank(self, query, candidates)

    async def predict_observed(self: LocalSTCrossEncoder, pairs: list[tuple[str, str]]) -> list[float]:
        if diagnostic:
            write_private(path.with_suffix(".pairs.json"), json.dumps(pairs, ensure_ascii=False), append=False)
        input_hash = hashlib.sha256(json.dumps(pairs, ensure_ascii=False).encode()).hexdigest()
        started = perf_counter()
        scores = await original_predict(self, pairs)
        record = ModelCall(
            query_sha256=hashlib.sha256(pairs[0][0].encode()).hexdigest() if pairs else "",
            pairs=len(pairs),
            input_sha256=input_hash,
            output_sha256=hashlib.sha256(json.dumps([float(s) for s in scores]).encode()).hexdigest(),
            elapsed_ms=(perf_counter() - started) * 1000,
        )
        write_private(path, record.model_dump_json())
        return scores

    Embeddings.encode_query = embedding_observed
    CrossEncoderReranker.rerank = rerank_observed
    LocalSTCrossEncoder._predict = predict_observed
