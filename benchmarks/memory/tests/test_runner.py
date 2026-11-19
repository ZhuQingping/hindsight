"""Real pinned AMB code, synthetic LoCoMo histories, local HTTP and scripted models only."""

import asyncio
import importlib.util
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import Mock
from urllib.parse import urlsplit

import aiohttp
import numpy as np
import pytest
import tiktoken
from aiohttp import web
from aiohttp.test_utils import TestServer
from hindsight_api.engine.chunk_ids import build_chunk_id
from hindsight_api.engine.response_models import LLMCallResult, TokenUsage

SCRIPT = Path(__file__).parents[1] / "runner.py"
spec = importlib.util.spec_from_file_location("amb_contextbase_test", SCRIPT)
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a
spec.loader.exec_module(a)


h = a.core


def config_fixture(tmp_path, *, conversations=("conv-30",), attempts=2):
    sources = tmp_path / "sources"
    sources.mkdir()
    records = []
    for name in conversations:
        records.append(
            {
                "sample_id": name,
                "conversation": {
                    "speaker_a": "Person A",
                    "speaker_b": "Person B",
                    "session_1_date_time": "1:00 pm on 1 January, 2023",
                    "session_1": [{"speaker": "Person A", "dia_id": "D1:1", "text": "Public session memory."}],
                    "session_10_date_time": "1:00 pm on 10 January, 2023",
                    "session_10": [{"speaker": "Person B", "dia_id": "D10:1", "text": "Another public memory."}],
                },
                "qa": [
                    {
                        "question": "A public question?",
                        "answer": "GOLD_SENTINEL_NOT_IN_MEMORY",
                        "category": 2,
                        "evidence": ["EVIDENCE_SENTINEL_NOT_IN_MEMORY"],
                    },
                    {"question": "Excluded adversarial?", "category": 5},
                ],
            }
        )
    (sources / "locomo10.json").write_text(json.dumps(records))
    # Original LoCoMo F1 functions, formatting normalized; no real QA data.
    (sources / "locomo_evaluation.py").write_text(r"""
def normalize_answer(s):
    s = s.replace(',', '')

    def remove_articles(text):
        return regex.sub('\\b(a|an|the|and)\\b', ' ', text)

    def white_space_fix(text):
        return ' '.join(text.split())

    def remove_punc(text):
        exclude = set(string.punctuation)
        return ''.join((ch for ch in text if ch not in exclude))

    def lower(text):
        return text.lower()
    return white_space_fix(remove_articles(remove_punc(lower(s))))

def f1_score(prediction, ground_truth):
    prediction_tokens = [ps.stem(w) for w in normalize_answer(prediction).split()]
    ground_truth_tokens = [ps.stem(w) for w in normalize_answer(ground_truth).split()]
    common = Counter(prediction_tokens) & Counter(ground_truth_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0
    precision = 1.0 * num_same / len(prediction_tokens)
    recall = 1.0 * num_same / len(ground_truth_tokens)
    f1 = 2 * precision * recall / (precision + recall)
    return f1

def f1(prediction, ground_truth):
    predictions = [p.strip() for p in prediction.split(',')]
    ground_truths = [g.strip() for g in ground_truth.split(',')]
    return np.mean([max([f1_score(prediction, gt) for prediction in predictions]) for gt in ground_truths])
""")
    template = json.loads((SCRIPT.parent / "config.example.json").read_text())
    template["sources"] = {
        name: {"path": str(sources / filename), "sha256": h.file_sha(sources / filename)}
        for name, filename in h.SOURCE_FILES.items()
    }
    template["conversations"] = list(conversations)
    template["poll_interval_s"] = 0.01
    template["model_max_attempts"] = attempts
    path = tmp_path / "config.json"
    path.write_text(json.dumps(template))
    return path


def recall_fixture(conversation, count=109, *, giant=False):
    doc = conversation.sessions[0].document_id
    identifier = build_chunk_id(conversation.bank_id, doc, 0)
    facts = [
        h.Fact(
            id=f"fact{i}",
            text=("x " * 10000 if giant and i == 0 else f"Fact {i}: this is an entire statement with a date."),
            document_id=doc,
            chunk_id=identifier,
            mentioned_at="2023-01-01T13:00:00Z",
        )
        for i in range(count)
    ]
    return h.RecallReply(
        results=facts,
        chunks={
            identifier: h.Chunk(text='Original passage with "quotes", 中文 and an exact detail omitted by the facts.')
        },
    )


def test_server_profile_requires_matching_candidate_and_packing_settings(tmp_path):
    data = json.loads(config_fixture(tmp_path).read_text())
    data["recall_profile"] = "locomo"
    data["packing"].update(algorithm="query-turn-windows-v1", chunk_order="query_relevance")
    data["recall"]["max_chunk_tokens"] = 65536
    assert a.Config.model_validate(data).recall_profile == "locomo"
    data["recall"]["max_chunk_tokens"] = 8192
    with pytest.raises(ValueError, match="65536 candidate"):
        a.Config.model_validate(data)


def test_server_context_is_used_verbatim_and_missing_or_corrupt_context_fails():
    with pytest.raises(ValueError, match="not returned"):
        h.server_packed_context(h.RecallReply(results=[]))
    text = '{"facts":[], "chunks":[]}'
    packed = dict(
        text=text,
        tokens=len(tiktoken.get_encoding("o200k_base").encode(text)),
        fact_tokens=0,
        chunk_tokens=0,
        included_fact_ids=[],
        included_chunk_ids=[],
        omitted=[],
    )
    context = dict(
        **packed, profile="locomo", version="message_windows_v1", format="locomo-packed-json-v1", tokenizer="o200k_base"
    )
    reply = h.RecallReply(results=[], recall_context=context)
    assert h.server_packed_context(reply).text == text
    reply.recall_context.tokens += 1
    with pytest.raises(ValueError, match="token contract"):
        h.server_packed_context(reply)
    reply.recall_context.tokens -= 1
    reply.recall_context.fact_tokens = 4001
    with pytest.raises(ValueError, match="token contract"):
        h.server_packed_context(reply)


class FakeBankService:
    def __init__(self):
        self.documents = {}
        self.polls = {}
        self.requests = []
        self.ingestion_bodies = []
        self.reads_before_completed = 0
        self.config_marker = 0

    async def handle(self, request):
        self.requests.append((request.method, request.path))
        if request.path == "/version":
            return web.json_response({"api_version": "fixture"})
        prefix = "/v1/default/banks/"
        tail = request.path.removeprefix(prefix)
        bank, _, suffix = tail.partition("/")
        assert bank.startswith("unit_test_conv_")
        if request.method == "PUT":
            assert request.headers["If-None-Match"] == "*"
            assert bank not in self.documents
            self.documents[bank] = {}
            self.polls[bank] = 0
            return web.json_response({"bank_id": bank})
        if suffix == "config":
            return web.json_response(
                {"bank_id": bank, "config": {"enable_observations": False, "llm_api_key": "NEVER_COPY_THIS_SECRET"}}
            )
        if suffix == "memories" and request.method == "POST":
            body = await request.json()
            self.ingestion_bodies.append(body)
            self.documents[bank] = {x["document_id"]: x["content"] for x in body["items"]}
            return web.json_response({"operation_id": body["operation_id"]})
        if suffix == "operations":
            self.polls[bank] += 1
            operation_id = next(
                x["operation_id"]
                for x in self.ingestion_bodies
                if x["items"][0]["document_id"].startswith(bank.split("unit_test_")[1].replace("conv_", "conv-") + "_")
            )
            return web.json_response(
                {
                    "total": 2,
                    "operations": [
                        {"operation_id": operation_id, "status": "completed"},
                        {"operation_id": "child", "status": "processing"},
                    ],
                }
            )
        if suffix.startswith("operations/"):
            child = suffix.endswith("child")
            status = "processing" if child and self.polls[bank] == 1 else "completed"
            return web.json_response(
                {
                    "operation_id": suffix.split("/")[1],
                    "status": status,
                    "result_metadata": {"extraction_errors_count": 0},
                }
            )
        if suffix == "documents":
            assert self.polls[bank] >= 2
            return web.json_response(
                {
                    "total": len(self.documents[bank]),
                    "items": [{"id": k, "bank_id": bank} for k in self.documents[bank]],
                }
            )
        if suffix.startswith("documents/"):
            doc = suffix.removeprefix("documents/")
            return web.json_response({"id": doc, "bank_id": bank, "original_text": self.documents[bank][doc]})
        if suffix == "memories/recall":
            assert self.polls[bank] >= 2
            body = await request.json()
            assert body["include"]["entities"] is None
            doc = next(iter(self.documents[bank]))
            chunk = build_chunk_id(bank, doc, 0)
            return web.json_response(
                {
                    "results": [
                        {"id": bank + "_fact", "text": "Public memory.", "document_id": doc, "chunk_id": chunk}
                    ],
                    "chunks": {chunk: {"text": "Public original passage."}},
                }
            )
        raise AssertionError(f"Unexpected request (including reflect/delete): {request.method} {suffix}")


@pytest.fixture(scope="session")
def checkout():
    fallback = SCRIPT.parents[3] / "ContextDB-Research/.local-archive/benchmarks/tools/amb-28b644b"
    path = Path(os.environ.get("CONTEXTBASE_AMB_CHECKOUT", str(fallback)))
    if not path.exists():
        pytest.skip("Set CONTEXTBASE_AMB_CHECKOUT to the fixed offline source checkout")
    assert a.git(path, "rev-parse", "HEAD") == a.AMB_COMMIT
    return path


@pytest.fixture(autouse=True)
def prevent_real_services(monkeypatch):
    original = aiohttp.ClientSession._request

    async def guarded(self, method, url, **kwargs):
        parsed = urlsplit(str(url))
        assert parsed.hostname == "127.0.0.1" and parsed.port not in (8888, 8891, 8892), (
            "Offline tests cannot access real services"
        )
        return await original(self, method, url, **kwargs)

    monkeypatch.setattr(aiohttp.ClientSession, "_request", guarded)
    monkeypatch.setattr("urllib.request.urlretrieve", Mock(side_effect=AssertionError("No dataset downloads")))


@dataclass
class Prepared:
    directory: Path
    manifest: Any

    def __iter__(self) -> Iterator[Any]:
        yield self.directory
        yield self.manifest


