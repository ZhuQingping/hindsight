"""Shared types, complete context packing, ingestion and original LoCoMo F1 for runner.py."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import inspect
import json
import os
import re
import string
import sys
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterator, Literal, TypeVar, cast
from urllib.parse import quote, urlsplit

import aiohttp
import numpy as np
import regex
import tiktoken
from hindsight_api.engine.chunk_ids import parse_chunk_id
from hindsight_api.engine.llm_interface import LLMInterface
from hindsight_api.engine.llm_wrapper import create_llm_provider
from hindsight_api.engine.response_models import TokenUsage
from nltk.stem import PorterStemmer
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

VERSION = "contextbase-memory-support-v1"
SOURCE_FILES = MappingProxyType({"dataset": "locomo10.json", "scoring": "locomo_evaluation.py"})
DEPENDENCIES = ("aiohttp", "pydantic", "nltk", "numpy", "regex", "tiktoken")
T = TypeVar("T", bound=BaseModel)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictModel):
    path: str
    url: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Sources(StrictModel):
    dataset: Source
    scoring: Source


class Credential(StrictModel):
    env: str | None = None
    file: str | None = None

    @model_validator(mode="after")
    def one_reference(self) -> Credential:
        if bool(self.env) == bool(self.file):
            raise ValueError("Specify exactly one credential env name or private JSON file path")
        return self

    def resolve(self) -> str:
        if self.env:
            value = os.environ.get(self.env)
            if not value:
                raise ValueError(f"Credential environment variable {self.env} is not set")
            return value
        # Only the reference is frozen. Never copy the secret into a run manifest.
        payload = PrivateKey.model_validate_json(Path(os.path.expandvars(self.file or "")).expanduser().read_text())
        return payload.secret


class PrivateKey(BaseModel):
    secret: str


class ModelSettings(StrictModel):
    provider: Literal["openai-codex", "openai", "gemini"]
    model: str = Field(min_length=1)
    reasoning_effort: str | None = None
    temperature: float | None = None
    output_tokens_limit: int | None = Field(default=None, gt=0)
    api_key_env: str | None = None
    base_url: str = ""
    codex_home: str | None = None

    @model_validator(mode="after")
    def effective_parameters(self) -> ModelSettings:
        if self.provider == "openai-codex" and (self.temperature is not None or self.output_tokens_limit is not None):
            raise ValueError("Codex transport does not forward these limits; use null instead of claiming they apply")
        if self.provider != "openai-codex" and not self.api_key_env:
            raise ValueError("API-key providers require an explicit api_key_env; there is no model fallback")
        if self.base_url and (urlsplit(self.base_url).username or urlsplit(self.base_url).query):
            raise ValueError("Do not put credentials in model URLs")
        return self


class MemoryProfile(StrictModel):
    """Declared service settings, kept distinct from snapshots returned by the server."""

    retain_provider: str
    retain_model: str
    retain_reasoning_effort: str | None = None
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int = Field(gt=0)
    reranker: str
    service_revision: str


class PackingSettings(StrictModel):
    algorithm: Literal["complete-json-separate-budgets-v2"] = "complete-json-separate-budgets-v2"
    tokenizer: Literal["o200k_base", "cl100k_base"] = "o200k_base"
    max_tokens: int = Field(default=8192, ge=32)
    fact_tokens: int = Field(default=4000, ge=0)
    chunk_tokens: int = Field(default=4000, ge=0)
    fact_order: Literal["recall_order"] = "recall_order"
    chunk_order: Literal["response_order"] = "response_order"

    @model_validator(mode="after")
    def budgets(self) -> PackingSettings:
        if self.fact_tokens + self.chunk_tokens > self.max_tokens:
            raise ValueError("Fact and chunk quotas cannot exceed the total context budget")
        return self


class RecallSettings(StrictModel):
    budget: Literal["low", "mid", "high"] = "high"
    max_tokens: int = Field(default=8192, gt=0)
    max_chunk_tokens: int = Field(default=8192, gt=0)


class Config(StrictModel):
    schema_version: Literal[2] = 2
    protocol: Literal["amb-locomo-cat1to4-packed-v1"] = "amb-locomo-cat1to4-packed-v1"
    sources: Sources
    categories: tuple[Literal[1], Literal[2], Literal[3], Literal[4]] = (1, 2, 3, 4)
    timestamp_policy: Literal["naive-session-dates-as-UTC"] = "naive-session-dates-as-UTC"
    judge_protocol: Literal["pinned-amb-locomo-judge"] = "pinned-amb-locomo-judge"
    f1_protocol: Literal["original-locomo-unchanged"] = "original-locomo-unchanged"
    conversations: list[str] = Field(min_length=1)
    reuse_banks: dict[str, str] = Field(default_factory=dict)
    # A limit is a declared smoke scope, never silently presented as the full split.
    question_limit_per_conversation: int | None = Field(default=None, gt=0)
    api_url: str
    credential: Credential
    memory_profile: MemoryProfile
    answer: ModelSettings
    judge: ModelSettings
    packing: PackingSettings = Field(default_factory=PackingSettings)
    recall: RecallSettings = Field(default_factory=RecallSettings)
    concurrency: int = Field(default=4, ge=1, le=32)
    request_timeout_s: float = Field(default=180, gt=0)
    ingestion_timeout_s: float = Field(default=3600, gt=0)
    poll_interval_s: float = Field(default=5, ge=0.01)
    model_max_attempts: int = Field(default=2, ge=1, le=4)
    enable_observations: Literal[False] = False
    retain_environment: Literal[True] = True

    @model_validator(mode="after")
    def scope_and_target(self) -> Config:
        if len(set(self.conversations)) != len(self.conversations):
            raise ValueError("Conversation IDs must be unique")
        if self.reuse_banks:
            if set(self.reuse_banks) != set(self.conversations):
                raise ValueError("reuse_banks must name exactly the selected conversations")
            if len(set(self.reuse_banks.values())) != len(self.reuse_banks):
                raise ValueError("Each conversation must reuse a different Bank")
            if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,53}", bank) for bank in self.reuse_banks.values()):
                raise ValueError("Reused Bank IDs must be canonical")
        url = urlsplit(self.api_url)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.query or url.fragment:
            raise ValueError("api_url must be an HTTP(S) service URL without credentials/query/fragment")
        if url.path not in ("", "/"):
            raise ValueError("api_url must point at the service root")
        return self


class RawQA(BaseModel):
    question: str
    answer: str | int | None = None
    category: int
    evidence: list[str] = Field(default_factory=list)


class RawConversation(BaseModel):
    sample_id: str
    conversation: dict[str, JsonValue]
    qa: list[RawQA]


class Session(StrictModel):
    document_id: str
    timestamp: str
    content: str


class Question(StrictModel):
    id: str
    conversation_id: str
    original_index: int
    category: int
    question: str


class Conversation(StrictModel):
    id: str
    bank_id: str
    speaker_a: str
    speaker_b: str
    sessions: list[Session]
    questions: list[Question]
    reference_date: str
    message_count: int


class Manifest(StrictModel):
    schema_version: Literal[2] = 2
    harness_version: str = VERSION
    run_id: str
    created_at: str
    config: Config
    conversations: list[Conversation]
    question_scope_sha256: str
    harness_sha256: str
    environment: dict[str, str]
    client_source_sha256: dict[str, str]
    fingerprint: str = ""


class Fact(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    text: str
    document_id: str | None = None
    chunk_id: str | None = None
    mentioned_at: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class Chunk(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str


class RecallReply(BaseModel):
    model_config = ConfigDict(extra="allow")
    results: list[Fact]
    chunks: dict[str, Chunk] | None = None


class PackedFact(StrictModel):
    text: str
    document: str | None = None
    mentioned_at: str | None = None
    occurred_start: str | None = None
    occurred_end: str | None = None


class PackedChunk(StrictModel):
    document: str
    index: int
    timestamp: str
    text: str


class Payload(StrictModel):
    facts: list[PackedFact] = Field(default_factory=list)
    chunks: list[PackedChunk] = Field(default_factory=list)

    def render(self) -> str:
        return self.model_dump_json(exclude_none=True)


class Omitted(StrictModel):
    id: str
    reason: Literal["fact_quota", "chunk_quota"]


class Packed(StrictModel):
    text: str
    tokens: int
    fact_tokens: int
    chunk_tokens: int
    included_fact_ids: list[str]
    included_chunk_ids: list[str]
    omitted: list[Omitted]


class CreateBank(StrictModel):
    name: str
    description: str
    enable_observations: bool = False


class RetainItem(StrictModel):
    content: str
    timestamp: str
    document_id: str
    context: str


class RetainBody(StrictModel):
    items: list[RetainItem]
    asynchronous: bool = Field(default=True, alias="async")
    operation_id: str


class RetainReply(BaseModel):
    operation_id: str | None = None
    operation_ids: list[str] | None = None


class RetainMetadata(BaseModel):
    model_config = ConfigDict(extra="allow")
    extraction_errors_count: int = 0
    facts_committed: bool | None = None


class Operation(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    operation_id: str | None = None
    operation_type: str | None = None
    task_type: str | None = None
    status: str
    result_metadata: RetainMetadata | None = None


class OperationsPage(BaseModel):
    operations: list[Operation]
    total: int


class DocumentHeader(BaseModel):
    id: str
    bank_id: str


class DocumentsPage(BaseModel):
    items: list[DocumentHeader]
    total: int


class Document(BaseModel):
    id: str
    bank_id: str
    original_text: str | None = None


class RuntimeSnapshot(BaseModel):
    """These response keys evolve with the service; do not silently discard them."""

    model_config = ConfigDict(extra="allow")


class Attempt(StrictModel):
    stage: Literal["answer", "judge"]
    state: Literal["started", "completed", "failed", "interrupted_unknown"]
    at: str
    elapsed_s: float | None = None
    error: str | None = None
    usage: TokenUsage | None = None


class BankState(StrictModel):
    created: bool = False
    submission: RetainReply | None = None
    verified: bool = False
    ingestion_elapsed_s: float | None = None


class State(StrictModel):
    fingerprint: str
    status: str = "prepared"
    banks: dict[str, BankState] = Field(default_factory=dict)
    answer_elapsed_s: float = 0
    runtime_consistent: bool = True


class HTTPFailure(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        super().__init__(f"HTTP {status}: {body[:500]}")


def now() -> str:
    return datetime.now(UTC).isoformat()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(model: BaseModel) -> str:
    return hashlib.sha256(
        json.dumps(model.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def save_model(path: Path, model: BaseModel) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def read_model(path: Path, model: type[T]) -> T:
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def environment() -> dict[str, str]:
    return {"python": sys.version, **{name: importlib.metadata.version(name) for name in DEPENDENCIES}}


def client_sources() -> dict[str, str]:
    from hindsight_api.engine import llm_wrapper
    from hindsight_api.engine.providers import codex_llm, gemini_llm, openai_compatible_llm, openai_responses_llm

    modules = (codex_llm, gemini_llm, openai_compatible_llm, openai_responses_llm, llm_wrapper)
    return {module.__name__: file_sha(Path(inspect.getfile(module))) for module in modules}


def corpus(config: Config, run_id: str, path: Path) -> list[Conversation]:
    raw = [RawConversation.model_validate(x) for x in json.loads(path.read_text())]
    indexed = {c.sample_id: c for c in raw}
    result: list[Conversation] = []
    for conversation_id in config.conversations:
        if conversation_id not in indexed:
            raise ValueError(f"Unknown conversation {conversation_id}")
        source = indexed[conversation_id]
        history = source.conversation
        session_keys = sorted(
            (k for k, v in history.items() if re.fullmatch(r"session_\d+", k) and isinstance(v, list)),
            key=lambda k: int(k.removeprefix("session_")),
        )
        sessions: list[Session] = []
        count = 0
        for key in session_keys:
            date = datetime.strptime(str(history[key + "_date_time"]), "%I:%M %p on %d %B, %Y").replace(tzinfo=UTC)
            content = json.dumps(history[key])
            count += len(cast(list[JsonValue], history[key]))
            sessions.append(
                Session(document_id=f"{conversation_id}_{key}", timestamp=date.isoformat(), content=content)
            )
        if not sessions:
            raise ValueError("Conversation has no sessions")
        questions = [
            Question(
                id=f"{conversation_id}_q{i:03d}",
                conversation_id=conversation_id,
                original_index=i,
                category=q.category,
                question=q.question,
            )
            for i, q in enumerate(source.qa)
            if q.category in config.categories
        ]
        if config.question_limit_per_conversation:
            questions = questions[: config.question_limit_per_conversation]
        if not questions or any(source.qa[q.original_index].answer is None for q in questions):
            raise ValueError("Selected scope has no questions or missing gold answers")
        bank_id = f"{run_id}_{conversation_id.replace('-', '_')}"
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,53}", bank_id):
            raise ValueError("run_id plus conversation must form a canonical Bank ID of at most 54 characters")
        result.append(
            Conversation(
                id=conversation_id,
                bank_id=bank_id,
                speaker_a=str(history["speaker_a"]),
                speaker_b=str(history["speaker_b"]),
                sessions=sessions,
                questions=questions,
                reference_date=sessions[-1].timestamp,
                message_count=count,
            )
        )
    return result


@contextmanager
def run_lock(directory: Path) -> Iterator[None]:
    # File locking is local to this CLI, never a PostgreSQL advisory lock. The OS
    # releases it after crashes, so resuming does not require deleting a stale marker.
    import fcntl

    with (directory / ".run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Another command owns this run directory") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def pack_context(recalled: RecallReply, conversation: Conversation, settings: PackingSettings) -> Packed:
    """Use only returned evidence and input-history dates; never receives QA gold/evidence annotations."""
    encoder = tiktoken.get_encoding(settings.tokenizer)
    payload = Payload()
    empty_tokens = len(encoder.encode(payload.render()))
    documents = {s.document_id: s for s in conversation.sessions}
    omitted: list[Omitted] = []
    fact_ids: list[str] = []
    chunk_ids: list[str] = []
    # Unlike v1's prefix slice, separate quotas reserve room for original text.
    # Measure full serializations each time: token counts are not additive at boundaries.
    fact_budget = min(settings.fact_tokens, settings.max_tokens - empty_tokens - settings.chunk_tokens)
    for fact in recalled.results:
        if fact.document_id is not None and fact.document_id not in documents:
            raise ValueError("Recall returned a document outside the question's conversation")
        candidate = PackedFact(
            text=fact.text,
            document=fact.document_id,
            mentioned_at=fact.mentioned_at,
            occurred_start=fact.occurred_start,
            occurred_end=fact.occurred_end,
        )
        trial = Payload(facts=[*payload.facts, candidate])
        tokens = len(encoder.encode(trial.render()))
        if tokens - empty_tokens <= fact_budget:
            payload.facts.append(candidate)
            fact_ids.append(fact.id)
        else:
            omitted.append(Omitted(id=fact.id, reason="fact_quota"))
    fact_total = len(encoder.encode(payload.render()))
    for identifier, chunk in (recalled.chunks or {}).items():
        ref = parse_chunk_id(identifier)
        if ref is None or ref.bank_id != conversation.bank_id or ref.document_id not in documents:
            raise ValueError("Chunk identity is invalid or outside the question's Bank")
        source = documents[ref.document_id]
        candidate = PackedChunk(
            document=ref.document_id, index=ref.chunk_index, timestamp=source.timestamp, text=chunk.text
        )
        trial = Payload(facts=payload.facts, chunks=[*payload.chunks, candidate])
        tokens = len(encoder.encode(trial.render()))
        if tokens <= settings.max_tokens and tokens - fact_total <= settings.chunk_tokens:
            payload.chunks.append(candidate)
            chunk_ids.append(identifier)
        else:
            omitted.append(Omitted(id=identifier, reason="chunk_quota"))
    if recalled.chunks and settings.chunk_tokens > 0 and not chunk_ids:
        raise ValueError("No complete original passage fits the reserved chunk quota; do not silently run facts-only")
    text = payload.render()
    total = len(encoder.encode(text))
    if total > settings.max_tokens:
        raise ValueError("Context envelope itself exceeds the token budget")
    return Packed(
        text=text,
        tokens=total,
        fact_tokens=fact_total - empty_tokens,
        chunk_tokens=total - fact_total,
        included_fact_ids=fact_ids,
        included_chunk_ids=chunk_ids,
        omitted=omitted,
    )


class FrozenScoring:
    def __init__(self, directory: Path) -> None:
        source = ast.parse((directory / "inputs/locomo_evaluation.py").read_text())
        names = {"normalize_answer", "f1_score", "f1"}
        functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
        if {node.name for node in functions} != names:
            raise ValueError("Frozen scoring source is missing original functions")
        # An exec namespace has dynamically defined names, unlike structured runtime records.
        namespace: dict[str, Any] = {
            "Counter": Counter,
            "string": string,
            "np": np,
            "ps": PorterStemmer(),
            "regex": regex,
        }
        statements: list[ast.stmt] = list(functions)
        exec(compile(ast.Module(body=statements, type_ignores=[]), "frozen_locomo_scoring", "exec"), namespace)
        self.single = cast(Callable[[str, str], float], namespace["f1_score"])
        self.multi = cast(Callable[[str, str], float], namespace["f1"])
        self.gold = {
            c.sample_id: c.qa
            for c in [
                RawConversation.model_validate(x) for x in json.loads((directory / "inputs/locomo10.json").read_text())
            ]
        }

    def gold_answer(self, question: Question) -> str:
        gold = str(self.gold[question.conversation_id][question.original_index].answer)
        return gold.split(";")[0].strip() if question.category == 3 else gold

    def f1(self, question: Question, answer: str) -> float:
        scoring = self.multi if question.category == 1 else self.single
        return float(scoring(answer, self.gold_answer(question)))


def redact_snapshot(value: JsonValue) -> JsonValue:
    if isinstance(value, list):
        return [redact_snapshot(item) for item in value]
    if isinstance(value, dict):
        protected = {
            "api_key",
            "secret",
            "password",
            "authorization",
            "access_token",
            "refresh_token",
            "client_secret",
            "database_url",
            "dsn",
        }
        return {
            key: "[redacted]"
            if key.lower() in protected or key.lower().endswith(("_api_key", "_password", "_secret", "_database_url"))
            else redact_snapshot(item)
            for key, item in value.items()
        }
    return value


class BankHTTP:
    def __init__(self, session: aiohttp.ClientSession, config: Config, secret: str) -> None:
        self.session = session
        self.config = config
        self.secret = secret

    async def request(
        self,
        method: str,
        path: str,
        response_type: type[T],
        body: BaseModel | None = None,
        *,
        create_only: bool = False,
    ) -> T:
        if self.config.reuse_banks:
            prefixes = ["/v1/default/banks/" + bank for bank in self.config.reuse_banks.values()]
            read = method == "GET" and (
                path == "/version" or any(path == p or path.startswith(p + "/") for p in prefixes)
            )
            recall = method == "POST" and any(path == p + "/memories/recall" for p in prefixes)
            if not (read or recall):
                raise ValueError("Reused Banks are read-only: only scoped GET and recall are allowed")
        headers = {"Authorization": "Bearer " + self.secret}
        if create_only:
            headers["If-None-Match"] = "*"
        payload = body.model_dump(mode="json", by_alias=True) if body else None
        async with self.session.request(
            method, self.config.api_url.rstrip("/") + path, headers=headers, json=payload
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise HTTPFailure(response.status, text.replace(self.secret, "[redacted]"))
            return response_type.model_validate_json(text)


def make_provider(settings: ModelSettings, timeout: float) -> LLMInterface:
    key = os.environ.get(settings.api_key_env, "") if settings.api_key_env else ""
    if settings.api_key_env and not key:
        raise ValueError(f"Model key environment variable {settings.api_key_env} is not set")
    return cast(
        LLMInterface,
        create_llm_provider(
            provider=settings.provider,
            api_key=key,
            base_url=settings.base_url,
            model=settings.model,
            reasoning_effort=settings.reasoning_effort,
            timeout=timeout,
            codex_home=os.path.expandvars(settings.codex_home) if settings.codex_home else None,
        ),
    )


def retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    return (
        isinstance(error, (TimeoutError, aiohttp.ClientConnectionError))
        or status == 429
        or (isinstance(status, int) and status >= 500)
    )


class Ingestion:
    def __init__(self, directory: Path, manifest: Manifest, http: BankHTTP | None = None) -> None:
        self.directory = directory
        self.manifest = manifest
        self.config = manifest.config
        self.state = read_model(directory / "state.json", State)
        if self.state.fingerprint != manifest.fingerprint:
            raise ValueError("State belongs to another protocol")
        self.http = http

    def save_state(self) -> None:
        save_model(self.directory / "state.json", self.state)

    def prefix(self, conversation: Conversation) -> str:
        return "/v1/default/banks/" + conversation.bank_id

    async def request(
        self,
        conversation: Conversation,
        method: str,
        suffix: str,
        response_type: type[T],
        body: BaseModel | None = None,
        *,
        create_only: bool = False,
    ) -> T:
        if self.http is None:
            raise RuntimeError("This offline command has no HTTP client")
        return await self.http.request(
            method, self.prefix(conversation) + suffix, response_type, body, create_only=create_only
        )

    async def all_operations(self, conversation: Conversation) -> list[Operation]:
        operations: list[Operation] = []
        offset = 0
        while True:
            page = await self.request(conversation, "GET", f"/operations?limit=100&offset={offset}", OperationsPage)
            for row in page.operations:
                identifier = row.operation_id or row.id
                if identifier is None:
                    raise ValueError("Operation has no identity")
                operations.append(
                    await self.request(conversation, "GET", "/operations/" + quote(identifier, safe=""), Operation)
                )
            offset += len(page.operations)
            if offset >= page.total:
                return operations
            if not page.operations:
                raise ValueError("Operation pagination ended before total")

    async def verify_documents(self, conversation: Conversation) -> None:
        ids: set[str] = set()
        offset = 0
        while True:
            page = await self.request(conversation, "GET", f"/documents?limit=100&offset={offset}", DocumentsPage)
            if any(row.bank_id != conversation.bank_id for row in page.items):
                raise ValueError("Document listing crossed a Bank boundary")
            ids.update(row.id for row in page.items)
            offset += len(page.items)
            if offset >= page.total:
                break
            if not page.items:
                raise ValueError("Document pagination ended before total")
        if ids != {s.document_id for s in conversation.sessions}:
            raise ValueError("Bank document set does not match the frozen ingestion scope")
        for session in conversation.sessions:
            doc = await self.request(conversation, "GET", "/documents/" + quote(session.document_id, safe=""), Document)
            if doc.bank_id != conversation.bank_id or doc.original_text is None:
                raise ValueError("Original document is unavailable or belongs to another Bank")
            if json.loads(doc.original_text) != json.loads(session.content):
                raise ValueError("Stored original document differs from the frozen session")

    async def check_runtime(self, conversation: Conversation, label: str) -> None:
        snapshot = await self.request(conversation, "GET", "/config", RuntimeSnapshot)
        sanitized = RuntimeSnapshot.model_validate(redact_snapshot(snapshot.model_dump(mode="json")))
        baseline = self.directory / (conversation.id + "-server-config-before.json")
        if baseline.exists() and canonical_sha(read_model(baseline, RuntimeSnapshot)) != canonical_sha(sanitized):
            self.state.runtime_consistent = False
            self.save_state()
            raise ValueError("Public Bank configuration changed; use a new run_id")
        save_model(self.directory / (conversation.id + "-server-config-" + label + ".json"), sanitized)

    async def ingest(self) -> None:
        if self.config.reuse_banks:
            raise ValueError("Cannot ingest into reused Banks; use read-only verify")
        self.state.status = "ingesting"
        self.save_state()
        for conversation in self.manifest.conversations:
            bank = self.state.banks.setdefault(conversation.id, BankState())
            if bank.verified:
                await self.check_runtime(conversation, "resume")
                await self.verify_documents(conversation)
                continue
            started = time.monotonic()
            if not bank.created:
                body = CreateBank(
                    name=conversation.bank_id,
                    description=f"{self.manifest.run_id}: {conversation.id} LoCoMo isolated run",
                )
                profile = await self.request(conversation, "PUT", "", RuntimeSnapshot, body, create_only=True)
                save_model(self.directory / (conversation.id + "-profile.json"), profile)
                bank.created = True
                self.save_state()
            await self.check_runtime(conversation, "before")
            if bank.submission is None:
                # Retain content is built exclusively from sessions, never the QA or evidence arrays.
                items = [
                    RetainItem(
                        content=s.content,
                        timestamp=s.timestamp,
                        document_id=s.document_id,
                        context=f"Conversation between {conversation.speaker_a} and {conversation.speaker_b}; relative dates use the session timestamp.",
                    )
                    for s in conversation.sessions
                ]
                operation_id = str(uuid.uuid5(uuid.NAMESPACE_URL, self.manifest.fingerprint + ":" + conversation.id))
                body = RetainBody(items=items, operation_id=operation_id)
                save_model(self.directory / (conversation.id + "-ingestion-request.json"), body)
                bank.submission = await self.request(conversation, "POST", "/memories", RetainReply, body)
                if not (bank.submission.operation_ids or bank.submission.operation_id):
                    raise ValueError("Async ingestion did not return operation IDs")
                self.save_state()
            while True:
                operations = await self.all_operations(conversation)
                save_model(
                    self.directory / (conversation.id + "-operations.json"),
                    OperationsPage(operations=operations, total=len(operations)),
                )
                if not operations:
                    raise ValueError("Submitted ingestion operation is missing")
                roots = set(bank.submission.operation_ids or [bank.submission.operation_id])
                if not roots.issubset({op.operation_id or op.id for op in operations}):
                    raise ValueError("Submitted parent operation was not found")
                if any(op.status in ("failed", "cancelled", "not_found") for op in operations):
                    raise ValueError("An ingestion operation failed; no question was started")
                if any(op.result_metadata and op.result_metadata.extraction_errors_count for op in operations):
                    raise ValueError("Ingestion reported extraction errors")
                if all(op.status == "completed" for op in operations):
                    # Parent completion and cached stats alone were insufficient in v1.
                    await self.verify_documents(conversation)
                    break
                if time.monotonic() - started > self.config.ingestion_timeout_s:
                    raise TimeoutError("Ingestion timed out; memory is retained but answering remains blocked")
                await asyncio.sleep(self.config.poll_interval_s)
            bank.verified = True
            bank.ingestion_elapsed_s = time.monotonic() - started
            self.save_state()
            print(
                json.dumps(
                    {"bank": conversation.bank_id, "stage": "ingested", "documents": len(conversation.sessions)}
                ),
                flush=True,
            )
        self.state.status = "ingested"
        self.save_state()


class Message(StrictModel):
    role: Literal["user", "system"]
    content: str


class ChunkBudget(StrictModel):
    max_tokens: int


class RecallInclude(StrictModel):
    entities: None = None
    chunks: ChunkBudget


class RecallBody(StrictModel):
    query: str
    budget: str
    max_tokens: int
    query_timestamp: str
    include: RecallInclude


class Preview(StrictModel):
    fingerprint: str
    packing: Packed
    note: str = "Offline packaging only; no API/model calls and no new answers or scores."
