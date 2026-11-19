"""Pinned AMB LoCoMo integration. Only explicit ingest/run commands access services.

The AMB dataset, RAG mode, judge and EvalRunner run unchanged. A declared context
hook prevents AMB's raw-response shortcut from bypassing the packed 8K budget.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import hashlib
import importlib.util
import json
import logging
import os
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, Literal

import aiohttp
import numpy as np
import tiktoken
from hindsight_api.engine.llm_interface import LLMInterface
from hindsight_api.engine.response_models import TokenUsage
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, model_validator


def module_from_file(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CORE_SOURCE = Path(__file__).with_name("support.py")
core = module_from_file("_contextbase_locomo_core", CORE_SOURCE)
AMB_COMMIT = "28b644bd4dd653c0207c7507280439390c829155"
AMB_REPO = "https://github.com/vectorize-io/agent-memory-benchmark.git"
VERSION = "contextbase-amb-locomo-v1"
QUESTION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("amb_contextbase_question", default=None)
ProviderFactory = Callable[[Any, float], LLMInterface]


class Config(core.Config):
    judge_protocol: Literal["pinned-amb-locomo-judge"] = "pinned-amb-locomo-judge"
    amb_checkout: str
    amb_commit: Literal["28b644bd4dd653c0207c7507280439390c829155"] = AMB_COMMIT
    # AMB uses this tokenizer. Keep the original scorer and legacy packing utility,
    # but count the actual injected context in both tokenizers for comparison.
    upstream_tokenizer: Literal["cl100k_base"] = "cl100k_base"
    checkpoint_source: core.Source | None = None
    retrieval_source: core.Source | None = None
    resume_connection_failures: bool = False

    @model_validator(mode="after")
    def independent_source_modes(self) -> Config:
        if self.checkpoint_source and self.retrieval_source:
            raise ValueError("Choose checkpoint continuation or a fresh retrieval-only experiment")
        if self.retrieval_source and (not self.reuse_banks or self.resume_connection_failures):
            raise ValueError("Retrieval-only experiments require explicit read-only Banks and no recovery override")
        return self

    @property
    def source_ref(self) -> core.Source | None:
        return self.checkpoint_source or self.retrieval_source


class RetrievalOrigin(core.StrictModel):
    run_id: str
    manifest_sha256: str


class Manifest(core.Manifest):
    harness_version: str = VERSION
    amb_repository: str = AMB_REPO
    config: Config
    core_sha256: str
    amb_files: dict[str, str]
    checkpoint_imports: dict[str, str] = Field(default_factory=dict)
    retrieval_origin: RetrievalOrigin | None = None
    integration_notes: list[str] = Field(
        default_factory=lambda: [
            "Unmodified AMB LoComoDataset loaders/prompts, RAGMode, GeminiJudge and EvalRunner.",
            "Context-only hook: packed JSON is injected verbatim; raw recall is archived separately.",
            "Explicit ingest then AMB skip_ingestion; no oracle, failed-only replacement or Bank deletion.",
            "Original LoCoMo F1 is supplementary; category-3 reference answers use the original semicolon rule.",
            "Existing provider factory bridges async transports to AMB's synchronous LLM interface.",
        ]
    )


class AnswerData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasoning: str = Field(description="Step-by-step explanation of how you used the context to arrive at the answer.")
    answer: str = Field(
        description="The final concise answer to the question. If the context lacks the information, say so."
    )


class JudgeData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correct: StrictBool
    reason: str


class ResponseSchema(core.StrictModel):
    properties: dict[str, JsonValue]
    required: list[str]


class Sealed(core.StrictModel):
    fingerprint: str
    checksum: str = ""


class CallRecord(Sealed):
    question_id: str
    stage: Literal["answer", "judge"]
    prompt: str
    response_schema: ResponseSchema
    status: Literal["started", "completed", "failed", "interrupted"] = "started"
    response: str | dict[str, JsonValue] | None = None
    parsed: AnswerData | JudgeData | None = None
    attempts: list[core.Attempt] = Field(default_factory=list)


class RetrievalRecord(Sealed):
    question_id: str
    bank_id: str
    recall: core.RecallReply | None = None
    packing: core.Packed | None = None
    error: str | None = None
    retrieval_elapsed_ms: float | None = None


class NativeResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    query_id: str
    answer: str
    correct: StrictBool
    context: str
    context_tokens: int
    retrieve_time_ms: float
    reasoning: str
    gold_answers: list[str | int | float]
    judge_reason: str
    meta: dict[str, JsonValue]


class SavedResult(Sealed):
    question_id: str
    amb_result: NativeResult
    answer_f1: float


class Summary(core.StrictModel):
    fingerprint: str
    protocol: str
    amb_commit: str
    valid_complete_run: bool
    expected: int
    completed: int
    failed: int
    pending: int
    correct: int
    accuracy_all_expected: float
    answer_f1_all_expected: float
    context_tokenizer: str
    context_tokens_total: int
    context_tokens_mean: float | None
    context_tokens_max: int | None
    amb_cl100k_context_tokens_mean: float | None
    full_answer_prompt_tokens_mean: float | None
    retrieval_sample_count: int
    retrieval_measurement: Literal["live-http-recall", "reused-source-recall"] = "live-http-recall"
    retrieval_source_run_id: str | None = None
    retrieval_ms_mean: float | None
    retrieval_ms_p50: float | None
    retrieval_ms_p95: float | None
    model_usage: dict[str, TokenUsage]
    attempts_with_unknown_usage: int
    retained_banks: list[str]
    note: str = "All expected questions stay in denominator; tokens use recorded context, prompt or provider usage as labelled. Retain/internal model usage is excluded."


def git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def upstream_files(checkout: Path) -> list[str]:
    if git(checkout, "rev-parse", "HEAD") != AMB_COMMIT:
        raise ValueError("AMB checkout must be at the fixed commit")
    # Copy tracked files only, after checking their contents against the commit.
    # This avoids importing untracked provider code or downloading result/data blobs.
    paths = git(checkout, "ls-tree", "-r", "--name-only", AMB_COMMIT, "src", "pyproject.toml", "uv.lock").splitlines()
    git(checkout, "diff", "--exit-code", AMB_COMMIT, "--", "src", "pyproject.toml", "uv.lock")
    if not paths or any(not (checkout / path).is_file() for path in paths):
        raise ValueError("AMB source checkout is incomplete")
    return paths


def init_run(config_path: Path, directory: Path, run_id: str) -> Manifest:
    config = core.read_model(config_path, Config)
    checkout = Path(os.path.expandvars(config.amb_checkout)).expanduser().resolve()
    paths = upstream_files(checkout)
    config.amb_checkout = str(checkout)
    sources = {
        name: Path(os.path.expandvars(getattr(config.sources, name).path)).expanduser().resolve()
        for name in core.SOURCE_FILES
    }
    for name, path in sources.items():
        if core.file_sha(path) != getattr(config.sources, name).sha256:
            raise ValueError(f"Source hash mismatch: {name}")
    for settings in (config.answer, config.judge):
        if settings.provider == "openai-codex":
            home = settings.codex_home or os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
            settings.codex_home = str(Path(os.path.expandvars(home)).expanduser().resolve())
    conversations = core.corpus(config, run_id, sources["dataset"])
    for conversation in conversations:
        if config.reuse_banks:
            conversation.bank_id = config.reuse_banks[conversation.id]
    scope = [q.model_dump(mode="json") for c in conversations for q in c.questions]
    runtime = core.environment() | {
        name: core.importlib.metadata.version(name) for name in ("rich", "google-genai", "openai")
    }
    manifest = Manifest(
        run_id=run_id,
        created_at=core.now(),
        config=config,
        conversations=conversations,
        question_scope_sha256=hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest(),
        harness_sha256=core.file_sha(Path(__file__)),
        core_sha256=core.file_sha(CORE_SOURCE),
        environment=runtime,
        client_source_sha256=core.client_sources(),
        amb_files={path: core.file_sha(checkout / path) for path in paths},
    )
    if config.reader_profile != "amb-default":
        manifest.integration_notes[0] = (
            "Unmodified AMB loaders, RAGMode, GeminiJudge and EvalRunner; "
            "explicitly versioned global reader guidance prepends the original reader prompt."
        )
        manifest.integration_notes.append(f"Reader profile: {config.reader_profile}; judge prompt unchanged.")
    source_manifest = None
    source_directory = None
    if config.source_ref is not None:
        source_path = Path(config.source_ref.path).expanduser().resolve()
        if core.file_sha(source_path) != config.source_ref.sha256:
            raise ValueError("Checkpoint source manifest hash changed")
        raw = json.loads(source_path.read_text())
        fingerprint = raw["fingerprint"]
        raw["fingerprint"] = ""
        if hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != fingerprint:
            raise ValueError("Checkpoint source manifest is invalid")
        source_manifest = core.read_model(source_path, Manifest)
        manifest.retrieval_origin = source_manifest.retrieval_origin
        # A run that originally created Banks must resume through the read-only
        # guard. The only permitted transition names those exact source Banks.
        if config.reuse_banks != source_manifest.config.reuse_banks and (
            source_manifest.config.reuse_banks
            or config.reuse_banks != {c.id: c.bank_id for c in source_manifest.conversations}
        ):
            raise ValueError("Checkpoint recovery must reuse the exact source Banks read-only")
        excluded = {
            "checkpoint_source",
            "retrieval_source",
            "resume_connection_failures",
            "model_max_attempts",
            "concurrency",
            "reuse_banks",
        }
        if config.retrieval_source is not None:
            # Same stored memories, query scope, API recall, models and judge.
            # Only the declared reader instructions/packing may change; all
            # answers and verdicts will be generated anew for the entire scope.
            excluded |= {"packing", "reader_profile", "protocol"}
        previous = source_manifest.config.model_dump(exclude=excluded)
        current = config.model_dump(exclude=excluded)
        if previous != current or source_manifest.conversations != manifest.conversations:
            raise ValueError("Checkpoint reuse requires identical questions, Banks, models and all evaluation settings")
        if config.retrieval_source is None and config.concurrency != source_manifest.config.concurrency:
            if not config.resume_connection_failures or config.concurrency > source_manifest.config.concurrency:
                raise ValueError("Checkpoint transport recovery may only reduce concurrency")
        if config.retrieval_source is None and config.model_max_attempts != source_manifest.config.model_max_attempts:
            if (
                not config.resume_connection_failures
                or config.model_max_attempts != source_manifest.config.model_max_attempts + 1
            ):
                raise ValueError("Only one explicitly recorded extra transport attempt may be added")
        if (
            source_manifest.environment != runtime
            or source_manifest.client_source_sha256 != manifest.client_source_sha256
        ):
            raise ValueError("Checkpoint provider/runtime changed")
        source_directory = source_path.parent
        if config.retrieval_source is not None:
            validate_complete_retrieval_source(source_directory, source_manifest)
            manifest.retrieval_origin = source_manifest.retrieval_origin or RetrievalOrigin(
                run_id=source_manifest.run_id, manifest_sha256=config.retrieval_source.sha256
            )
            manifest.integration_notes.append(
                f"Retrieval-only source: {source_manifest.run_id}. No source answers/verdicts are adopted; "
                "recall timings are historical source measurements, not fresh recall measurements."
            )
        if source_manifest.amb_files != manifest.amb_files:
            raise ValueError("Source AMB code differs from this experiment")
        for filename, digest in (
            ("runner.py", source_manifest.harness_sha256),
            ("support.py", source_manifest.core_sha256),
        ):
            if core.file_sha(source_directory / filename) != digest:
                raise ValueError("Checkpoint source code was modified")
        for name, filename in core.SOURCE_FILES.items():
            if core.file_sha(source_directory / "inputs" / filename) != getattr(config.sources, name).sha256:
                raise ValueError("Checkpoint source inputs changed")
        manifest.checkpoint_imports = {
            str(path.relative_to(source_directory)): core.file_sha(path)
            for folder in ("retrievals", "calls", "results")
            for path in sorted((source_directory / folder).glob("*.json"))
        }
        for filename in [
            "state.json",
            "server-version-before.json",
            *[c.id + "-server-config-before.json" for c in source_manifest.conversations],
        ]:
            path = source_directory / filename
            if path.exists():
                manifest.checkpoint_imports[filename] = core.file_sha(path)
        if config.retrieval_source is not None:
            manifest.checkpoint_imports["summary.json"] = core.file_sha(source_directory / "summary.json")
    manifest.fingerprint = core.canonical_sha(manifest)
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "inputs").mkdir()
    for name, path in sources.items():
        shutil.copyfile(path, directory / "inputs" / core.SOURCE_FILES[name])
    shutil.copyfile(__file__, directory / "runner.py")
    shutil.copyfile(CORE_SOURCE, directory / "support.py")
    for path in paths:
        target = directory / "amb-source" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checkout / path, target)
    if source_manifest is not None and source_directory is not None:
        shutil.copyfile(source_directory / "manifest.json", directory / "inputs/checkpoint-source-manifest.json")
        retry_ids: set[str] = set()
        if config.resume_connection_failures:
            for path in (source_directory / "calls").glob("*.json"):
                record = unseal(path, CallRecord, source_manifest)
                if (
                    record.status == "failed"
                    and record.response is None
                    and record.attempts
                    and all(
                        a.state == "failed"
                        and a.usage is None
                        and a.error
                        in {"ConnectionTimeoutError", "ClientConnectorError", "ClientPayloadError", "TimeoutError"}
                        for a in record.attempts
                    )
                    and len(record.attempts) < config.model_max_attempts
                ):
                    retry_ids.add(record.question_id)
            for path in (source_directory / "retrievals").glob("*.json"):
                record = unseal(path, RetrievalRecord, source_manifest)
                if record.recall is None and record.error in {
                    None,  # An orphaned in-flight request with no response; keep the source record unchanged.
                    "interrupted_unknown",
                    "ConnectionTimeoutError",
                    "ClientConnectorError",
                    "ClientPayloadError",
                    "TimeoutError",
                }:
                    retry_ids.add(record.question_id)
        for name in manifest.checkpoint_imports:
            original = source_directory / name
            snapshot = directory / "checkpoint-source" / name
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, snapshot)
            if "/" not in name:
                if name not in {"state.json", "summary.json"}:
                    shutil.copyfile(original, directory / name)
                continue
            folder = Path(name).parts[0]
            if config.retrieval_source is not None and folder != "retrievals":
                continue  # Snapshot source proof, never adopt source answers or verdicts.
            record_type = {
                "calls": CallRecord,
                "retrievals": RetrievalRecord,
                "results": SavedResult,
            }[folder]
            record = unseal(original, record_type, source_manifest)
            if config.retrieval_source is not None:
                conversation = next(c for c in conversations if c.bank_id == record.bank_id)
                question = next(q for q in conversation.questions if amb_id(q) == record.question_id)
                record.packing = core.pack_context(record.recall, conversation, config.packing, query=question.question)
            if folder == "retrievals" and record.question_id in retry_ids and record.recall is None:
                continue
            if folder == "results" and record.question_id in retry_ids:
                continue  # Keep the operational failure in source evidence, never replace it there.
            if folder == "calls" and record.question_id in retry_ids and record.status == "failed":
                record.status = "interrupted"  # Attempts and their failures stay intact; one bounded continuation.
            record.fingerprint = manifest.fingerprint
            seal(directory / name, record)
    core.save_model(directory / "manifest.json", manifest)
    state = core.State(fingerprint=manifest.fingerprint)
    if (
        config.checkpoint_source is not None
        and source_manifest is not None
        and "state.json" in manifest.checkpoint_imports
    ):
        previous_state = core.read_model(directory / "checkpoint-source/state.json", core.State)
        if previous_state.fingerprint != source_manifest.fingerprint or not previous_state.runtime_consistent:
            raise ValueError("Cannot continue inconsistent source runtime/state")
        state.answer_elapsed_s = previous_state.answer_elapsed_s
        state.banks = {
            name: bank.model_copy(update={"created": False, "verified": False})
            for name, bank in previous_state.banks.items()
        }
    core.save_model(directory / "state.json", state)
    # Exercise the pinned dataset loader during offline preparation, before any Bank
    # can be created. A future upstream/data mismatch must not emerge after ingestion.
    runtime = components(Archive(directory, manifest))
    runtime.dataset.load_queries("locomo10")
    actual_docs = {doc.id: doc for doc in runtime.dataset.load_documents("locomo10")}
    expected_docs = {session.document_id: session for c in conversations for session in c.sessions}
    if set(actual_docs) != set(expected_docs) or any(
        actual_docs[key].content != session.content or actual_docs[key].timestamp != session.timestamp
        for key, session in expected_docs.items()
    ):
        raise ValueError("AMB document/date scope differs from frozen ingestion inputs")
    return manifest


def load_manifest(directory: Path) -> Manifest:
    path = directory / "manifest.json"
    if not path.exists():
        raise ValueError("No AMB manifest; legacy runs are read-only")
    manifest = core.read_model(path, Manifest)
    if core.canonical_sha(manifest.model_copy(update={"fingerprint": ""})) != manifest.fingerprint:
        raise ValueError("Manifest/config changed; use a new run_id")
    if manifest.harness_version != VERSION:
        raise ValueError("Unsupported integration version")
    for path in (Path(__file__), directory / "runner.py"):
        if core.file_sha(path) != manifest.harness_sha256:
            raise ValueError("AMB harness changed; use the frozen entry or a new run")
    for path in (CORE_SOURCE, directory / "support.py"):
        if core.file_sha(path) != manifest.core_sha256:
            raise ValueError("Packing/transport helper changed")
    actual_files = {
        str(p.relative_to(directory / "amb-source"))
        for p in (directory / "amb-source").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }
    if actual_files != set(manifest.amb_files):
        raise ValueError("Frozen AMB file set changed")
    for name, digest in manifest.amb_files.items():
        if core.file_sha(directory / "amb-source" / name) != digest:
            raise ValueError(f"Frozen AMB source changed: {name}")
    for name, filename in core.SOURCE_FILES.items():
        if core.file_sha(directory / "inputs" / filename) != getattr(manifest.config.sources, name).sha256:
            raise ValueError(f"Frozen input changed: {name}")
    if manifest.config.source_ref is not None:
        if core.file_sha(directory / "inputs/checkpoint-source-manifest.json") != manifest.config.source_ref.sha256:
            raise ValueError("Checkpoint source manifest copy changed")
        for name, digest in manifest.checkpoint_imports.items():
            if core.file_sha(directory / "checkpoint-source" / name) != digest:
                raise ValueError("Checkpoint source snapshot changed")
    if manifest.retrieval_origin is not None:
        expected = {amb_id(q) + ".json" for c in manifest.conversations for q in c.questions}
        if {p.name for p in (directory / "retrievals").glob("*.json")} != expected:
            raise ValueError("Reused retrieval checkpoint missing or unexpected; live recall fallback is forbidden")
    runtime = core.environment() | {
        name: core.importlib.metadata.version(name) for name in ("rich", "google-genai", "openai")
    }
    if runtime != manifest.environment or core.client_sources() != manifest.client_source_sha256:
        raise ValueError("Runtime/provider source changed")
    return manifest


def seal(path: Path, record: Sealed) -> None:
    record.checksum = core.canonical_sha(record.model_copy(update={"checksum": ""}))
    path.parent.mkdir(exist_ok=True)
    core.save_model(path, record)


def unseal(path: Path, record_type: type[Any], manifest: Manifest) -> Any:
    record = core.read_model(path, record_type)
    if record.fingerprint != manifest.fingerprint or record.checksum != core.canonical_sha(
        record.model_copy(update={"checksum": ""})
    ):
        raise ValueError(f"Checkpoint content or protocol changed: {path.name}")
    return record


def validate_complete_retrieval_source(directory: Path, manifest: Manifest) -> None:
    """Audit a completed source without executing it, writing it or calling models."""
    if not (directory / "summary.json").exists() or not (directory / "state.json").exists():
        raise ValueError("Retrieval reuse requires a complete, valid source")
    summary = core.read_model(directory / "summary.json", Summary)
    state = core.read_model(directory / "state.json", core.State)
    questions = {amb_id(q): q for c in manifest.conversations for q in c.questions}
    banks = {c.id: c.bank_id for c in manifest.conversations}
    documents = {c.id: {session.document_id for session in c.sessions} for c in manifest.conversations}
    count = len(questions)
    if (
        not summary.valid_complete_run
        or summary.fingerprint != manifest.fingerprint
        or summary.expected != count
        or summary.completed != count
        or summary.failed
        or summary.pending
        or state.fingerprint != manifest.fingerprint
        or state.status != "completed"
        or not state.runtime_consistent
        or set(state.banks) != set(banks)
        or not all(bank.verified for bank in state.banks.values())
    ):
        raise ValueError("Retrieval reuse requires a complete, valid, runtime-consistent source")
    for folder, expected in {
        "retrievals": {qid + ".json" for qid in questions},
        "results": {qid + ".json" for qid in questions},
        "calls": {f"{qid}-{stage}.json" for qid in questions for stage in ("answer", "judge")},
    }.items():
        if {p.name for p in (directory / folder).glob("*.json")} != expected:
            raise ValueError("Retrieval source has missing or unexpected question checkpoints")
    encoder = tiktoken.get_encoding(manifest.config.packing.tokenizer)
    scoring = core.FrozenScoring(directory)
    correct = 0
    f1_total = 0.0
    for qid, question in questions.items():
        retrieved = unseal(directory / f"retrievals/{qid}.json", RetrievalRecord, manifest)
        answer = unseal(directory / f"calls/{qid}-answer.json", CallRecord, manifest)
        judge = unseal(directory / f"calls/{qid}-judge.json", CallRecord, manifest)
        result = unseal(directory / f"results/{qid}.json", SavedResult, manifest)
        if (
            any(record.question_id != qid for record in (retrieved, answer, judge, result))
            or retrieved.bank_id != banks[question.conversation_id]
            or retrieved.error
            or retrieved.recall is None
            or retrieved.packing is None
            or retrieved.retrieval_elapsed_ms is None
            or answer.stage != "answer"
            or judge.stage != "judge"
            or answer.status != "completed"
            or judge.status != "completed"
        ):
            raise ValueError("Retrieval source contains an invalid or incomplete question")
        allowed_documents = documents[question.conversation_id]
        for identifier in retrieved.recall.chunks or {}:
            ref = core.parse_chunk_id(identifier)
            if ref is None or ref.bank_id != retrieved.bank_id or ref.document_id not in allowed_documents:
                raise ValueError("Retrieval source contains a raw chunk outside the question's Bank")
        if any(f.document_id is not None and f.document_id not in allowed_documents for f in retrieved.recall.results):
            raise ValueError("Retrieval source contains a fact outside the question's conversation")
        parsed_answer = AnswerData.model_validate(answer.parsed)
        parsed_judge = JudgeData.model_validate(judge.parsed)
        tokens = len(encoder.encode(retrieved.packing.text))
        f1 = scoring.f1(question, parsed_answer.answer)
        if (
            tokens != retrieved.packing.tokens
            or tokens > manifest.config.packing.max_tokens
            or result.amb_result.query_id != qid
            or result.amb_result.answer != parsed_answer.answer
            or result.amb_result.context != retrieved.packing.text
            or result.amb_result.correct != parsed_judge.correct
            or abs(result.answer_f1 - f1) > 1e-12
        ):
            raise ValueError("Retrieval source results disagree with sealed evidence and model calls")
        correct += int(parsed_judge.correct)
        f1_total += f1
    if summary.correct != correct or abs(summary.answer_f1_all_expected - f1_total / count) > 1e-12:
        raise ValueError("Retrieval source summary disagrees with all question checkpoints")


def amb_modules(directory: Path) -> dict[str, ModuleType]:
    # Import leaf modules under a private namespace. AMB's package registries eagerly
    # import Cognee/Mem0/all providers; those are unrelated to the pinned LoCoMo path.
    # No upstream file is patched, and no default model factory is invoked.
    root = directory / "amb-source/src/memory_bench"
    prefix = "_contextbase_amb_" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:16]
    for suffix in ("", ".dataset", ".memory", ".modes", ".llm"):
        name = prefix + suffix
        if name not in sys.modules:
            package = ModuleType(name)
            package.__path__ = [str(root.joinpath(*suffix.lstrip(".").split("."))) if suffix else str(root)]
            sys.modules[name] = package
    import importlib

    return {
        name: importlib.import_module(prefix + "." + name)
        for name in (
            "dataset.locomo",
            "memory.base",
            "modes.rag",
            "judge",
            "runner",
            "models",
            "llm.base",
        )
    }


@dataclass
class Retrieval:
    documents: list[Any]
    raw_response: dict[str, JsonValue]

    def __iter__(self) -> Iterator[Any]:
        # AMB unpacks this interface into two values; keep our own return type named.
        yield self.documents
        yield self.raw_response


@dataclass
class Components:
    dataset: Any
    memory: Any
    mode: Any
    runner: Any


class Archive:
    def __init__(self, directory: Path, manifest: Manifest, factory: ProviderFactory = core.make_provider) -> None:
        self.directory = directory
        self.manifest = manifest
        self.factory = factory
        self.scoring = core.FrozenScoring(directory)
        self.questions = {amb_id(q): q for c in manifest.conversations for q in c.questions}
        self.conversations = {c.id: c for c in manifest.conversations}

    def call_path(self, qid: str, stage: str) -> Path:
        if qid not in self.questions or stage not in ("answer", "judge"):
            raise ValueError("Unknown question or model stage")
        return self.directory / "calls" / f"{qid}-{stage}.json"

    async def generate(
        self, qid: str, stage: Literal["answer", "judge"], prompt: str, schema: Any
    ) -> dict[str, JsonValue]:
        path = self.call_path(qid, stage)
        expected = ResponseSchema.model_validate(asdict(schema))
        record = (
            unseal(path, CallRecord, self.manifest)
            if path.exists()
            else CallRecord(
                fingerprint=self.manifest.fingerprint,
                question_id=qid,
                stage=stage,
                prompt=prompt,
                response_schema=expected,
            )
        )
        if (
            record.question_id != qid
            or record.stage != stage
            or record.prompt != prompt
            or record.response_schema != expected
        ):
            raise ValueError("Saved model request does not match current request")
        if record.status == "completed":
            if record.parsed is None:
                raise ValueError("Completed model record has no parsed response")
            return record.parsed.model_dump(mode="json")
        if record.status == "failed":
            raise RuntimeError("Model stage previously failed; preserve it and use a new run")
        settings = self.manifest.config.answer if stage == "answer" else self.manifest.config.judge
        response_type = AnswerData if stage == "answer" else JudgeData
        if set(expected.required) != set(response_type.model_fields):
            raise ValueError("Unexpected upstream response schema")
        for attempt in record.attempts:
            if attempt.state == "started":
                attempt.state = "interrupted_unknown"
        while len(record.attempts) < self.manifest.config.model_max_attempts:
            attempt = core.Attempt(stage=stage, state="started", at=core.now())
            record.attempts.append(attempt)
            record.status = "started"
            seal(path, record)
            started = time.monotonic()
            provider = None
            try:
                provider = self.factory(settings, self.manifest.config.request_timeout_s)
                reply = await asyncio.wait_for(
                    provider.call(
                        messages=[core.Message(role="user", content=prompt).model_dump()],
                        response_format=response_type,
                        strict_schema=True,
                        max_retries=0,
                        temperature=settings.temperature,
                        max_completion_tokens=settings.output_tokens_limit,
                    ),
                    timeout=self.manifest.config.request_timeout_s,
                )
                attempt.usage = reply.usage
                content = (
                    reply.content.model_dump(mode="json") if isinstance(reply.content, BaseModel) else reply.content
                )
                record.response = content
                # This branch's Codex provider returns an already parsed object for
                # strict structured output; other providers return JSON text.
                parsed = (
                    response_type.model_validate_json(content)
                    if isinstance(content, str)
                    else response_type.model_validate(content)
                )
                record.parsed = parsed
                record.status = "completed"
                attempt.state = "completed"
                return parsed.model_dump(mode="json")
            except asyncio.CancelledError:
                attempt.state = "interrupted_unknown"
                record.status = "interrupted"
                raise
            except Exception as error:
                attempt.state = "failed"
                # Do not copy potentially credential-bearing transport exception text.
                attempt.error = type(error).__name__
                if not core.retryable(error) or len(record.attempts) >= self.manifest.config.model_max_attempts:
                    record.status = "failed"
                    raise RuntimeError("Model stage failed; see archived attempt") from None
                await asyncio.sleep(2)
            finally:
                attempt.elapsed_s = time.monotonic() - started
                seal(path, record)
                if provider is not None:
                    await provider.cleanup()
        record.status = "failed"
        seal(path, record)
        raise RuntimeError("Model attempt budget exhausted")


def amb_id(question: Any) -> str:
    return f"{question.conversation_id}_q{question.original_index}"


def components(archive: Archive) -> Components:
    directory, manifest = archive.directory, archive.manifest
    modules = amb_modules(directory)
    upstream_dataset = modules["dataset.locomo"].LoComoDataset
    upstream_mode = modules["modes.rag"].RAGMode
    upstream_judge = modules["judge"].GeminiJudge
    upstream_runner = modules["runner"].EvalRunner
    models = modules["models"]

    class Dataset(upstream_dataset):
        def __init__(self) -> None:
            # Never invoke AMB's auto-download/cache path.
            self._local_path = directory / "inputs/locomo10.json"

        def load_queries(self, split: str, category: str | None = None, limit: int | None = None) -> list[Any]:
            queries = [q for q in super().load_queries(split, category=category) if q.id in archive.questions]
            if {q.id for q in queries} != set(archive.questions):
                raise ValueError("AMB question scope differs from frozen scope")
            for query in queries:
                query.meta["_contextbase_question_id"] = query.id
            return queries[:limit] if limit else queries

        def load_documents(
            self,
            split: str,
            category: str | None = None,
            limit: int | None = None,
            ids: set[str] | None = None,
            user_ids: set[str] | None = None,
        ) -> list[Any]:
            docs = super().load_documents(split, category=category, ids=ids, user_ids=set(archive.conversations))
            return docs[:limit] if limit else docs

        def build_rag_prompt(
            self,
            query: str,
            context: str,
            task_type: str,
            split: str,
            category: str | None = None,
            meta: dict[str, Any] | None = None,
        ) -> str:
            # Default preserves the exact upstream template. A declared reader-v2
            # experiment adds only global guidance, leaving the judge untouched.
            if meta is None:
                raise ValueError("Packed recall metadata is required")
            packed = core.Packed.model_validate(meta["_raw_response"]["packing"])
            clean = {key: value for key, value in meta.items() if key != "_raw_response"}
            upstream = super().build_rag_prompt(query, packed.text, task_type, split, category, clean)
            return core.reader_prompt(upstream, manifest.config.reader_profile)

    class Memory(modules["memory.base"].MemoryProvider):
        name = "contextbase-http"
        description = "Local ContextBase, explicit isolated ingestion and audited complete context packing"
        kind = "local"
        concurrency = manifest.config.concurrency

        def prepare(self, store_dir: Path, unit_ids: set[str] | None = None, reset: bool = True) -> None:
            if reset or unit_ids != set(archive.conversations):
                raise ValueError("Use explicit ingestion; AMB cannot reset these Banks")

        def ingest(self, documents: list[Any]) -> None:
            raise RuntimeError("Use the explicit ingest command before AMB run")

        def retrieve(
            self,
            query: str,
            k: int = 10,
            user_id: str | None = None,
            query_timestamp: str | None = None,
            filters: Any = None,
        ) -> Retrieval:
            raise RuntimeError("This provider requires AMB async_retrieve")

        async def async_retrieve(
            self,
            query: str,
            k: int = 10,
            user_id: str | None = None,
            query_timestamp: str | None = None,
            filters: Any = None,
        ) -> Retrieval:
            qid = QUESTION_ID.get()
            question = archive.questions.get(qid)
            if (
                question is None
                or question.question != query
                or question.conversation_id != user_id
                or filters is not None
            ):
                raise ValueError("Retrieval identity differs from the frozen scope")
            conversation = archive.conversations[user_id]
            if query_timestamp != conversation.reference_date:
                raise ValueError("AMB query date differs from the frozen conversation date")
            path = directory / "retrievals" / f"{qid}.json"
            if path.exists():
                record = unseal(path, RetrievalRecord, manifest)
                if record.question_id != qid or record.bank_id != conversation.bank_id:
                    raise ValueError("Saved retrieval belongs to another question/Bank")
            else:
                if manifest.retrieval_origin is not None:
                    raise ValueError("Reused retrieval checkpoint missing; live recall fallback is forbidden")
                record = RetrievalRecord(
                    fingerprint=manifest.fingerprint,
                    question_id=qid,
                    bank_id=conversation.bank_id,
                )
                # A failed/interrupted recall is evidence too. Do not let AMB's outer
                # query retry silently replace it with a fresh retrieval and timing.
                seal(path, record)
                secret = manifest.config.credential.resolve()
                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=manifest.config.request_timeout_s), trust_env=False
                ) as session:
                    http = core.BankHTTP(session, manifest.config, secret)
                    body = core.RecallBody(
                        query=query,
                        budget=manifest.config.recall.budget,
                        max_tokens=manifest.config.recall.max_tokens,
                        query_timestamp=query_timestamp,
                        include=core.RecallInclude(
                            chunks=core.ChunkBudget(max_tokens=manifest.config.recall.max_chunk_tokens)
                        ),
                    )
                    started = time.monotonic()
                    try:
                        record.recall = await http.request(
                            "POST",
                            "/v1/default/banks/" + conversation.bank_id + "/memories/recall",
                            core.RecallReply,
                            body,
                        )
                        record.retrieval_elapsed_ms = (time.monotonic() - started) * 1000
                    except asyncio.CancelledError:
                        record.error = "interrupted_unknown"
                        raise
                    except Exception as error:
                        record.error = type(error).__name__
                        raise RuntimeError("Recall failed; see archived retrieval") from None
                    finally:
                        seal(path, record)
                try:
                    record.packing = core.pack_context(
                        record.recall, conversation, manifest.config.packing, query=query
                    )
                except Exception as error:
                    record.error = type(error).__name__
                    raise
                finally:
                    seal(path, record)
            if record.packing is None:
                raise ValueError("Saved recall could not be packed; preserve it and use a new run")
            return Retrieval([models.Document(id=qid, content=record.packing.text)], record.model_dump(mode="json"))

    class Bridge(modules["llm.base"].LLM):
        def __init__(self, stage: Literal["answer", "judge"]) -> None:
            self.stage = stage

        @property
        def model_id(self) -> str:
            settings = manifest.config.answer if self.stage == "answer" else manifest.config.judge
            return f"{settings.provider}:{settings.model}"

        def generate(self, prompt: str, schema: Any) -> dict[str, JsonValue]:
            qid = QUESTION_ID.get()
            if qid is None:
                raise ValueError("Model call is not bound to a frozen question")
            # AMB invokes this synchronous interface in its own worker thread. HTTP
            # remains async; each call owns/cleans its provider on this fresh loop.
            return asyncio.run(archive.generate(qid, self.stage, prompt, schema))

    class Mode(upstream_mode):
        def __init__(self) -> None:
            self._llm = Bridge("answer")

        async def async_answer(
            self,
            query: str,
            memory: Any,
            task_type: str = "open",
            user_id: str | None = None,
            meta: dict[str, Any] | None = None,
        ) -> Any:
            if meta is None:
                raise ValueError("Frozen question metadata is required")
            qid = meta["_contextbase_question_id"]
            # ContextVar is task-local and is copied by AMB's to_thread into its judge.
            QUESTION_ID.set(qid)
            try:
                result = await super().async_answer(query, memory, task_type=task_type, user_id=user_id, meta=meta)
            except Exception:
                # AMB otherwise aborts the entire conversation on one exhausted
                # transport failure. Preserve that terminal failure and evaluate
                # the remaining questions; never regenerate a failed answer.
                call = archive.call_path(qid, "answer")
                retrieval = directory / "retrievals" / f"{qid}.json"
                failed_call = call.exists() and unseal(call, CallRecord, manifest).status == "failed"
                failed_retrieval = retrieval.exists() and unseal(retrieval, RetrievalRecord, manifest).error is not None
                if not (failed_call or failed_retrieval):
                    raise
                return models.AnswerResult(
                    answer="", reasoning="Recorded operational failure", context="", retrieve_time_ms=0
                )
            saved = unseal(directory / "retrievals" / f"{qid}.json", RetrievalRecord, manifest)
            # Upstream stores a generic '## Memory' wrapper here, although the LoCoMo
            # prompt hook injected the packed string. Archive/count the actual input.
            result.context = saved.packing.text
            result.retrieve_time_ms = saved.retrieval_elapsed_ms
            return result

    class Judge(upstream_judge):
        def __init__(self) -> None:
            self._llm = Bridge("judge")

        def score(self, query: str, answer: str, gold_answers: list[str], prompt_fn: Any = None) -> Any:
            try:
                return super().score(query, answer, gold_answers, prompt_fn)
            except Exception:
                qid = QUESTION_ID.get()
                path = archive.call_path(qid, "judge") if qid else None
                if path is None or not path.exists() or unseal(path, CallRecord, manifest).status != "failed":
                    raise
                return models.JudgeResult(
                    correct=False, reason="Recorded judge transport/format failure; not a semantic verdict"
                )

    class Runner(upstream_runner):
        def __init__(self) -> None:
            # Upstream __init__ constructs an environment-default judge. Inject the
            # configured bridge directly so no implicit credentials/model can win.
            self.output_dir = directory / "amb-output"
            self._judge = Judge()
            self._dataset_metrics = {}

        def _load_previous_ingestion_ms(self, dataset: str, split: str, memory: str, mode: str) -> float:
            state = core.read_model(directory / "state.json", core.State)
            return sum((bank.ingestion_elapsed_s or 0) * 1000 for bank in state.banks.values())

        def _load_previous_ingested_docs(self, dataset: str, split: str, memory: str, mode: str) -> int:
            return sum(len(c.sessions) for c in manifest.conversations)

        def _save(self, summary: Any, query_ids: set[str] | None = None) -> None:
            super()._save(summary, query_ids=query_ids)
            for result in summary.results:
                path = directory / "results" / f"{result.query_id}.json"
                record = SavedResult(
                    fingerprint=manifest.fingerprint,
                    question_id=result.query_id,
                    amb_result=NativeResult.model_validate(asdict(result)),
                    answer_f1=archive.scoring.f1(archive.questions[result.query_id], result.answer),
                )
                if path.exists() and unseal(path, SavedResult, manifest).amb_result != record.amb_result:
                    raise ValueError("Refusing to replace an existing result")
                seal(path, record)

    return Components(Dataset(), Memory(), Mode(), Runner())


async def service_stage(directory: Path, manifest: Manifest, stage: str) -> None:
    if stage == "ingest" and manifest.config.reuse_banks:
        raise ValueError("Cannot ingest into reused Banks; use read-only verify")
    if stage == "verify" and not manifest.config.reuse_banks:
        raise ValueError("verify requires explicit reuse_banks mapping")
    secret = manifest.config.credential.resolve()
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=manifest.config.request_timeout_s), trust_env=False
    ) as session:

        class RedactedHTTP(core.BankHTTP):
            async def request(self, *args: Any, **kwargs: Any) -> Any:
                result = await super().request(*args, **kwargs)
                if isinstance(result, core.RuntimeSnapshot):
                    return core.RuntimeSnapshot.model_validate(core.redact_snapshot(result.model_dump(mode="json")))
                return result

        transport = core.Ingestion(directory, manifest, RedactedHTTP(session, manifest.config, secret))
        if stage == "ingest":
            await transport.ingest()
        elif stage == "verify":
            for conversation in manifest.conversations:
                await transport.check_runtime(conversation, "before")
                await transport.verify_documents(conversation)
                await verify_reused_operations(transport, conversation, "verify")
                previous = transport.state.banks.get(conversation.id, core.BankState())
                transport.state.banks[conversation.id] = previous.model_copy(
                    update={"created": False, "verified": True}
                )
            transport.state.status = "verified_reuse"
            transport.save_state()
        else:
            if not all(transport.state.banks.get(c.id, core.BankState()).verified for c in manifest.conversations):
                raise ValueError("Every Bank must be ingested and verified before answering")
            for conversation in manifest.conversations:
                await transport.check_runtime(conversation, stage)
                await transport.verify_documents(conversation)
                if manifest.config.reuse_banks:
                    await verify_reused_operations(transport, conversation, stage)
        version = await transport.http.request("GET", "/version", core.RuntimeSnapshot)
        baseline = directory / "server-version-before.json"
        if baseline.exists() and core.canonical_sha(
            core.read_model(baseline, core.RuntimeSnapshot)
        ) != core.canonical_sha(version):
            transport.state.runtime_consistent = False
            transport.save_state()
            raise ValueError("Server version changed")
        core.save_model(baseline if not baseline.exists() else directory / f"server-version-{stage}.json", version)


async def verify_reused_operations(transport: Any, conversation: Any, label: str) -> None:
    operations = await transport.all_operations(conversation)
    if not operations or any(op.status != "completed" for op in operations):
        raise ValueError("Reused Bank has missing, pending or failed ingestion operations")
    if any(op.result_metadata and op.result_metadata.extraction_errors_count for op in operations):
        raise ValueError("Reused Bank reports extraction errors")
    core.save_model(
        transport.directory / f"{conversation.id}-reuse-operations-{label}.json",
        core.OperationsPage(operations=operations, total=len(operations)),
    )


def report(directory: Path, manifest: Manifest) -> Summary:
    archive = Archive(directory, manifest)
    state = core.read_model(directory / "state.json", core.State)
    if state.fingerprint != manifest.fingerprint:
        raise ValueError("State belongs to another run")
    results: dict[str, SavedResult] = {}
    retrieved: list[RetrievalRecord] = []
    calls: list[CallRecord] = []
    for folder, cls in (("results", SavedResult), ("retrievals", RetrievalRecord), ("calls", CallRecord)):
        for path in (directory / folder).glob("*.json"):
            record = unseal(path, cls, manifest)
            if record.question_id not in archive.questions:
                raise ValueError("Record outside the frozen scope")
            if folder == "results":
                if path.stem != record.question_id:
                    raise ValueError("Result filename differs from identity")
                results[record.question_id] = record
            elif folder == "retrievals":
                if (
                    path.stem != record.question_id
                    or record.bank_id
                    != archive.conversations[archive.questions[record.question_id].conversation_id].bank_id
                ):
                    raise ValueError("Retrieval filename/Bank differs from identity")
                retrieved.append(record)
            else:
                if path.name != archive.call_path(record.question_id, record.stage).name:
                    raise ValueError("Model record filename differs from identity")
                calls.append(record)
    f1_total = 0.0
    for record in calls:
        if record.stage == "answer" and record.status == "completed":
            answer = AnswerData.model_validate(record.parsed)
            f1_total += archive.scoring.f1(archive.questions[record.question_id], answer.answer)
    usage = {"answer": TokenUsage(), "judge": TokenUsage()}
    for record in calls:
        for attempt in record.attempts:
            if attempt.usage is not None:
                usage[record.stage] += attempt.usage
    encoder = tiktoken.get_encoding(manifest.config.packing.tokenizer)
    amb_encoder = tiktoken.get_encoding("cl100k_base")
    contexts = [len(encoder.encode(record.packing.text)) for record in retrieved if record.packing is not None]
    amb_tokens = [len(amb_encoder.encode(record.packing.text)) for record in retrieved if record.packing is not None]
    prompts = [len(encoder.encode(record.prompt)) for record in calls if record.stage == "answer"]
    latencies = [record.retrieval_elapsed_ms for record in retrieved if record.retrieval_elapsed_ms is not None]
    failed = {record.question_id for record in calls if record.status == "failed"} | {
        record.question_id for record in retrieved if record.error is not None
    }
    correct = sum(record.amb_result.correct is True for record in results.values())
    count = len(archive.questions)
    summary = Summary(
        fingerprint=manifest.fingerprint,
        protocol=manifest.config.protocol,
        amb_commit=AMB_COMMIT,
        valid_complete_run=len(results) == count
        and len(retrieved) == count
        and all(
            r.recall is not None and r.packing is not None and r.retrieval_elapsed_ms is not None for r in retrieved
        )
        and len(calls) == count * 2
        and all(call.status == "completed" for call in calls)
        and not failed
        and state.status == "completed"
        and state.runtime_consistent
        and set(state.banks) == set(archive.conversations)
        and all(bank.verified for bank in state.banks.values()),
        expected=count,
        completed=len(set(results) - failed),
        failed=len(failed),
        pending=count - len(set(results) | failed),
        correct=correct,
        accuracy_all_expected=correct / count,
        answer_f1_all_expected=f1_total / count,
        context_tokenizer=manifest.config.packing.tokenizer,
        context_tokens_total=sum(contexts),
        context_tokens_mean=statistics.mean(contexts) if contexts else None,
        context_tokens_max=max(contexts) if contexts else None,
        amb_cl100k_context_tokens_mean=statistics.mean(amb_tokens) if amb_tokens else None,
        full_answer_prompt_tokens_mean=statistics.mean(prompts) if prompts else None,
        retrieval_sample_count=len(latencies),
        retrieval_measurement="reused-source-recall" if manifest.retrieval_origin else "live-http-recall",
        retrieval_source_run_id=manifest.retrieval_origin.run_id if manifest.retrieval_origin else None,
        retrieval_ms_mean=statistics.mean(latencies) if latencies else None,
        retrieval_ms_p50=float(np.percentile(latencies, 50)) if latencies else None,
        retrieval_ms_p95=float(np.percentile(latencies, 95)) if latencies else None,
        model_usage=usage,
        attempts_with_unknown_usage=sum(a.usage is None for r in calls for a in r.attempts),
        retained_banks=[c.bank_id for c in manifest.conversations],
    )
    core.save_model(directory / "summary.json", summary)
    return summary


def run(directory: Path, manifest: Manifest, factory: ProviderFactory = core.make_provider) -> Summary:
    asyncio.run(service_stage(directory, manifest, "before"))
    archive = Archive(directory, manifest, factory)
    runtime = components(archive)
    state = core.read_model(directory / "state.json", core.State)
    state.status = "answering"
    core.save_model(directory / "state.json", state)
    started = time.monotonic()
    try:
        runtime.runner.run(
            dataset=runtime.dataset,
            split="locomo10",
            memory=runtime.memory,
            mode=runtime.mode,
            skip_ingestion=True,
            run_name=manifest.run_id,
            description=f"{VERSION}; AMB {AMB_COMMIT}; declared complete-context packing; no oracle",
        )
        asyncio.run(service_stage(directory, manifest, "after"))
        state.status = "completed"
    except BaseException:
        state.status = "interrupted_or_failed"
        raise
    finally:
        latest = core.read_model(directory / "state.json", core.State)
        state.runtime_consistent = latest.runtime_consistent
        state.answer_elapsed_s += time.monotonic() - started
        core.save_model(directory / "state.json", state)
        report(directory, manifest)
    return report(directory, manifest)


def preview(directory: Path, source: Path, conversation_id: str, output: Path, query: str | None = None) -> Any:
    manifest = load_manifest(directory)
    if output.exists():
        raise ValueError("Preview output exists; preserve previous evidence")
    conversation = next(c for c in manifest.conversations if c.id == conversation_id)
    raw = json.loads(source.read_text())
    recalled = core.RecallReply.model_validate(raw["recall"] if "recall" in raw else raw)
    if recalled.chunks:
        ref = core.parse_chunk_id(next(iter(recalled.chunks)))
        if ref is None:
            raise ValueError("Invalid saved chunk identity")
        # Read-only preview may inspect an older run, but never adopts its Bank.
        conversation = conversation.model_copy(update={"bank_id": ref.bank_id})
    result = core.Preview(
        fingerprint=manifest.fingerprint,
        packing=core.pack_context(recalled, conversation, manifest.config.packing, query=query),
    )
    core.save_model(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Offline: freeze a pinned source checkout, inputs and configuration")
    init.add_argument("--config", type=Path, required=True)
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--run-id", required=True)
    for command in ("ingest", "verify", "run", "report"):
        sub = commands.add_parser(command)
        sub.add_argument("run_dir", type=Path)
    pack = commands.add_parser("preview", help="Offline: inspect packing of a saved recall, no new answers")
    pack.add_argument("run_dir", type=Path)
    pack.add_argument("--recall", type=Path, required=True)
    pack.add_argument("--conversation", required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--query")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if args.command == "init":
        result = init_run(args.config, args.run_dir, args.run_id)
        print(json.dumps({"fingerprint": result.fingerprint, "stage": "prepared_offline", "amb_commit": AMB_COMMIT}))
        return
    load_manifest(args.run_dir)  # Reject old results before creating even a lock file.
    with core.run_lock(args.run_dir):
        manifest = load_manifest(args.run_dir)
        if args.command == "ingest":
            asyncio.run(service_stage(args.run_dir, manifest, "ingest"))
        elif args.command == "verify":
            asyncio.run(service_stage(args.run_dir, manifest, "verify"))
        elif args.command == "run":
            print(run(args.run_dir, manifest).model_dump_json(indent=2))
        elif args.command == "preview":
            print(
                preview(args.run_dir, args.recall, args.conversation, args.output, args.query).model_dump_json(indent=2)
            )
        else:
            print(report(args.run_dir, manifest).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