def prepared(
    tmp_path,
    checkout,
    *,
    conversations=("conv-30",),
    api_url=None,
    questions_per_conversation=1,
    reuse_banks=None,
    gold_answer=None,
    evidence_ids=None,
    packing=None,
    reader_profile="amb-default",
):
    path = config_fixture(tmp_path, conversations=conversations)
    config = json.loads(path.read_text())
    config.update(
        protocol="amb-locomo-cat1to4-packed-v1", judge_protocol="pinned-amb-locomo-judge", amb_checkout=str(checkout)
    )
    if api_url:
        config["api_url"] = api_url
    if reuse_banks:
        config["reuse_banks"] = reuse_banks
    if packing is not None:
        config["packing"] = packing.model_dump(mode="json")
    config["reader_profile"] = reader_profile
    if reader_profile != "amb-default":
        config["protocol"] = "amb-locomo-cat1to4-reader-v2"
    if questions_per_conversation > 1 or gold_answer is not None or evidence_ids is not None:
        dataset_path = Path(config["sources"]["dataset"]["path"])
        records = json.loads(dataset_path.read_text())
        for conversation in records:
            if questions_per_conversation > 1:
                conversation["qa"] = [conversation["qa"][0].copy() for _ in range(questions_per_conversation)] + [
                    conversation["qa"][-1]
                ]
            if gold_answer is not None or evidence_ids is not None:
                for question in conversation["qa"]:
                    if question["category"] != 5:
                        if gold_answer is not None:
                            question["answer"] = gold_answer
                        if evidence_ids is not None:
                            question["evidence"] = evidence_ids
        dataset_path.write_text(json.dumps(records))
        config["sources"]["dataset"]["sha256"] = a.core.file_sha(dataset_path)
    path.write_text(json.dumps(config))
    directory = tmp_path / "amb-run"
    return Prepared(directory, a.init_run(path, directory, "unit_test"))


class ScriptedModel:
    def __init__(self, factory, *, judge):
        self.factory = factory
        self.judge = judge

    async def call(self, *, messages, response_format, strict_schema, **kwargs):
        assert strict_schema and kwargs["max_retries"] == 0
        prompt = messages[0]["content"]
        self.factory.calls.append((self.judge, prompt, a.QUESTION_ID.get()))
        if self.judge and self.factory.interrupt_judge:
            self.factory.interrupt_judge = False
            raise asyncio.CancelledError()
        if self.judge and self.factory.fail_judge:
            raise ValueError("Scripted failure")
        content = (
            {"correct": self.factory.correct, "reason": "Scripted mechanics fixture"}
            if self.judge
            else {"answer": self.factory.answer, "reasoning": "Scripted mechanics fixture"}
        )
        return LLMCallResult(
            content=response_format.model_validate(content)
            if self.factory.structured == "model"
            else content
            if self.factory.structured
            else json.dumps(content),
            usage=TokenUsage(input_tokens=7, output_tokens=3, total_tokens=10),
        )

    async def cleanup(self):
        self.factory.cleanups += 1


class Factory:
    def __init__(
        self,
        manifest,
        *,
        correct=False,
        answer="test answer",
        interrupt_judge=False,
        fail_judge=False,
        structured=False,
    ):
        self.manifest = manifest
        self.correct = correct
        self.answer = answer
        self.interrupt_judge = interrupt_judge
        self.fail_judge = fail_judge
        self.structured = structured
        self.calls = []
        self.cleanups = 0

    def __call__(self, settings, timeout):
        return ScriptedModel(self, judge=settings is self.manifest.config.judge)


def test_init_is_offline_freezes_upstream_and_rejects_existing_directory(tmp_path, checkout, monkeypatch):
    monkeypatch.delenv("CONTEXTBASE_BENCH_KEY", raising=False)
    factory = Mock(side_effect=AssertionError("No model creation"))
    monkeypatch.setattr(a.core, "make_provider", factory)
    directory, manifest = prepared(tmp_path, checkout)
    assert a.load_manifest(directory) == manifest
    assert manifest.config.amb_commit == a.AMB_COMMIT
    assert (directory / "amb-source/uv.lock").is_file()
    assert len(manifest.amb_files) > 30
    assert a.core.read_model(directory / "state.json", a.core.State).banks == {}
    assert not (directory / "calls").exists()
    assert "GOLD_SENTINEL" not in json.dumps([q.model_dump() for c in manifest.conversations for q in c.questions])
    with pytest.raises(FileExistsError):
        a.init_run(tmp_path / "config.json", directory, "unit_test")
    assert not factory.called


