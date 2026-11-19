"""Recall-only feasibility verification, never a second reader/judge runner.

Uses a frozen private Bank/vector snapshot and the real Recall HTTP endpoint on
an isolated loopback server. Frozen query embeddings are declared explicitly;
these timings must not be labelled live-embedding production latency.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import secrets
import socket
import statistics
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class Question(BaseModel):
    id: str
    query: str
    window: list[datetime] | None


class Questions(BaseModel):
    reference_date: datetime
    queries: list[Question]


class Vectors(BaseModel):
    ids: list[str]
    vectors: list[list[float]]


class SQLCall(BaseModel):
    stage: str
    candidate_entry: bool
    elapsed_ms: float
    failed: bool
    statement: str


class RankedItem(BaseModel):
    id: str
    score: float | None


class ArmSnapshot(BaseModel):
    semantic: list[RankedItem]
    keyword: list[RankedItem]
    graph: list[RankedItem]
    temporal: list[RankedItem]


class FusionItem(BaseModel):
    id: str
    score: float
    rank: int
    source_ranks: dict[str, int]
    payload_sha256: str


class FusionSnapshot(BaseModel):
    inputs: list[list[str]]
    output: list[FusionItem]


class Sample(BaseModel):
    question_id: str
    repeat: int
    http_ms: float
    status: int
    claimed: bool
    temporal: bool = False
    sql: list[SQLCall]
    candidate_count: int | None = None
    chunk_count: int | None = None
    model_pairs: int = 0
    model_input_sha256: str | None = None
    model_ms: float = 0
    response_sha256: str | None = None
    arms: dict[str, ArmSnapshot] = Field(default_factory=dict)
    fusion: list[FusionSnapshot] = Field(default_factory=list)
    model_ids: list[str] = Field(default_factory=list)


@dataclass
class RequestSQLScope:
    sample: Sample
    stage: str = "api"


class QueryLogRecord(Protocol):
    query: str
    elapsed: float
    exception: BaseException | None


@dataclass
class SQLRecorder:
    context: ContextVar[RequestSQLScope | None]
    outside_request: int = 0

    def observe(self, record: QueryLogRecord) -> None:
        scope = self.context.get()
        if scope is None:
            # Maintenance tasks inherit the startup context, not the HTTP scope.
            self.outside_request += 1
            return
        scope.sample.sql.append(
            SQLCall(
                stage=scope.stage,
                candidate_entry=any(
                    name in record.query for name in ("recall_pushdown.candidates(", "recall_equiv.candidates(")
                ),
                elapsed_ms=record.elapsed * 1000,
                failed=record.exception is not None,
                statement=record.query,
            )
        )


class Report(BaseModel):
    path: str
    mode: str
    label: str | None = None
    python_hash_seed: str | None = None
    metadata_bootstrap: str = "normal read-only startup"
    embedding: str = "frozen query embeddings; no embedding service time included"
    protocol: str = "real loopback Recall HTTP; no reader/judge or new accuracy score"
    endpoint: str | None = None
    database_mode: str = "private snapshot"
    maintenance: str = "normal process settings"
    pg_backend_pids: list[int] = Field(default_factory=list)
    pg_log_candidate_executes: int | None = None
    outside_request_sql: int = 0
    source_sha256: dict[str, str] = Field(default_factory=dict)
    samples: list[Sample] = Field(default_factory=list)


def validate_database_target(
    actual_dir: Path,
    snapshot_dir: Path,
    existing_pg_data_dir: Path | None,
    *,
    superuser: bool,
    read_only: bool,
) -> str:
    """Attaching an existing PG requires an explicit path and a read-only role."""
    if existing_pg_data_dir is None:
        if actual_dir.resolve() != (snapshot_dir / "pgdata").resolve():
            raise RuntimeError("Verification requires the declared private PG snapshot")
        return "private snapshot"
    if actual_dir.resolve() != existing_pg_data_dir.resolve():
        raise RuntimeError("Existing PG data directory does not match the explicit target")
    if superuser or not read_only:
        raise RuntimeError("Existing PG verification requires a non-superuser read-only role")
    return "existing PG; no migration, initialization or data import"


async def run(args: argparse.Namespace) -> None:
    # Both processes get identical settings. Session setup stays at connection
    # initialization, not hidden on every recall acquire; this is existing config.
    os.environ.update(
        HINDSIGHT_API_DATABASE_SCHEMA=args.schema,
        HINDSIGHT_API_DB_SESSION_SETUP_ON_ACQUIRE="false",
        HINDSIGHT_API_LLM_PROVIDER="mock",
        HINDSIGHT_API_LLM_MODEL="mock",
        HINDSIGHT_API_SKIP_LLM_VERIFICATION="true",
        HINDSIGHT_API_RERANKER_PROVIDER="local" if args.mode == "bge" else "rrf",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        OMP_NUM_THREADS="4",
        TOKENIZERS_PARALLELISM="false",
    )
    if args.existing_pg_data_dir is not None:
        # This auxiliary Recall-only process must not duplicate the existing
        # service's maintenance jobs. Database permissions also prevent writes.
        os.environ.update(
            HINDSIGHT_API_CONSOLIDATION_RECONCILE_INTERVAL_SECONDS="0",
            HINDSIGHT_API_MENTAL_MODEL_REFRESH_TICK_SECONDS="0",
            HINDSIGHT_API_RETENTION_SWEEP_INTERVAL_SECONDS="0",
            HINDSIGHT_API_OPERATION_CLEANUP_INTERVAL_SECONDS="0",
        )
    import aiohttp
    import asyncpg
    import uvicorn
    from hindsight_api.api import create_app
    from hindsight_api.engine.cross_encoder import LocalSTCrossEncoder, RRFPassthroughCrossEncoder
    from hindsight_api.engine.embeddings import Embeddings
    from hindsight_api.engine.memories import set_memories
    from hindsight_api.engine.memories.base import FullRecallRequest
    from hindsight_api.engine.memories.postgres import PostgresMemories
    from hindsight_api.engine.memory_engine import MemoryEngine
    from hindsight_api.engine.query_analyzer import DateparserQueryAnalyzer

    data = Questions.model_validate_json((args.snapshot_dir / "queries.json").read_text())
    vectors: dict[str, list[float]] = {}
    for file in sorted(args.snapshot_dir.glob("embeddings-*.json")):
        batch = Vectors.model_validate_json(file.read_text())
        vectors.update(zip(batch.ids, batch.vectors, strict=True))
    by_text = {q.query: vectors[q.id] for q in data.queries}
    selected = [q for q in data.queries if not args.ids or q.id in args.ids][: args.take]
    if not selected:
        raise ValueError("No questions selected")
    if not args.output_dir.is_dir():
        args.output_dir.mkdir(parents=True, mode=0o700)
    report = Report(path=args.path, mode=args.mode, label=args.label, python_hash_seed=os.getenv("PYTHONHASHSEED"))
    if args.existing_pg_data_dir is not None:
        report.maintenance = "auxiliary process jobs disabled; existing service unchanged"
    active: Sample | None = None
    request_scope: ContextVar[RequestSQLScope | None] = ContextVar("recall_verification_request", default=None)
    recorder = SQLRecorder(request_scope)

    class FrozenEmbeddings(Embeddings):
        @property
        def provider_name(self) -> str:
            return "frozen-snapshot"

        @property
        def dimension(self) -> int:
            return len(next(iter(vectors.values())))

        async def initialize(self) -> None:
            pass

        async def encode(self, texts: list[str]) -> list[list[float]]:
            return [by_text[text] for text in texts]

    class RecordingEncoder(LocalSTCrossEncoder):
        async def _predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            started = perf_counter()
            scope = request_scope.get()
            if scope is not None:
                scope.sample.model_pairs = len(pairs)
                scope.sample.model_input_sha256 = hashlib.sha256(json.dumps(pairs).encode()).hexdigest()
            result = await super()._predict(pairs)
            if scope is not None:
                scope.sample.model_ms = (perf_counter() - started) * 1000
            return result

    if args.path == "legacy":
        # This branch also runs against the entirely unmodified source commit.
        # Importing the new pushdown module would invalidate that baseline.
        parent = PostgresMemories
    else:
        from hindsight_api.engine.memories.pg.recall_pushdown import (
            CanonicalPostgresMemories,
            EquivalentPostgresRecallMemories,
            PostgresRecallPushdownMemories,
        )

        parent = {
            "pushdown": PostgresRecallPushdownMemories,
            "equivalent": EquivalentPostgresRecallMemories,
            "control": CanonicalPostgresMemories,
        }[args.path]

    from hindsight_api.engine.search import fusion as fusion_module

    original_fuse = fusion_module.reciprocal_rank_fusion

    def observed_fuse(result_lists, k=60):
        result = original_fuse(result_lists, k)
        scope = request_scope.get()
        if scope is not None:
            scope.sample.fusion.append(
                FusionSnapshot(
                    inputs=[[r.id for r in arm] for arm in result_lists],
                    output=[
                        FusionItem(
                            id=r.id,
                            score=r.rrf_score,
                            rank=r.rrf_rank,
                            source_ranks=r.source_ranks,
                            payload_sha256=hashlib.sha256(
                                json.dumps(vars(r.retrieval), sort_keys=True, default=str).encode()
                            ).hexdigest(),
                        )
                        for r in result
                    ],
                )
            )
        # Preserve the original objects, list order, scores and payloads exactly.
        return result

    fusion_module.reciprocal_rank_fusion = observed_fuse

    class RecordingStore(parent):
        async def recall_unified(self, **kwargs: Any):
            result = await super().recall_unified(**kwargs)
            scope = request_scope.get()
            if scope is not None:
                scope.sample.temporal = kwargs.get("temporal_window") is not None
                for fact_type, arms in result.items():
                    scope.sample.arms[fact_type] = ArmSnapshot(
                        semantic=[RankedItem(id=r.id, score=r.similarity) for r in arms.semantic],
                        keyword=[RankedItem(id=r.id, score=r.bm25_score) for r in arms.bm25],
                        graph=[RankedItem(id=r.id, score=r.activation) for r in arms.graph],
                        temporal=[RankedItem(id=r.id, score=r.temporal_score) for r in arms.temporal],
                    )
            return result

        async def full_recall(self, request: FullRecallRequest):
            scope = request_scope.get()
            assert scope is not None
            scope.stage = "full_recall"
            scope.sample.temporal = request.temporal_window is not None
            if args.path == "legacy":
                try:
                    return await super().full_recall(request)
                finally:
                    scope.stage = "legacy"
            if args.path in {"pushdown", "equivalent"} and not self.supports(request):
                from hindsight_api.config import get_config

                cfg = get_config()
                print(
                    {
                        "declined": {
                            key: getattr(request, key)
                            for key in (
                                "bank_id",
                                "fact_types",
                                "tags",
                                "tags_match",
                                "tag_groups",
                                "min_semantic",
                                "min_keyword",
                                "enable_text_search",
                                "enable_graph",
                                "reranking",
                                "per_source_cap",
                                "strategy_boosts",
                                "include_entities",
                                "include_source_facts",
                                "reranker_max_candidates",
                                "limit",
                            )
                        },
                        "config": {
                            key: getattr(cfg, key)
                            for key in (
                                "database_backend",
                                "text_search_extension",
                                "text_search_extension_native_language",
                                "bm25_min_score",
                                "graph_retriever",
                            )
                        },
                    },
                    flush=True,
                )
            assert request.runtime is not None
            finalize = request.runtime.finalize

            async def observed_finalize(batch):
                await asyncio.sleep(0)  # Drain the driver's completed-query logger first.
                scope.stage = "postprocess"
                scope.sample.candidate_count = len(batch.candidates)
                scope.sample.chunk_count = len(batch.chunks or {})
                scope.sample.fusion.append(
                    FusionSnapshot(
                        inputs=[],
                        output=[
                            FusionItem(
                                id=c.id,
                                score=c.rrf_score,
                                rank=c.rrf_rank,
                                source_ranks=c.source_ranks,
                                payload_sha256=hashlib.sha256(
                                    json.dumps(vars(c.retrieval), sort_keys=True, default=str).encode()
                                ).hexdigest(),
                            )
                            for c in batch.candidates
                        ],
                    )
                )
                return await finalize(batch)

            request.runtime.finalize = observed_finalize
            try:
                result = await super().full_recall(request)
                await asyncio.sleep(0)
                scope.sample.claimed = result is not None
                return result
            finally:
                scope.stage = "response" if args.path in {"pushdown", "equivalent"} else "legacy"

    model = (
        RecordingEncoder(
            model_name=str(args.model_path),
            force_cpu=True,
            fp16=False,
            max_concurrent=1,
            batch_size=8,
        )
        if args.mode == "bge"
        else RRFPassthroughCrossEncoder()
    )
    # The default remains snapshot-only. Existing PG attachment is explicit and
    # uses a separately granted read-only account, never the installation owner.
    guard = await asyncpg.connect(args.pg_dsn)
    try:
        actual_dir = Path(await guard.fetchval("SHOW data_directory")).resolve()
        report.database_mode = validate_database_target(
            actual_dir,
            args.snapshot_dir,
            args.existing_pg_data_dir,
            superuser=bool(await guard.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")),
            read_only=await guard.fetchval("SHOW default_transaction_read_only") == "on",
        )
    finally:
        await guard.close()
    source_root = Path(__import__("hindsight_api").__file__).parent
    for relative in [
        "engine/memory_engine.py",
        "engine/memories/base.py",
        "engine/memories/pg/recall_pushdown.py",
        "engine/search/retrieval.py",
        "engine/memories/postgres.py",
        "engine/search/fusion.py",
        "engine/search/reranking.py",
        "engine/cross_encoder.py",
        "engine/fact_budget.py",
    ]:
        file = source_root / relative
        if file.exists():
            report.source_sha256[relative] = hashlib.sha256(file.read_bytes()).hexdigest()
    log_start = args.pg_log.stat().st_size if args.pg_log else 0
    set_memories(RecordingStore({"bank_id": args.bank_id}))
    engine = MemoryEngine(
        db_url=args.pg_dsn,
        memory_llm_provider="mock",
        memory_llm_api_key="",
        memory_llm_model="mock",
        embeddings=FrozenEmbeddings(),
        cross_encoder=model,
        query_analyzer=DateparserQueryAnalyzer(),
        pool_min_size=1,
        pool_max_size=4,
        run_migrations=False,
        skip_llm_verification=True,
    )
    if args.bootstrap_admin_dsn_file is not None:
        # The pristine engine unconditionally issues CREATE ... IF NOT EXISTS
        # for metadata at startup. Keep its source untouched: temporarily permit
        # those no-ops, then revoke CREATE and force every Recall connection RO.
        admin = await asyncpg.connect(args.bootstrap_admin_dsn_file.read_text().strip())
        try:
            if Path(await admin.fetchval("SHOW data_directory")).resolve() != actual_dir:
                raise RuntimeError("Bootstrap administrator is not on the verified PG instance")
            if await admin.fetchval("SELECT current_database()") != args.pg_dsn.rsplit("/", 1)[-1]:
                raise RuntimeError("Bootstrap administrator database mismatch")
            role_guard = await asyncpg.connect(args.pg_dsn)
            try:
                role = await role_guard.fetchval("SELECT current_user")
                database = await role_guard.fetchval("SELECT current_database()")
            finally:
                await role_guard.close()
            oid = await admin.fetchval("SELECT to_regclass('ctxdb_meta.system_config')::oid")
            if oid is None:
                raise RuntimeError("Pristine startup requires existing metadata; refusing initialization")
            role_ident = '"' + role.replace('"', '""') + '"'
            db_ident = '"' + database.replace('"', '""') + '"'
            db_create = await admin.fetchval("SELECT has_database_privilege($1,$2,'CREATE')", role, database)
            schema_create = await admin.fetchval("SELECT has_schema_privilege($1,'ctxdb_meta','CREATE')", role)
            try:
                await admin.execute(f"GRANT CREATE ON DATABASE {db_ident} TO {role_ident}")
                await admin.execute(f"GRANT CREATE ON SCHEMA ctxdb_meta TO {role_ident}")
                await admin.execute(f"ALTER ROLE {role_ident} SET default_transaction_read_only=off")
                await engine.initialize()
            finally:
                await admin.execute(f"ALTER ROLE {role_ident} SET default_transaction_read_only=on")
                if not db_create:
                    await admin.execute(f"REVOKE CREATE ON DATABASE {db_ident} FROM {role_ident}")
                if not schema_create:
                    await admin.execute(f"REVOKE CREATE ON SCHEMA ctxdb_meta FROM {role_ident}")
            if await admin.fetchval("SELECT to_regclass('ctxdb_meta.system_config')::oid") != oid:
                raise RuntimeError("Metadata identity changed during pristine startup")
            report.metadata_bootstrap = "pristine startup no-op DDL; existing table OID unchanged; CREATE revoked"
        finally:
            await admin.close()
    else:
        await engine.initialize()

    original_rerank = engine._cross_encoder_reranker.rerank

    async def observed_rerank(query, candidates):
        scope = request_scope.get()
        if scope is not None:
            scope.sample.model_ids = [c.id for c in candidates]
            scope.stage = "rerank"
        try:
            return await original_rerank(query, candidates)
        finally:
            if scope is not None:
                scope.stage = "postprocess"

    engine._cross_encoder_reranker.rerank = observed_rerank

    # Install the logger on every already-warmed connection and on later ones.
    # At most four simultaneous leases force the pool to instantiate all slots.

    pool = engine._backend.get_pool()
    holders = [await pool.acquire() for _ in range(4)]
    for conn in holders:
        if args.bootstrap_admin_dsn_file is not None:
            await conn.execute("SET default_transaction_read_only=on")
            assert await conn.fetchval("SHOW transaction_read_only") == "on"
        report.pg_backend_pids.append(conn.get_server_pid())
        if args.pg_log:
            await conn.execute("SET log_min_duration_statement = 0")
        conn.add_query_logger(recorder.observe)
    for conn in holders:
        await pool.release(conn)
    app = create_app(engine, initialize_memory=False)
    api_key = args.api_key_file.read_text().strip() if args.api_key_file else None
    allowed_path = f"/v1/default/banks/{args.bank_id}/memories/recall"

    async def observed_app(scope, receive, send):
        if scope["type"] == "http" and api_key is not None:
            headers = dict(scope.get("headers", []))
            supplied = headers.get(b"authorization", b"").decode("latin-1")
            permitted = secrets.compare_digest(supplied, "Bearer " + api_key)
            permitted = permitted and scope["method"] == "POST" and scope["path"] == allowed_path
            if not permitted:
                await send({"type": "http.response.start", "status": 403, "headers": []})
                return await send({"type": "http.response.body", "body": b"Recall verification only"})
        if scope["type"] != "http" or active is None:
            return await app(scope, receive, send)
        # Mutable state is request-local, so cancellation child tasks and the HTTP
        # response share the phase, while independent maintenance cannot inherit it.
        token = request_scope.set(RequestSQLScope(active))
        try:
            await app(scope, receive, send)
        finally:
            request_scope.reset(token)

    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    port = sock.getsockname()[1]
    report.endpoint = f"http://127.0.0.1:{port}{allowed_path}"
    server = uvicorn.Server(uvicorn.Config(observed_app, log_level="warning", lifespan="off"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        headers = {"Authorization": "Bearer " + api_key} if api_key else {}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180), headers=headers) as client:
            for repeat in range(args.repeats):
                for q in selected:
                    active = Sample(question_id=q.id, repeat=repeat, http_ms=0, status=0, claimed=False, sql=[])
                    body = {
                        "query": q.query,
                        "budget": "high",
                        "max_tokens": 8192,
                        "query_timestamp": data.reference_date.isoformat(),
                        "include": {"entities": None, "chunks": {"max_tokens": 8192}},
                    }
                    started = perf_counter()
                    async with client.post(
                        f"http://127.0.0.1:{port}/v1/default/banks/{args.bank_id}/memories/recall", json=body
                    ) as response:
                        payload = await response.read()
                        active.http_ms = (perf_counter() - started) * 1000
                        active.status = response.status
                    await asyncio.sleep(0)
                    active.response_sha256 = hashlib.sha256(payload).hexdigest()
                    # Full responses contain real memory data and must remain private.
                    (args.output_dir / f"{q.id}-{repeat}.json").write_bytes(payload)
                    report.samples.append(active)
                    (args.output_dir / "verification.json").write_text(report.model_dump_json(indent=2))
                    print(
                        json.dumps(
                            {
                                "qid": q.id,
                                "status": active.status,
                                "claimed": active.claimed,
                                "http_ms": round(active.http_ms, 2),
                                "full_sql": sum(x.stage == "full_recall" for x in active.sql),
                                "post_sql": sum(x.stage in {"postprocess", "response"} for x in active.sql),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
                    if response.status != 200:
                        raise RuntimeError(f"Recall failed: {q.id}; see private response")
                    if args.path in {"pushdown", "equivalent"} and (
                        not active.claimed
                        or sum(x.stage == "full_recall" for x in active.sql) != 1
                        or any(x.stage in {"postprocess", "response"} for x in active.sql)
                    ):
                        raise RuntimeError(f"Single-call/no-reread contract failed: {q.id}")
                    active = None
    finally:
        server.should_exit = True
        await serving
        await engine.close()
        set_memories(None)
        fusion_module.reciprocal_rank_fusion = original_fuse
    if args.pg_log:
        import re

        with args.pg_log.open("rb") as log:
            log.seek(log_start)
            lines = log.read().decode(errors="replace").splitlines()
        report.pg_log_candidate_executes = sum(
            "execute " in line
            and any(name in line for name in ("SELECT recall_pushdown.candidates(", "SELECT recall_equiv.candidates("))
            and any(f"[{pid}]" in line for pid in report.pg_backend_pids)
            for line in lines
        )
        if args.path in {"pushdown", "equivalent"} and report.pg_log_candidate_executes != len(report.samples):
            raise RuntimeError("PG log execute count differs from application call count")
    report.outside_request_sql = recorder.outside_request
    (args.output_dir / "verification.json").write_text(report.model_dump_json(indent=2))
    times = [sample.http_ms for sample in report.samples]
    print(
        json.dumps(
            {
                "complete": len(times),
                "mean_ms": statistics.mean(times),
                "p50_ms": statistics.median(times),
                "embedding": "frozen",
                "mode": args.mode,
                "path": args.path,
            }
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    dsn = parser.add_mutually_exclusive_group(required=True)
    dsn.add_argument("--pg-dsn")
    dsn.add_argument("--pg-dsn-file", type=Path)
    parser.add_argument("--existing-pg-data-dir", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--bootstrap-admin-dsn-file", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--pg-log", type=Path)
    parser.add_argument("--bank-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--path", choices=["control", "pushdown", "equivalent", "legacy"], required=True)
    parser.add_argument("--mode", choices=["rrf", "bge"], default="rrf")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--take", type=int, default=81)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--ids", nargs="*")
    args = parser.parse_args()
    if args.pg_dsn_file:
        args.pg_dsn = args.pg_dsn_file.read_text().strip()
    if args.existing_pg_data_dir is not None and args.api_key_file is None:
        parser.error("Existing PG verification requires --api-key-file")
    if args.bootstrap_admin_dsn_file and (args.path != "legacy" or args.existing_pg_data_dir is None):
        parser.error("Metadata bootstrap is only allowed for an explicit existing-PG legacy baseline")
    if args.mode == "bge" and args.model_path is None:
        parser.error("BGE mode requires --model-path")
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