@pytest.mark.parametrize("reader_profile", ["amb-default", "locomo-grounded-concise-v1"])
def test_real_amb_loader_and_prompt_use_only_complete_packed_context(tmp_path, checkout, reader_profile):
    directory, manifest = prepared(tmp_path, checkout, reader_profile=reader_profile)
    archive = a.Archive(directory, manifest)
    runtime = a.components(archive)
    queries = runtime.dataset.load_queries("locomo10")
    assert [q.id for q in queries] == ["conv-30_q0"]  # adversarial excluded
    assert queries[0].meta["query_timestamp"] == "2023-01-10T13:00:00+00:00"
    docs = runtime.dataset.load_documents("locomo10")
    assert len(docs) == 2 and all(doc.user_id == "conv-30" for doc in docs)
    assert all("GOLD_SENTINEL" not in doc.content and "EVIDENCE_SENTINEL" not in doc.content for doc in docs)
    packed = a.core.pack_context(
        recall_fixture(manifest.conversations[0]), manifest.conversations[0], manifest.config.packing
    )
    meta = {**queries[0].meta, "_raw_response": {"packing": packed.model_dump(), "DONT_INJECT": "RAW_BYPASS_SENTINEL"}}
    actual = runtime.dataset.build_rag_prompt(
        queries[0].query, "WRAPPER_SHOULD_NOT_ENTER_PROMPT", "open", "locomo10", meta=meta
    )
    upstream = a.amb_modules(directory)["dataset.locomo"].LoComoDataset()
    expected = upstream.build_rag_prompt(queries[0].query, packed.text, "open", "locomo10", meta=queries[0].meta)
    assert actual == h.reader_prompt(expected, reader_profile)
    if reader_profile == "amb-default":
        assert actual == expected
    else:
        assert actual.endswith(expected) and actual.startswith("# ADDITIONAL READER GUIDANCE")
        assert "fictional characters" in actual and "image caption" in actual
        assert "GOLD_SENTINEL" not in actual and "EVIDENCE_SENTINEL" not in actual
        assert "judge prompt unchanged" in manifest.integration_notes[-1]
    assert packed.text in actual and json.loads(packed.text)["chunks"]
    assert "RAW_BYPASS_SENTINEL" not in actual and "WRAPPER_SHOULD_NOT_ENTER_PROMPT" not in actual
    assert packed.tokens <= 8192
    assert runtime.dataset.build_judge_prompt("q", ["gold"], "answer") == upstream.build_judge_prompt(
        "q", ["gold"], "answer"
    )
    assert runtime.runner.__class__.__mro__[1].__module__.endswith(".runner")
    assert runtime.mode.__class__.__mro__[1].__module__.endswith(".modes.rag")
    with pytest.raises(ValueError, match="reset"):
        runtime.memory.prepare(directory, {"conv-30"}, reset=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "packing_algorithm",
    ["complete-json-separate-budgets-v2", "query-turn-windows-v1", "query-turn-windows-metadata-v2"],
)
@pytest.mark.parametrize("reader_profile", ["amb-default", "locomo-grounded-concise-v1"])
async def test_pinned_amb_end_to_end_isolated_banks_and_resume_without_new_calls(
    tmp_path, checkout, monkeypatch, packing_algorithm, reader_profile
):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        directory, manifest = prepared(
            tmp_path,
            checkout,
            conversations=("conv-30", "conv-26"),
            api_url=str(server.make_url("/")),
            reader_profile=reader_profile,
            packing=h.PackingSettings(
                algorithm=packing_algorithm,
                chunk_order="response_order"
                if packing_algorithm == "complete-json-separate-budgets-v2"
                else "query_relevance",
            ),
        )
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        factory = Factory(manifest, structured=True)
        summary = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert summary.valid_complete_run and summary.expected == summary.completed == 2
        assert summary.correct == 0 and summary.accuracy_all_expected == 0
        assert len(factory.calls) == factory.cleanups == 4
        assert {x[2] for x in factory.calls} == {"conv-30_q0", "conv-26_q0"}
        assert all(
            "GOLD_SENTINEL" not in prompt and "EVIDENCE_SENTINEL" not in prompt
            for judge, prompt, _ in factory.calls
            if not judge
        )
        assert all("GOLD_SENTINEL" in prompt for judge, prompt, _ in factory.calls if judge)
        assert all(
            "GOLD_SENTINEL" not in json.dumps(body) and "EVIDENCE_SENTINEL" not in json.dumps(body)
            for body in service.ingestion_bodies
        )
        assert summary.model_usage["answer"].input_tokens == 14
        assert summary.model_usage["judge"].output_tokens == 6
        assert summary.attempts_with_unknown_usage == 0
        assert summary.retrieval_sample_count == 2
        recalls = sum("recall" in path for _, path in service.requests)
        before = {p.name: a.core.file_sha(p) for p in (directory / "results").glob("*.json")}
        second = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert second.valid_complete_run and second.correct == 0
        assert len(factory.calls) == 4 and sum("recall" in path for _, path in service.requests) == recalls
        assert before == {p.name: a.core.file_sha(p) for p in (directory / "results").glob("*.json")}
        assert len(service.documents) == 2 and all(
            method != "DELETE" and "reflect" not in path for method, path in service.requests
        )
        assert "NEVER_COPY_THIS_SECRET" not in "".join(p.read_text() for p in directory.glob("*-server-config-*.json"))
        native = json.loads(next((directory / "amb-output").rglob("locomo10.json")).read_text())
        assert native["total_queries"] == 2 and native["answer_llm"] == "openai-codex:gpt-6.1-sol"
        assert native["ingested_docs"] == 4 and native["ingestion_time_ms"] > 0
        for path in (directory / "retrievals").glob("*.json"):
            row = a.unseal(path, a.RetrievalRecord, manifest)
            assert row.packing.text in next(
                prompt for judge, prompt, qid in factory.calls if not judge and qid == row.question_id
            )
        analysis = a.module_from_file("memory_analysis_test", SCRIPT.with_name("analysis.py"))
        request_count = len(service.requests)
        output = tmp_path / "public-results.json"
        exported = analysis.export(directory, output, directory)
        assert len(exported.rows) == 2 and exported.changes.both_wrong == 2
        assert exported.resource_epochs is None
        assert len(service.requests) == request_count and len(factory.calls) == 4
        assert "TEST_ONLY_SECRET" not in output.read_text()
        assert "credential" not in json.loads(output.read_text())["settings"]
        with pytest.raises(FileExistsError):
            analysis.export(directory, output)
        if packing_algorithm == "query-turn-windows-v1" and reader_profile == "amb-default":
            qids = [row.question_id for row in exported.rows]
            declaration = analysis.ResourceEpochDeclaration(
                source_run_id=manifest.run_id,
                source_manifest_sha256=h.file_sha(directory / "manifest.json"),
                initial_manifest_reranker_label=manifest.config.memory_profile.reranker,
                setting="HINDSIGHT_API_RERANKER_LOCAL_MAX_CONCURRENT",
                before=1,
                after=2,
                pause_started_at="2026-11-19T03:45:00+00:00",
                resumed_at="2026-11-19T03:45:23+00:00",
                pause_elapsed_s=23,
                env_before_sha256="1" * 64,
                env_after_sha256="2" * 64,
                switch_journal_sha256="3" * 64,
                phase1_recall_question_ids=qids[:1],
                transition_question_ids=[],
                phase2_recall_question_ids=qids[1:],
            )
            phase_path = directory / "performance-epochs.json"
            phase_path.write_text(declaration.model_dump_json(indent=2))
            phase_bytes = phase_path.read_bytes()
            hashes = {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
            phase_export = analysis.export(directory, tmp_path / "resource-epochs-export.json", directory)
            report = phase_export.resource_epochs
            assert report is not None and not report.historical_source_timings
            assert [p.questions for p in report.latency] == [1, 0, 1]
            assert [p.reranker_concurrency for p in report.latency] == [1, None, 2]
            assert report.latency[0].recall_p50_ms == exported.rows[0].recall_ms
            assert report.latency[1].recall_p95_ms is None
            assert phase_export.summary == exported.summary and phase_export.rows == exported.rows
            assert report.declaration_sha256 == h.file_sha(phase_path)
            assert hashes == {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
            inherited = manifest.model_copy(
                update={
                    "checkpoint_imports": manifest.checkpoint_imports
                    | {"performance-epochs.json": h.file_sha(phase_path)},
                    "retrieval_origin": a.RetrievalOrigin(
                        run_id=manifest.run_id, manifest_sha256=h.file_sha(directory / "manifest.json")
                    ),
                }
            )
            inherited_report = analysis.resource_epoch_report(directory, inherited, exported.rows)
            assert inherited_report.historical_source_timings and inherited_report.latency == report.latency
            for invalid in ("scope", "foreign", "inherited-tamper"):
                raw = declaration.model_dump()
                if invalid == "scope":
                    raw["phase2_recall_question_ids"] = qids[:1]
                if invalid == "foreign":
                    raw["source_manifest_sha256"] = "0" * 64
                phase_path.write_text(json.dumps(raw))
                current_manifest = manifest
                if invalid == "inherited-tamper":
                    current_manifest = manifest.model_copy(
                        update={
                            "checkpoint_imports": manifest.checkpoint_imports | {"performance-epochs.json": "0" * 64}
                        }
                    )
                with pytest.raises(ValueError, match="Resource|resource"):
                    analysis.resource_epoch_report(directory, current_manifest, exported.rows)
            phase_path.write_bytes(phase_bytes)
            assert hashes == {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
            assert len(service.requests) == request_count and len(factory.calls) == 4
        coverage_settings = analysis.h.core.PackingSettings.model_validate(
            manifest.config.packing.model_dump()
            | {"algorithm": "query-turn-windows-v1", "chunk_order": "query_relevance"}
        )
        coverage = analysis.coverage(directory, tmp_path / "coverage.json", coverage_settings)
        assert len(coverage.rows) == 2
        assert len(service.requests) == request_count and len(factory.calls) == 4
        probe = a.module_from_file("memory_probe_test", SCRIPT.with_name("probe.py"))
        probe_dir = tmp_path / "recall-probe"
        overrides = tmp_path / "probe-settings.json"
        overrides.write_text(
            json.dumps(
                {
                    "recall": {"max_tokens": 32768, "max_chunk_tokens": 65536},
                    "packing": {
                        "algorithm": "query-turn-windows-v1",
                        "chunk_order": "query_relevance",
                        "max_tokens": 600,
                        "fact_tokens": 0,
                        "chunk_tokens": 550,
                    },
                }
            )
        )
        probe_config = probe.initialize(directory, probe_dir, ["conv-30_q0"], "recall", overrides)
        calls_before = len(service.requests)
        await probe.recall(directory, probe_dir, probe_config)
        assert [v for v in service.requests[calls_before:] if v[0] != "GET"] == [
            ("POST", f"/v1/default/banks/{manifest.conversations[0].bank_id}/memories/recall")
        ]
        assert len(factory.calls) == 4
        assert (probe_dir / "conv-30_q0-packing.json").is_file()
        probe_request = json.loads((probe_dir / "conv-30_q0-request.json").read_text())
        assert probe_request["max_tokens"] == 32768
        assert probe_request["include"]["chunks"]["max_tokens"] == 65536
        packed_probe = json.loads((probe_dir / "conv-30_q0-packing.json").read_text())
        assert packed_probe["tokens"] <= 600 and packed_probe["included_fact_ids"] == []
        assert json.loads((probe_dir / "manifest.json").read_text())["packing"]["max_tokens"] == 600
        assert (probe_dir / "overrides.json").read_bytes() == overrides.read_bytes()
        assert (probe_dir / "server-version-before.json").read_bytes() == (
            probe_dir / "server-version-after.json"
        ).read_bytes()
        assert "NEVER_COPY_THIS_SECRET" not in (probe_dir / "conv-30-server-config-probe-before.json").read_text()
        assert manifest.config.packing.max_tokens == 8192 and manifest.config.recall.max_tokens == 8192
        requests_after_probe = len(service.requests)
        night = a.module_from_file("memory_night_test", SCRIPT.with_name("night.py"))
        with h.run_lock(directory):
            assert night.locked(directory)
        assert not night.locked(directory)
        assert night.run(directory, tmp_path / "night-status.json", None, 1) == 0
        assert json.loads((tmp_path / "night-status.json").read_text())["stage"] == "completed"
        assert (directory / "public-results.json").is_file()
        assert len(factory.calls) == 4 and len(service.requests) == requests_after_probe


@pytest.mark.parametrize("change", ["amb", "helper", "config", "record"])
def test_drift_rejected_and_legacy_untouched(tmp_path, checkout, change):
    directory, manifest = prepared(tmp_path, checkout)
    if change == "amb":
        (directory / "amb-source/src/memory_bench/dataset/locomo.py").write_text("# changed")
    elif change == "helper":
        (directory / "support.py").write_text("# changed")
    elif change == "config":
        value = json.loads((directory / "manifest.json").read_text())
        value["config"]["packing"]["max_tokens"] = 16000
        (directory / "manifest.json").write_text(json.dumps(value))
    else:
        record = a.SavedResult(
            fingerprint=manifest.fingerprint,
            question_id="conv-30_q0",
            answer_f1=0,
            amb_result=a.NativeResult(
                query_id="conv-30_q0",
                query="q",
                answer="a",
                correct=False,
                context="{}",
                context_tokens=1,
                retrieve_time_ms=1,
                reasoning="r",
                gold_answers=["g"],
                judge_reason="r",
                meta={},
            ),
        )
        path = directory / "results/conv-30_q0.json"
        a.seal(path, record)
        path.write_text(path.read_text().replace('"correct": false', '"correct": true'))
        with pytest.raises(ValueError, match="Checkpoint"):
            a.report(directory, manifest)
        return
    with pytest.raises(ValueError):
        a.load_manifest(directory)


def test_legacy_refused_without_a_lock_or_mutation(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "run.json").write_text('{"accuracy": 0.9136}')
    before = (old / "run.json").read_bytes()
    with pytest.raises(ValueError, match="legacy"):
        a.load_manifest(old)
    assert (old / "run.json").read_bytes() == before
    assert len(list(old.iterdir())) == 1


@pytest.mark.asyncio
async def test_interrupted_judge_does_not_regenerate_answer(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    factory = Factory(manifest, interrupt_judge=True)
    archive = a.Archive(directory, manifest, factory)
    modules = a.amb_modules(directory)
    schema = modules["modes.rag"]._OPEN_SCHEMA
    qid = "conv-30_q0"
    await archive.generate(qid, "answer", "Public prompt", schema)
    judge_schema = modules["judge"]._SCHEMA
    with pytest.raises(asyncio.CancelledError):
        await archive.generate(qid, "judge", "Gold prompt", judge_schema)
    await archive.generate(qid, "answer", "Public prompt", schema)
    await archive.generate(qid, "judge", "Gold prompt", judge_schema)
    assert len([x for x in factory.calls if not x[0]]) == 1
    assert len([x for x in factory.calls if x[0]]) == 2
    saved = a.unseal(archive.call_path(qid, "judge"), a.CallRecord, manifest)
    assert [attempt.state for attempt in saved.attempts] == ["interrupted_unknown", "completed"]
    summary = a.report(directory, manifest)
    assert summary.attempts_with_unknown_usage == 1 and not summary.valid_complete_run


@pytest.mark.asyncio
async def test_failed_judge_stays_in_denominator_and_is_not_retried(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout, conversations=("conv-30", "conv-26"))
    factory = Factory(manifest, fail_judge=True)
    archive = a.Archive(directory, manifest, factory)
    schema = a.amb_modules(directory)["judge"]._SCHEMA
    with pytest.raises(RuntimeError, match="stage failed"):
        await archive.generate("conv-30_q0", "judge", "Gold prompt", schema)
    with pytest.raises(RuntimeError, match="previously failed"):
        await archive.generate("conv-30_q0", "judge", "Gold prompt", schema)
    summary = a.report(directory, manifest)
    assert summary.expected == 2 and summary.failed == 1 and summary.pending == 1
    assert summary.accuracy_all_expected == 0 and len(factory.calls) == 1


@pytest.mark.asyncio
async def test_supplementary_f1_tokens_percentiles_and_full_prompt_are_separate(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout, conversations=("conv-30", "conv-26"))
    factory = Factory(manifest, answer="GOLD_SENTINEL_NOT_IN_MEMORY")
    archive = a.Archive(directory, manifest, factory)
    schema = a.amb_modules(directory)["modes.rag"]._OPEN_SCHEMA
    latencies = [100.0, 900.0]
    token_counts = []
    for conversation, latency in zip(manifest.conversations, latencies, strict=True):
        question = conversation.questions[0]
        qid = a.amb_id(question)
        recall = recall_fixture(conversation)
        packed = a.core.pack_context(recall, conversation, manifest.config.packing)
        token_counts.append(packed.tokens)
        a.seal(
            directory / f"retrievals/{qid}.json",
            a.RetrievalRecord(
                fingerprint=manifest.fingerprint,
                question_id=qid,
                bank_id=conversation.bank_id,
                recall=a.core.RecallReply.model_validate(recall.model_dump()),
                packing=packed,
                retrieval_elapsed_ms=latency,
            ),
        )
        await archive.generate(qid, "answer", "Full answer prompt " + packed.text, schema)
    summary = a.report(directory, manifest)
    assert summary.answer_f1_all_expected == 1.0  # Original F1 on synthetic identical answers
    assert summary.retrieval_ms_p50 == np.percentile(latencies, 50)
    assert summary.retrieval_ms_p95 == np.percentile(latencies, 95)
    assert summary.context_tokens_total == sum(token_counts)
    assert summary.full_answer_prompt_tokens_mean > summary.context_tokens_mean
    expected = [
        len(tiktoken.get_encoding("cl100k_base").encode(a.unseal(p, a.RetrievalRecord, manifest).packing.text))
        for p in (directory / "retrievals").glob("*.json")
    ]
    assert summary.amb_cl100k_context_tokens_mean == sum(expected) / 2
    assert not summary.valid_complete_run  # No judge/results; F1 isn't accuracy.


def test_preview_is_offline_and_preserves_source(tmp_path, checkout, monkeypatch):
    directory, manifest = prepared(tmp_path, checkout)
    recall = recall_fixture(manifest.conversations[0])
    source = tmp_path / "saved-recall.json"
    source.write_text(recall.model_dump_json())
    before = source.read_bytes()
    monkeypatch.delenv("CONTEXTBASE_BENCH_KEY", raising=False)
    output = directory / "preview.json"
    result = a.preview(directory, source, "conv-30", output)
    assert json.loads(result.packing.text)["chunks"]
    assert result.packing.tokens <= 8192 and source.read_bytes() == before
    with pytest.raises(ValueError, match="exists"):
        a.preview(directory, source, "conv-30", output)
    assert not (directory / "calls").exists()


@pytest.mark.asyncio
async def test_concurrent_same_bank_questions_keep_their_own_prompt_and_judge(tmp_path, checkout, monkeypatch):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        directory, manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), questions_per_conversation=3
        )
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        factory = Factory(manifest)
        summary = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert summary.valid_complete_run and summary.completed == 3
        assert len(factory.calls) == 6
        for qid in ("conv-30_q0", "conv-30_q1", "conv-30_q2"):
            assert sorted(judge for judge, _, identity in factory.calls if identity == qid) == [False, True]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["recall", "judge"])
async def test_recall_failure_is_archived_and_not_retried_or_removed(tmp_path, checkout, monkeypatch, failure_stage):
    service = FakeBankService()

    async def handler(request):
        if request.path.endswith("/memories/recall") and failure_stage == "recall":
            service.requests.append((request.method, request.path))
            return web.json_response({"error": "scripted upstream failure"}, status=503)
        return await service.handle(request)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    async with TestServer(app) as server:
        directory, manifest = prepared(tmp_path, checkout, api_url=str(server.make_url("/")))
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        factory = Factory(manifest, fail_judge=failure_stage == "judge")
        await asyncio.to_thread(a.run, directory, manifest, factory)
        summary = a.report(directory, manifest)
        assert summary.failed == summary.expected == 1
        assert summary.retrieval_sample_count == (0 if failure_stage == "recall" else 1)
        assert not summary.valid_complete_run and summary.accuracy_all_expected == 0
        assert len(factory.calls) == (0 if failure_stage == "recall" else 2)
        analysis = a.module_from_file("memory_failed_diagnostic_" + failure_stage, SCRIPT.with_name("analysis.py"))
        observed_requests = len(service.requests)
        diagnostic = analysis.wrong_snapshot(directory, tmp_path / "failed-diagnostic.json")
        assert diagnostic.wrong_cases[0].operational_error is not None
        assert diagnostic.wrong_cases[0].inspection_hint == "inspect_operational_failure"
        assert len(service.requests) == observed_requests
        await asyncio.to_thread(a.run, directory, manifest, factory)
        assert sum("recall" in path for _, path in service.requests) == 1


@pytest.mark.asyncio
async def test_runtime_drift_stops_calls_before_evaluation(tmp_path, checkout, monkeypatch):
    service = FakeBankService()
    drifted = False

    async def handler(request):
        if request.path.endswith("/config") and drifted:
            return web.json_response({"config": {"changed": True}})
        return await service.handle(request)

    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    async with TestServer(app) as server:
        directory, manifest = prepared(tmp_path, checkout, api_url=str(server.make_url("/")))
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        drifted = True
        factory = Factory(manifest)
        with pytest.raises(ValueError, match="configuration changed"):
            await asyncio.to_thread(a.run, directory, manifest, factory)
        assert not factory.calls and not a.report(directory, manifest).valid_complete_run


def test_original_scoring_functions_on_synthetic_answers(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    scoring = a.core.FrozenScoring(directory)
    assert scoring.single("The red bicycle", "red") == pytest.approx(2 / 3)
    assert scoring.single("bicycles", "bicycle") == 1
    assert scoring.multi("red, blue", "red, blue") == 1
    assert scoring.single("", "red") == 0


def test_fact_flood_cannot_starve_original_passage(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    recalled = recall_fixture(manifest.conversations[0])
    packing = h.pack_context(
        recalled, manifest.conversations[0], h.PackingSettings(max_tokens=1200, fact_tokens=600, chunk_tokens=500)
    )
    payload = json.loads(packing.text)
    assert payload["facts"] and payload["chunks"]
    assert payload["chunks"][0]["text"] == next(iter(recalled.chunks.values())).text
    assert packing.tokens == len(tiktoken.get_encoding("o200k_base").encode(packing.text)) <= 1200
    assert packing.omitted
    assert all(x["mentioned_at"] == "2023-01-01T13:00:00Z" for x in payload["facts"])
    assert (
        h.pack_context(
            recalled, manifest.conversations[0], h.PackingSettings(max_tokens=1200, fact_tokens=600, chunk_tokens=500)
        )
        == packing
    )


def test_oversized_fact_is_omitted_whole_not_sliced(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    packing = h.pack_context(
        recall_fixture(manifest.conversations[0], count=2, giant=True), manifest.conversations[0], h.PackingSettings()
    )
    assert packing.included_fact_ids == ["fact1"]
    assert packing.omitted[0].id == "fact0"
    assert json.loads(packing.text)["chunks"]


@pytest.mark.parametrize("crossing", ["fact", "chunk"])
def test_cross_bank_or_conversation_evidence_is_rejected(tmp_path, checkout, crossing):
    directory, manifest = prepared(tmp_path, checkout)
    recalled = recall_fixture(manifest.conversations[0], count=1)
    if crossing == "fact":
        recalled.results[0].document_id = "conv-other_session_1"
    else:
        recalled.chunks = {
            build_chunk_id("another_bank", manifest.conversations[0].sessions[0].document_id, 0): h.Chunk(
                text="foreign"
            )
        }
    with pytest.raises(ValueError, match="outside"):
        h.pack_context(recalled, manifest.conversations[0], h.PackingSettings())


def test_all_oversized_original_passages_fail_visibly(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    conversation = manifest.conversations[0]
    recalled = recall_fixture(conversation, count=1)
    next(iter(recalled.chunks.values())).text = "huge source " * 2000
    with pytest.raises(ValueError, match="No complete original passage fits"):
        h.pack_context(recalled, conversation, h.PackingSettings(max_tokens=300, fact_tokens=150, chunk_tokens=100))


@pytest.mark.asyncio
async def test_reuse_bank_verifies_without_writes_and_runs_on_same_memory(tmp_path, checkout, monkeypatch):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        seed = tmp_path / "seed"
        seed.mkdir()
        seed_dir, seed_manifest = prepared(seed, checkout, api_url=str(server.make_url("/")))
        await a.service_stage(seed_dir, seed_manifest, "ingest")
        existing = seed_manifest.conversations[0].bank_id
        before = json.dumps(service.documents, sort_keys=True)
        service.requests.clear()
        target = tmp_path / "reuse"
        target.mkdir()
        directory, manifest = prepared(
            target, checkout, api_url=str(server.make_url("/")), reuse_banks={"conv-30": existing}
        )
        await a.service_stage(directory, manifest, "verify")
        state = a.core.read_model(directory / "state.json", a.core.State)
        assert state.banks["conv-30"].verified and not state.banks["conv-30"].created
        assert all(method == "GET" for method, _ in service.requests)
        with pytest.raises(ValueError, match="Cannot ingest"):
            await a.service_stage(directory, manifest, "ingest")
        async with aiohttp.ClientSession() as session:
            http = a.core.BankHTTP(session, manifest.config, "TEST_ONLY_SECRET")
            for method, suffix in (("PUT", ""), ("DELETE", ""), ("POST", "/memories"), ("POST", "/reflect")):
                with pytest.raises(ValueError, match="read-only"):
                    await http.request(method, "/v1/default/banks/" + existing + suffix, a.core.RuntimeSnapshot)
        factory = Factory(manifest)
        summary = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert summary.valid_complete_run and summary.completed == 1
        assert summary.retained_banks == [existing]
        assert before == json.dumps(service.documents, sort_keys=True)
        assert all(
            method == "GET" or (method == "POST" and path.endswith("/memories/recall"))
            for method, path in service.requests
        )


@pytest.mark.asyncio
async def test_reuse_rejects_changed_source_documents(tmp_path, checkout, monkeypatch):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        directory, manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), reuse_banks={"conv-30": "unit_test_conv_30"}
        )
        service.documents["unit_test_conv_30"] = {s.document_id: s.content for s in manifest.conversations[0].sessions}
        service.polls["unit_test_conv_30"] = 2
        service.documents["unit_test_conv_30"][manifest.conversations[0].sessions[0].document_id] = "[]"
        with pytest.raises(ValueError, match="differs"):
            await a.service_stage(directory, manifest, "verify")
        assert all(method == "GET" for method, _ in service.requests)
        assert not a.core.read_model(directory / "state.json", a.core.State).banks


@pytest.mark.parametrize("mapping", [{"other": "bank_a"}, {"conv-30": "not/canonical"}])
def test_reuse_mapping_must_match_scope_and_safe_identity(tmp_path, checkout, mapping):
    with pytest.raises(ValueError):
        prepared(tmp_path, checkout, reuse_banks=mapping)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_error", ["ConnectionTimeoutError", "ClientPayloadError"])
async def test_checkpoint_adoption_preserves_all_verdicts_and_explicit_transport_attempts(
    tmp_path, checkout, transport_error
):
    directory, manifest = prepared(
        tmp_path, checkout, reuse_banks={"conv-30": "unit_test_conv_30"}, questions_per_conversation=2
    )
    archive = a.Archive(directory, manifest, Factory(manifest, structured=True))
    modules = a.amb_modules(directory)
    await archive.generate("conv-30_q0", "answer", "unchanged prompt", modules["modes.rag"]._OPEN_SCHEMA)
    await archive.generate("conv-30_q1", "answer", "other answer", modules["modes.rag"]._OPEN_SCHEMA)
    assert not (await archive.generate("conv-30_q1", "judge", "already wrong", modules["judge"]._SCHEMA))["correct"]
    analysis = a.module_from_file("memory_progress_test_" + transport_error, SCRIPT.with_name("analysis.py"))
    before = {str(p): a.core.file_sha(p) for p in (directory / "calls").glob("*.json")}
    observed = analysis.progress(directory)
    assert observed.completed_answers == 2 and observed.completed_judges == 1
    assert observed.final_result_checkpoints == 0 and observed.expected_questions == 2
    assert observed.model_call_statuses == {"answer:completed": 2, "judge:completed": 1}
    assert not observed.failed_question_ids
    assert before == {str(p): a.core.file_sha(p) for p in (directory / "calls").glob("*.json")}
    # Simulate two connection failures with no returned answer. The copied source
    # remains failed, while a new explicitly configured run may spend one attempt.
    judge_schema = a.ResponseSchema.model_validate(a.asdict(modules["judge"]._SCHEMA))
    a.seal(
        archive.call_path("conv-30_q0", "judge"),
        a.CallRecord(
            fingerprint=manifest.fingerprint,
            question_id="conv-30_q0",
            stage="judge",
            prompt="unchanged judge",
            response_schema=judge_schema,
            status="failed",
            attempts=[
                a.core.Attempt(stage="judge", state="failed", error=transport_error, at=a.core.now()) for _ in range(2)
            ],
        ),
    )
    before = {str(p.relative_to(directory)): a.core.file_sha(p) for p in directory.rglob("*.json")}
    config = json.loads((tmp_path / "config.json").read_text())
    config["checkpoint_source"] = {
        "path": str(directory / "manifest.json"),
        "sha256": a.core.file_sha(directory / "manifest.json"),
    }
    config["resume_connection_failures"] = True
    config["model_max_attempts"] = 3
    config["concurrency"] = 1
    next_config = tmp_path / "next-config.json"
    next_config.write_text(json.dumps(config))
    next_dir = tmp_path / "next-run"
    next_manifest = a.init_run(next_config, next_dir, "unit_next")
    assert a.load_manifest(next_dir) == next_manifest
    factory = Factory(next_manifest, structured=True, correct=True)
    next_archive = a.Archive(next_dir, next_manifest, factory)
    await next_archive.generate("conv-30_q0", "answer", "unchanged prompt", modules["modes.rag"]._OPEN_SCHEMA)
    await next_archive.generate("conv-30_q0", "judge", "unchanged judge", modules["judge"]._SCHEMA)
    assert not (await next_archive.generate("conv-30_q1", "judge", "already wrong", modules["judge"]._SCHEMA))[
        "correct"
    ]
    assert len(factory.calls) == 1 and factory.calls[0][0] is True
    saved = a.unseal(next_archive.call_path("conv-30_q0", "judge"), a.CallRecord, next_manifest)
    assert [attempt.state for attempt in saved.attempts] == ["failed", "failed", "completed"]
    assert before == {str(p.relative_to(directory)): a.core.file_sha(p) for p in directory.rglob("*.json")}
    config["packing"]["max_tokens"] = 16000
    next_config.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="identical"):
        a.init_run(next_config, tmp_path / "invalid", "unit_invalid")


@pytest.mark.asyncio
async def test_native_pydantic_structured_replies_are_archived_as_json_objects(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    factory = Factory(manifest, structured="model")
    archive = a.Archive(directory, manifest, factory)
    modules = a.amb_modules(directory)
    await archive.generate("conv-30_q0", "answer", "public", modules["modes.rag"]._OPEN_SCHEMA)
    await archive.generate("conv-30_q0", "judge", "gold", modules["judge"]._SCHEMA)
    for stage in ["answer", "judge"]:
        row = a.unseal(archive.call_path("conv-30_q0", stage), a.CallRecord, manifest)
        assert row.status == "completed" and isinstance(row.response, dict)


@pytest.mark.asyncio
async def test_truncated_http_body_is_retryable_but_invalid_response_is_not() -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Length": "100"})
        await response.prepare(request)
        await response.write(b'{"answer":')
        request.transport.close()
        return response

    app = web.Application()
    app.router.add_get("/partial", handler)
    async with TestServer(app) as server:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientPayloadError) as error:
                async with session.get(server.make_url("/partial")) as response:
                    await response.read()
    assert h.retryable(error.value)
    assert not h.retryable(ValueError("Invalid complete answer"))


def test_analysis_evidence_ids_do_not_match_longer_turns() -> None:
    analysis = a.module_from_file("memory_analysis_id_test", SCRIPT.with_name("analysis.py"))
    assert analysis.contains_id('{"dia_id":"D1:2"}', "D1:2")
    assert not analysis.contains_id('{"dia_id":"D1:25"}', "D1:2")


@pytest.mark.parametrize("mutation", ["none", "duplicate", "question", "gold", "scope", "index"])
def test_official_public_rows_join_by_validated_identity(tmp_path, checkout, mutation):
    directory, _ = prepared(tmp_path, checkout, conversations=("conv-30", "conv-26"))
    analysis = a.module_from_file("memory_public_test_" + mutation, SCRIPT.with_name("analysis.py"))
    mem0 = analysis.Mem0Results.model_validate(
        {
            "metadata": {"answerer_model": "reader-m", "judge_model": "judge-m", "total_questions": 2},
            "evaluations": [
                {
                    "question_id": f"conv{i}_q0",
                    "conversation_idx": i,
                    "category": 2,
                    "question": "A public question?",
                    "ground_truth_answer": "GOLD_SENTINEL_NOT_IN_MEMORY",
                    "search_latency_ms": 10 + i * 10,
                    "cutoff_results": {
                        "top_200": {
                            "judgment": "CORRECT" if i == 0 else "ERROR",
                            "generated_answer": "GOLD_SENTINEL_NOT_IN_MEMORY" if i == 0 else "",
                        }
                    },
                }
                for i in range(2)
            ],
        }
    )
    hindsight = analysis.HindsightResults.model_validate(
        {
            "answer_llm": "reader-h",
            "judge_llm": "judge-h",
            "total_queries": 2,
            "correct": 2,
            "results": [
                {
                    "query_id": f"{conv}_q0",
                    "query": "A public question?",
                    "answer": "GOLD_SENTINEL_NOT_IN_MEMORY",
                    "gold_answers": ["GOLD_SENTINEL_NOT_IN_MEMORY"],
                    "correct": True,
                    "retrieve_time_ms": 30,
                    "context_tokens": 400,
                }
                for conv in ("conv-26", "conv-30")  # Deliberately reordered, unlike Mem0.
            ],
        }
    )
    if mutation == "duplicate":
        hindsight.results[1] = hindsight.results[0].model_copy(deep=True)
    elif mutation == "question":
        hindsight.results[0].query = "Different question"
    elif mutation == "gold":
        mem0.evaluations[0].ground_truth_answer = "Changed gold"
    elif mutation == "scope":
        mem0.metadata.total_questions = 3
    elif mutation == "index":
        mem0.evaluations[0].question_id = "conv1_q0"
    if mutation != "none":
        with pytest.raises(ValueError):
            analysis.public_rows(directory, mem0, hindsight)
        return
    rows = analysis.public_rows(directory, mem0, hindsight)
    by_id = {r.question_id: r for r in rows}
    assert by_id["conv-30_q0"].mem0.correct
    assert by_id["conv-26_q0"].mem0.status == "ERROR"
    metrics = analysis.public_metrics([r.mem0 for r in rows])
    assert metrics.count == 2 and metrics.correct == 1 and metrics.errors == 1
    assert metrics.accuracy == 0.5 and metrics.derived_answer_f1 == 0.5
    assert metrics.derived_retrieval_p50_ms == 15 and metrics.derived_retrieval_p95_ms == 19.5
    assert metrics.context_tokens_mean is None
    assert analysis.public_metrics([r.hindsight for r in rows]).context_tokens_mean == 400
    assert not (directory / "calls").exists() and not (directory / "retrievals").exists()
    assert not (directory / "state.json").exists() or not json.loads((directory / "state.json").read_text())["banks"]


@pytest.mark.asyncio
async def test_common_judge_reuses_identical_inputs_without_memory_or_answer_calls(tmp_path, checkout, monkeypatch):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    rejudge = a.module_from_file("memory_common_judge_test", SCRIPT.with_name("rejudge.py"))
    new_prompts = []

    class JudgeOnly:
        async def call(self, *, messages, response_format, strict_schema, **kwargs):
            assert strict_schema and kwargs["max_retries"] == 0
            assert set(response_format.model_fields) == {"correct", "reason"}
            new_prompts.append(messages[0]["content"])
            await asyncio.sleep(0)  # Make simultaneous duplicate requests contend for the shared task.
            return LLMCallResult(
                content=response_format(correct=True, reason="Synthetic common judge"),
                usage=TokenUsage(input_tokens=7, output_tokens=3, total_tokens=10),
            )

        async def cleanup(self):
            pass

    def provider(settings, timeout):
        return JudgeOnly()

    async with TestServer(app) as server:
        directory, manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), questions_per_conversation=2
        )
        public_rows = []
        for i in range(2):
            answer = rejudge.a.PublicAnswer(
                answer="test answer" if i == 0 else "a different public answer",
                correct=True,
                status="CORRECT",
                derived_answer_f1=0,
                retrieval_ms=1,
            )
            public_rows.append(
                rejudge.a.PublicRow(
                    question_id=f"conv-30_q{i}", conversation_id="conv-30", category=2, mem0=answer, hindsight=answer
                )
            )
        metrics = rejudge.a.public_metrics([r.mem0 for r in public_rows])
        public = rejudge.a.PublicComparison(
            question_scope_sha256=manifest.question_scope_sha256,
            mem0_source=rejudge.a.Source(url=None, sha256="synthetic"),
            hindsight_source=rejudge.a.Source(url=None, sha256="synthetic"),
            mem0_answer_model="fixture-m",
            mem0_judge_model="fixture-m",
            hindsight_answer_model="fixture-h",
            hindsight_judge_model="fixture-h",
            mem0_metrics=metrics,
            hindsight_metrics=metrics,
            rows=public_rows,
        )
        public_path = tmp_path / "public.json"
        public_path.write_text(public.model_dump_json())
        output = tmp_path / "common-judge"
        rejudge.prepare(directory, public_path, output, "unit_common")
        assert not service.requests and not new_prompts
        with pytest.raises(ValueError, match="complete source baseline"):
            await rejudge.run(output, provider)
        assert not new_prompts
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        original_factory = Factory(manifest, structured=True)
        original = await asyncio.to_thread(a.run, directory, manifest, original_factory)
        assert original.valid_complete_run and original.correct == 0
        request_count = len(service.requests)
        hashes = {
            str(p): a.core.file_sha(p) for folder in ["calls", "results"] for p in (directory / folder).glob("*.json")
        }
        summary = await rejudge.run(output, provider)
        assert summary.valid_complete_comparison and summary.baseline_reused_rows == 2
        assert summary.newly_generated_unique_prompts == 1 and len(new_prompts) == 1
        assert summary.model_usage.total_tokens == 10 and summary.attempts_without_usage == 0
        assert all(
            s.completed == 2 and s.correct == 1 and s.accuracy_all_expected == 0.5 for s in summary.products.values()
        )
        assert len(service.requests) == request_count and len(original_factory.calls) == 4
        assert hashes == {
            str(p): a.core.file_sha(p) for folder in ["calls", "results"] for p in (directory / folder).glob("*.json")
        }
        before = (output / "summary.json").read_bytes()
        assert (await rejudge.run(output, provider)) == summary and len(new_prompts) == 1
        assert (output / "summary.json").read_bytes() == before

        class UnavailableJudge(JudgeOnly):
            async def call(self, **kwargs):
                raise ValueError("Synthetic terminal judge failure")

        failed_output = tmp_path / "failed-common-judge"
        rejudge.prepare(directory, public_path, failed_output, "unit_common_failed")
        with pytest.raises(RuntimeError, match="Model stage failed"):
            await rejudge.run(failed_output, lambda settings, timeout: UnavailableJudge())
        assert not (failed_output / "summary.json").exists()
        failed_calls = [p for product in rejudge.PRODUCTS for p in (failed_output / product / "calls").glob("*.json")]
        assert len(failed_calls) == 1
        failed_call = rejudge.h.core.read_model(failed_calls[0], rejudge.h.CallRecord)
        assert failed_call.stage == "judge" and failed_call.status == "failed"
        assert failed_call.attempts[0].error == "ValueError"
        assert len(service.requests) == request_count and len(new_prompts) == 1
        copied = output / "public-results.json"
        copied.write_text(copied.read_text() + " ")
        with pytest.raises(ValueError, match="Public answers modified"):
            await rejudge.run(output, provider)
        assert len(new_prompts) == 1


@pytest.mark.asyncio
async def test_numeric_gold_save_failure_recovers_newly_ingested_banks_without_new_model_calls(
    tmp_path, checkout, monkeypatch
):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        directory, manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), gold_answer=2022, evidence_ids=["D1:1"]
        )
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        original_factory = Factory(manifest, structured=True)

        class OldStringOnlyResult(a.NativeResult):
            gold_answers: list[str]

        with monkeypatch.context() as old:
            old.setattr(a, "NativeResult", OldStringOnlyResult)
            with pytest.raises(ValueError, match="gold_answers"):
                await asyncio.to_thread(a.run, directory, manifest, original_factory)
        assert len(original_factory.calls) == 2
        original_state = h.read_model(directory / "state.json", h.State)
        assert original_state.status == "interrupted_or_failed"
        hashes = {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
        config = json.loads((tmp_path / "config.json").read_text())
        config["checkpoint_source"] = {
            "path": str(directory / "manifest.json"),
            "sha256": h.file_sha(directory / "manifest.json"),
        }
        config["reuse_banks"] = {c.id: c.bank_id for c in manifest.conversations}
        cfg = tmp_path / "recovery.json"
        cfg.write_text(json.dumps(config))
        recovered_dir = tmp_path / "numeric-recovery"
        recovered = a.init_run(cfg, recovered_dir, "unit_numeric_recovery")
        state = h.read_model(recovered_dir / "state.json", h.State)
        assert state.answer_elapsed_s == original_state.answer_elapsed_s
        assert not state.banks["conv-30"].verified
        night = a.module_from_file("memory_recovery_night_test", SCRIPT.with_name("night.py"))
        assert night.next_stage(state, None, 1, reused_banks=True) == "verify"
        assert night.next_stage(state, None, 1) == "ingest"
        assert state.banks["conv-30"].ingestion_elapsed_s == original_state.banks["conv-30"].ingestion_elapsed_s
        assert (recovered_dir / "conv-30-server-config-before.json").read_bytes() == (
            directory / "conv-30-server-config-before.json"
        ).read_bytes()
        await a.service_stage(recovered_dir, recovered, "verify")
        calls_before = len(service.requests)
        new_factory = Factory(recovered, structured=True)
        summary = await asyncio.to_thread(a.run, recovered_dir, recovered, new_factory)
        assert summary.valid_complete_run and summary.completed == 1 and summary.correct == 0
        assert not new_factory.calls
        assert all(method == "GET" for method, _ in service.requests[calls_before:])
        saved = a.unseal(recovered_dir / "results/conv-30_q0.json", a.SavedResult, recovered)
        assert saved.amb_result.gold_answers == [2022] and type(saved.amb_result.gold_answers[0]) is int
        analysis = a.module_from_file("memory_numeric_export_test", SCRIPT.with_name("analysis.py"))
        exported = analysis.export(recovered_dir, tmp_path / "numeric-export.json")
        assert exported.rows[0].gold == [2022]
        requests_before = len(service.requests)
        diagnostic = analysis.wrong_snapshot(recovered_dir, tmp_path / "wrong-diagnostic.json")
        assert diagnostic.kind == "posthoc-error-diagnostics-not-a-score"
        assert diagnostic.saved_result_count == 1 and len(diagnostic.wrong_cases) == 1
        passage = diagnostic.wrong_cases[0].passages[0]
        assert passage.evidence_id == "D1:1" and passage.document_id == "conv-30_session_1"
        assert passage.neighboring_turns[0].text == "Public session memory."
        assert passage.session_timestamp.startswith("2023-01-01")
        assert len(service.requests) == requests_before and not new_factory.calls
        with pytest.raises(FileExistsError):
            analysis.wrong_snapshot(recovered_dir, tmp_path / "wrong-diagnostic.json")
        assert h.read_model(recovered_dir / "state.json", h.State).answer_elapsed_s >= original_state.answer_elapsed_s
        assert hashes == {str(p): h.file_sha(p) for p in directory.rglob("*.json")}


def record_pending_restart(directory, manifest, qid):
    path = directory / "performance/reranker2-switch-test/journal.json"
    path.parent.mkdir(parents=True)
    proof = a.RecordedRestart(
        initial_manifest_sha256=h.file_sha(directory / "manifest.json"),
        completed_qa_before=[],
        transition_question_ids=[qid],
        sealed_file_hashes={f"retrievals/{qid}.json": h.file_sha(directory / "retrievals" / f"{qid}.json")},
        events=a.RestartEvents(
            all_sealed_records_preserved=True,
            paused_at="2026-11-19T03:45:00+00:00",
            ready_at="2026-11-19T03:45:20+00:00",
            resumed_at="2026-11-19T03:45:23+00:00",
            pause_elapsed_s=23,
        ),
    )
    path.write_text(proof.model_dump_json(indent=2))
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize("orphan_error", ["interrupted_unknown", None, "HTTPFailure"])
async def test_interrupted_retrieval_retries_only_the_unanswered_question(
    tmp_path, checkout, monkeypatch, orphan_error
):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        directory, manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), questions_per_conversation=2 if orphan_error else 1
        )
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        await a.service_stage(directory, manifest, "ingest")
        if orphan_error == "HTTPFailure":
            a.seal(
                directory / "retrievals/conv-30_q0.json",
                a.RetrievalRecord(
                    fingerprint=manifest.fingerprint,
                    question_id="conv-30_q0",
                    bank_id=manifest.conversations[0].bank_id,
                ),
            )
            record_pending_restart(directory, manifest, "conv-30_q0")
        a.seal(
            directory / "retrievals/conv-30_q0.json",
            a.RetrievalRecord(
                fingerprint=manifest.fingerprint,
                question_id="conv-30_q0",
                bank_id=manifest.conversations[0].bank_id,
                error=orphan_error,
            ),
        )
        original_factory = Factory(manifest, structured=True)
        if orphan_error:
            partial = await asyncio.to_thread(a.run, directory, manifest, original_factory)
            assert not partial.valid_complete_run and partial.failed == 1
            assert len(original_factory.calls) == 2  # q1 only, no judge on an operational placeholder.
        else:
            # A process stopped mid-request has not returned to AMB at all.
            # Do not resume the expired socket merely to manufacture a failure.
            assert not original_factory.calls
        before = {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
        cfg = json.loads((tmp_path / "config.json").read_text())
        cfg.update(
            reuse_banks={c.id: c.bank_id for c in manifest.conversations},
            checkpoint_source={
                "path": str(directory / "manifest.json"),
                "sha256": h.file_sha(directory / "manifest.json"),
            },
            resume_connection_failures=True,
        )
        cfg_path = tmp_path / "retry-recall.json"
        cfg_path.write_text(json.dumps(cfg))
        recovered_dir = tmp_path / "recall-recovery"
        recovered = a.init_run(cfg_path, recovered_dir, "unit_recall_recovery")
        if orphan_error == "HTTPFailure":
            proof = "performance/reranker2-switch-test/journal.json"
            assert (recovered_dir / "checkpoint-source" / proof).read_bytes() == (directory / proof).read_bytes()
            assert not (recovered_dir / proof).exists()  # No recursive use of the same restart proof.
        assert not (recovered_dir / "calls/conv-30_q0-judge.json").exists()
        await a.service_stage(recovered_dir, recovered, "verify")
        factory = Factory(recovered, structured=True)
        summary = await asyncio.to_thread(a.run, recovered_dir, recovered, factory)
        assert summary.valid_complete_run and summary.completed == (2 if orphan_error else 1) and summary.failed == 0
        assert len(factory.calls) == 2 and all(qid == "conv-30_q0" for _, _, qid in factory.calls)
        assert summary.model_usage["answer"].total_tokens == (20 if orphan_error else 10)
        assert summary.model_usage["judge"].total_tokens == (20 if orphan_error else 10)
        assert before == {str(p): h.file_sha(p) for p in directory.rglob("*.json")}


@pytest.mark.parametrize("invalid", ["no-proof", "foreign-manifest", "wrong-preimage", "semantic-call", "unfinished"])
def test_http_failure_needs_exact_recorded_restart_and_no_semantic_call(tmp_path, checkout, invalid):
    directory, manifest = prepared(tmp_path, checkout)
    qid = "conv-30_q0"
    record = a.RetrievalRecord(
        fingerprint=manifest.fingerprint, question_id=qid, bank_id=manifest.conversations[0].bank_id
    )
    a.seal(directory / "retrievals" / f"{qid}.json", record)
    proof_path = record_pending_restart(directory, manifest, qid)
    record.error = "HTTPFailure"
    a.seal(directory / "retrievals" / f"{qid}.json", record)
    proof = json.loads(proof_path.read_text())
    if invalid == "no-proof":
        proof_path.unlink()
        assert not a.recorded_restart_recovery(directory, manifest).question_ids
        return
    if invalid == "foreign-manifest":
        proof["initial_manifest_sha256"] = "0" * 64
    elif invalid == "wrong-preimage":
        proof["sealed_file_hashes"][f"retrievals/{qid}.json"] = "0" * 64
    elif invalid == "semantic-call":
        (directory / "calls").mkdir(exist_ok=True)
        (directory / "calls" / f"{qid}-answer.json").write_text("Already generated; cannot recover this way.")
    elif invalid == "unfinished":
        del proof["events"]["resumed_at"]
    proof_path.write_text(json.dumps(proof))
    before = {str(p): h.file_sha(p) for p in directory.rglob("*.json")}
    with pytest.raises(ValueError):
        a.recorded_restart_recovery(directory, manifest)
    assert before == {str(p): h.file_sha(p) for p in directory.rglob("*.json")}


def test_query_windows_find_late_raw_turn_within_fixed_budget(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    conversation = manifest.conversations[0]
    cid = build_chunk_id(conversation.bank_id, conversation.sessions[0].document_id, 0)
    turns = [
        {"speaker": "Person A", "dia_id": f"D1:{i}", "text": "Routine work and everyday news. " * 5} for i in range(70)
    ]
    turns[-2]["text"] = "Orion launched on Tuesday."
    recalled = h.RecallReply(results=[], chunks={cid: h.Chunk(text=json.dumps(turns))})
    before = recalled.model_dump(mode="json")
    settings = h.PackingSettings(
        algorithm="query-turn-windows-v1",
        chunk_order="query_relevance",
        max_tokens=600,
        fact_tokens=0,
        chunk_tokens=550,
    )
    result = h.pack_context(recalled, conversation, settings, query="When did Orion launch?")
    assert "Orion launched on Tuesday." in result.text
    assert result.tokens <= 600 and result.chunk_tokens <= 550
    assert result.included_chunk_ids == [cid]
    assert "D1:68" in result.text
    assert recalled.model_dump(mode="json") == before
    assert h.pack_context(recalled, conversation, settings, query="When did Orion launch?").text == result.text
    json.loads(result.text)


def test_query_windows_recover_complete_messages_and_preserve_image_caption():
    text = (
        '[{"speaker":"Alice","dia_id":"D1:1","text":"Look at this picture",'
        '"blip_caption":"Dancers performing on stage"},'
        '{"speaker":"Bob","dia_id":"D1:2","text":"incomplete'
    )
    turns = h.complete_turns(text)
    assert len(turns) == 1
    assert "Dancers performing on stage" in turns[0].render()
    assert "incomplete" not in turns[0].render()


def test_query_windows_do_not_read_original_session_contents(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    conversation = manifest.conversations[0]
    conversation.sessions[0].content = "ORIGINAL_ONLY_SENTINEL_NOT_RETURNED"
    cid = build_chunk_id(conversation.bank_id, conversation.sessions[0].document_id, 0)
    reply = h.RecallReply(results=[], chunks={cid: h.Chunk(text="Only this observed passage is returned.")})
    settings = h.PackingSettings(algorithm="query-turn-windows-v1", chunk_order="query_relevance")
    packed = h.pack_context(reply, conversation, settings, query="What passage was returned?")
    assert "Only this observed passage is returned." in packed.text
    assert "ORIGINAL_ONLY_SENTINEL" not in packed.text


def test_query_windows_require_query_and_validate_even_unselected_banks(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    conversation = manifest.conversations[0]
    settings = h.PackingSettings(algorithm="query-turn-windows-v1", chunk_order="query_relevance")
    with pytest.raises(ValueError, match="question text"):
        h.pack_context(h.RecallReply(results=[]), conversation, settings)
    cid = build_chunk_id("foreign_bank", conversation.sessions[0].document_id, 0)
    reply = h.RecallReply(results=[], chunks={cid: h.Chunk(text="unrelated")})
    with pytest.raises(ValueError, match="outside"):
        h.pack_context(reply, conversation, settings, query="Which passage?")


@pytest.mark.parametrize("algorithm", ["query-turn-windows-v1", "query-turn-windows-metadata-v2"])
def test_query_window_settings_cannot_claim_legacy_order(algorithm):
    with pytest.raises(ValueError, match="query_relevance"):
        h.PackingSettings(algorithm=algorithm)


def test_metadata_windows_retain_original_query_as_labeled_metadata_within_budget(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    conversation = manifest.conversations[0]
    conversation.sessions[0].content = "ORIGINAL_ONLY_SENTINEL_NOT_RETURNED"
    cid = build_chunk_id(conversation.bank_id, conversation.sessions[0].document_id, 0)
    source = json.dumps(
        [
            {"speaker": "Alice", "dia_id": "D1:1", "text": "A quiet day."},
            {
                "speaker": "Bob",
                "dia_id": "D1:2",
                "text": "Look at this picture.",
                "blip_caption": "A person with a wrapped leg.",
                "query": "ankle injury bandage",
                "img_url": ["https://example.invalid/not-fetched.png"],
            },
        ]
    )
    reply = h.RecallReply(results=[], chunks={cid: h.Chunk(text=source)})
    before = reply.model_dump(mode="json")
    settings = h.PackingSettings(
        algorithm="query-turn-windows-metadata-v2",
        chunk_order="query_relevance",
        max_tokens=300,
        fact_tokens=0,
        chunk_tokens=250,
    )
    packed = h.pack_context(reply, conversation, settings, query="Where was the injury?")
    assert "Source image-search query (metadata, not an observed caption): ankle injury bandage" in packed.text
    assert "Image caption: A person with a wrapped leg." in packed.text
    assert "not-fetched.png" not in packed.text and "ORIGINAL_ONLY_SENTINEL" not in packed.text
    assert packed.tokens <= 300 and packed.chunk_tokens <= 250
    assert reply.model_dump(mode="json") == before
    assert h.pack_context(reply, conversation, settings, query="Where was the injury?").text == packed.text
    legacy = settings.model_copy(update={"algorithm": "query-turn-windows-v1"})
    assert "ankle injury bandage" not in h.pack_context(reply, conversation, legacy, query="Where was the injury?").text


@pytest.mark.parametrize("value", [None, 12, {"unexpected": "metadata"}])
def test_malformed_optional_image_query_does_not_hide_observed_speech(value):
    text = json.dumps([{"speaker": "Alice", "text": "Observed speech.", "query": value}])
    turns = h.complete_turns(text)
    assert len(turns) == 1 and turns[0].render() == "Alice: Observed speech."
    assert turns[0].render(include_image_search_query=True) == turns[0].render()


def test_probe_overrides_reject_unknown_or_invalid_settings_before_output(tmp_path, checkout):
    directory, _ = prepared(tmp_path, checkout)
    probe = a.module_from_file("memory_invalid_probe_test", SCRIPT.with_name("probe.py"))
    path = tmp_path / "invalid-overrides.json"
    for settings in [
        {"gold": "never accepted"},
        {"recall": {"max_chunk_tokens": 0}},
        {"packing": {"algorithm": "query-turn-windows-v1"}},
    ]:
        path.write_text(json.dumps(settings))
        with pytest.raises(ValueError):
            probe.initialize(directory, tmp_path / "invalid-probe", ["conv-30_q0"], "recall", path)
        assert not (tmp_path / "invalid-probe").exists()
    path.write_text(json.dumps({"recall": {"max_chunk_tokens": 65536}}))
    with pytest.raises(ValueError, match="live recall"):
        probe.initialize(directory, tmp_path / "invalid-local", ["conv-30_q0"], "local", path)
    assert not (tmp_path / "invalid-local").exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"reader_profile": "locomo-grounded-concise-v1"},
        {"protocol": "amb-locomo-cat1to4-reader-v2"},
        {"reader_profile": "unknown", "protocol": "amb-locomo-cat1to4-reader-v2"},
    ],
)
def test_reader_profile_cannot_claim_unchanged_amb_protocol(tmp_path, settings):
    path = config_fixture(tmp_path)
    value = json.loads(path.read_text())
    a.Config.model_validate(value)
    value |= settings
    with pytest.raises(ValueError):
        a.Config.model_validate(value)
    with pytest.raises(ValueError, match="Unknown reader profile"):
        h.reader_prompt("unchanged", "unknown")


def test_checkpoint_reuse_requires_identical_reader_profile(tmp_path, checkout):
    directory, manifest = prepared(tmp_path, checkout)
    cfg = manifest.config.model_dump(mode="json")
    cfg.update(
        reader_profile="locomo-grounded-concise-v1",
        protocol="amb-locomo-cat1to4-reader-v2",
        reuse_banks={c.id: c.bank_id for c in manifest.conversations},
        checkpoint_source={"path": str(directory / "manifest.json"), "sha256": h.file_sha(directory / "manifest.json")},
    )
    path = tmp_path / "different-reader.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="identical questions"):
        a.init_run(path, tmp_path / "reader-must-not-adopt", "new_reader")
    assert not (tmp_path / "reader-must-not-adopt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_profile", ["amb-default", "locomo-grounded-concise-v1"])
async def test_retrieval_only_full_scope_experiment_makes_all_new_answers_without_recall(
    tmp_path, checkout, monkeypatch, reader_profile
):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        source, source_manifest = prepared(
            tmp_path, checkout, api_url=str(server.make_url("/")), questions_per_conversation=2
        )
        await a.service_stage(source, source_manifest, "ingest")
        original_factory = Factory(source_manifest, answer="original source answer")
        original = await asyncio.to_thread(a.run, source, source_manifest, original_factory)
        assert original.valid_complete_run and original.correct == 0
        before = {str(p): h.file_sha(p) for p in source.rglob("*.json")}
        cfg = source_manifest.config.model_dump(mode="json")
        cfg.update(
            reuse_banks={c.id: c.bank_id for c in source_manifest.conversations},
            retrieval_source={"path": str(source / "manifest.json"), "sha256": h.file_sha(source / "manifest.json")},
            reader_profile=reader_profile,
            protocol="amb-locomo-cat1to4-reader-v2"
            if reader_profile != "amb-default"
            else "amb-locomo-cat1to4-packed-v1",
            packing=h.PackingSettings(max_tokens=1500, fact_tokens=0, chunk_tokens=1200).model_dump(),
        )
        path = tmp_path / "reader-config.json"
        path.write_text(json.dumps(cfg))
        directory = tmp_path / "reader-experiment"
        requests_before = len(service.requests)
        manifest = a.init_run(path, directory, "fresh_reader")
        assert len(service.requests) == requests_before
        assert not list((directory / "calls").glob("*.json")) and not list((directory / "results").glob("*.json"))
        assert not (directory / "summary.json").exists()
        assert manifest.retrieval_origin.run_id == source_manifest.run_id
        state = h.read_model(directory / "state.json", h.State)
        assert not state.banks and state.answer_elapsed_s == 0
        for p in (directory / "retrievals").glob("*.json"):
            record = a.unseal(p, a.RetrievalRecord, manifest)
            assert record.packing.included_fact_ids == [] and record.packing.tokens <= 1500
            assert "GOLD_SENTINEL" not in record.packing.text
        with pytest.raises(ValueError, match="ingest|read-only|reuse"):
            await a.service_stage(directory, manifest, "ingest")
        await a.service_stage(directory, manifest, "verify")
        factory = Factory(manifest, correct=True, answer="new independent answer")
        summary = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert summary.valid_complete_run and summary.correct == summary.completed == 2
        assert summary.retrieval_measurement == "reused-source-recall"
        assert summary.retrieval_source_run_id == source_manifest.run_id
        assert summary.model_usage["answer"].total_tokens == summary.model_usage["judge"].total_tokens == 20
        assert len(factory.calls) == 4 and all(method == "GET" for method, _ in service.requests[requests_before:])
        assert all("original source answer" not in prompt for _, prompt, _ in factory.calls)
        assert all("new independent answer" in prompt for judge, prompt, _ in factory.calls if judge)
        if reader_profile != "amb-default":
            assert all(
                prompt.startswith("# ADDITIONAL READER GUIDANCE") for judge, prompt, _ in factory.calls if not judge
            )
        requests_after = len(service.requests)
        second = await asyncio.to_thread(a.run, directory, manifest, factory)
        assert second.valid_complete_run and len(factory.calls) == 4
        assert all(method == "GET" for method, _ in service.requests[requests_after:])
        assert before == {str(p): h.file_sha(p) for p in source.rglob("*.json")}
        analysis = a.module_from_file("memory_retrieval_export_test", SCRIPT.with_name("analysis.py"))
        exported = analysis.export(directory, tmp_path / "reader-export.json", source)
        assert exported.changes.fixed == ["conv-30_q0", "conv-30_q1"]
        assert exported.settings.reader_profile == reader_profile
        assert exported.settings.retrieval_source.sha256 == h.file_sha(source / "manifest.json")
        # A later transport continuation retains historical-latency provenance.
        cfg = manifest.config.model_dump(mode="json")
        cfg.update(
            retrieval_source=None,
            checkpoint_source={
                "path": str(directory / "manifest.json"),
                "sha256": h.file_sha(directory / "manifest.json"),
            },
        )
        path.write_text(json.dumps(cfg))
        recovered = tmp_path / "reader-continuation"
        recovery = a.init_run(path, recovered, "continued_reader")
        assert recovery.retrieval_origin == manifest.retrieval_origin
        await a.service_stage(recovered, recovery, "verify")
        resumed_factory = Factory(recovery)
        resumed = await asyncio.to_thread(a.run, recovered, recovery, resumed_factory)
        assert resumed.valid_complete_run and resumed.retrieval_measurement == "reused-source-recall"
        assert resumed.retrieval_source_run_id == source_manifest.run_id
        assert not resumed_factory.calls
        # Missing borrowed evidence cannot silently become a newly timed recall.
        active_path = directory / "retrievals/conv-30_q0.json"
        active_bytes = active_path.read_bytes()
        active_path.unlink()
        with pytest.raises(ValueError, match="fallback is forbidden"):
            a.load_manifest(directory)
        assert not a.report(directory, manifest).valid_complete_run
        runtime = a.components(a.Archive(directory, manifest, factory))
        q = manifest.conversations[0].questions[0]
        token = a.QUESTION_ID.set("conv-30_q0")
        requests_before_missing = len(service.requests)
        try:
            with pytest.raises(ValueError, match="fallback is forbidden"):
                await runtime.memory.async_retrieve(
                    q.question, user_id=q.conversation_id, query_timestamp=manifest.conversations[0].reference_date
                )
        finally:
            a.QUESTION_ID.reset(token)
        assert len(service.requests) == requests_before_missing and len(factory.calls) == 4
        active_path.write_bytes(active_bytes)
        assert a.report(directory, manifest).valid_complete_run
        # Frozen cache proof must be checked on every load.
        copied = next((directory / "checkpoint-source/retrievals").glob("*.json"))
        copied.write_text(copied.read_text() + " ")
        with pytest.raises(ValueError, match="snapshot changed"):
            a.load_manifest(directory)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "incomplete",
        "unverified",
        "missing",
        "other-bank",
        "foreign-chunk",
        "verdict",
        "recall-settings",
        "both-modes",
        "new-banks",
    ],
)
async def test_retrieval_only_rejects_invalid_source_before_output(tmp_path, checkout, monkeypatch, mutation):
    service = FakeBankService()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", service.handle)
    async with TestServer(app) as server:
        monkeypatch.setenv("CONTEXTBASE_BENCH_KEY", "TEST_ONLY_SECRET")
        source, source_manifest = prepared(tmp_path, checkout, api_url=str(server.make_url("/")))
        await a.service_stage(source, source_manifest, "ingest")
        await asyncio.to_thread(a.run, source, source_manifest, Factory(source_manifest))
        cfg = source_manifest.config.model_dump(mode="json")
        cfg.update(
            reuse_banks={c.id: c.bank_id for c in source_manifest.conversations},
            retrieval_source={"path": str(source / "manifest.json"), "sha256": h.file_sha(source / "manifest.json")},
        )
        if mutation == "incomplete":
            (source / "summary.json").unlink()
        elif mutation == "unverified":
            state = h.read_model(source / "state.json", h.State)
            state.banks["conv-30"].verified = False
            h.save_model(source / "state.json", state)
        elif mutation == "missing":
            (source / "results/conv-30_q0.json").unlink()
        elif mutation == "other-bank":
            p = source / "retrievals/conv-30_q0.json"
            record = a.unseal(p, a.RetrievalRecord, source_manifest)
            record.bank_id = "foreign_bank"
            a.seal(p, record)
        elif mutation == "foreign-chunk":
            p = source / "retrievals/conv-30_q0.json"
            record = a.unseal(p, a.RetrievalRecord, source_manifest)
            doc = source_manifest.conversations[0].sessions[0].document_id
            record.recall.chunks = {build_chunk_id("foreign_bank", doc, 0): next(iter(record.recall.chunks.values()))}
            a.seal(p, record)
        elif mutation == "verdict":
            p = source / "results/conv-30_q0.json"
            record = a.unseal(p, a.SavedResult, source_manifest)
            record.amb_result.correct = True
            a.seal(p, record)
        elif mutation == "recall-settings":
            cfg["recall"]["max_tokens"] += 1
        elif mutation == "both-modes":
            cfg["checkpoint_source"] = cfg["retrieval_source"]
        else:
            cfg["reuse_banks"] = {}
        path = tmp_path / "invalid-reader.json"
        path.write_text(json.dumps(cfg))
        target = tmp_path / "must-not-exist"
        requests_before = len(service.requests)
        with pytest.raises(ValueError):
            a.init_run(path, target, "invalid_cache")
        assert not target.exists() and len(service.requests) == requests_before
