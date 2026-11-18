"""Offline, credential-free LoCoMo result exports and evidence coverage for every wrong answer."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

spec = importlib.util.spec_from_file_location("_memory_analysis_runner", Path(__file__).with_name("runner.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("Cannot load benchmark schemas")
h = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = h
spec.loader.exec_module(h)


class Source(BaseModel):
    url: str | None
    sha256: str


class Model(BaseModel):
    provider: str
    model: str
    reasoning_effort: str | None
    temperature: float | None
    output_tokens_limit: int | None


class Settings(BaseModel):
    memory: h.core.MemoryProfile
    answer: Model
    judge: Model
    packing: h.core.PackingSettings
    recall: h.core.RecallSettings
    categories: list[int]
    concurrency: int
    model_max_attempts: int
    request_timeout_s: float
    protocol: str
    judge_protocol: str
    f1_protocol: str
    timestamp_policy: str


class Previous(BaseModel):
    correct: bool
    answer: str
    answer_f1: float
    judge_reason: str


class Row(BaseModel):
    question_id: str
    conversation_id: str
    category: int
    question: str
    gold: list[str]
    answer: str
    reasoning: str
    correct: bool
    judge_reason: str
    answer_f1: float
    context_tokens: int
    recall_ms: float
    fact_count: int
    included_facts: int
    returned_chunks: int
    included_chunks: int
    server_truncated_chunks: int
    evidence_ids: list[str]
    evidence_ids_in_returned_chunks: list[str]
    evidence_ids_in_packed_context: list[str]
    previous: Previous | None = None


class Changes(BaseModel):
    both_correct: int
    both_wrong: int
    fixed: list[str]
    regressed: list[str]


class Export(BaseModel):
    schema_version: int = 1
    run_id: str
    baseline_run_id: str | None = None
    manifest_sha256: str
    harness_sha256: str
    support_sha256: str
    question_scope_sha256: str
    dataset: Source
    scoring: Source
    amb_commit: str
    settings: Settings
    summary: h.Summary
    previous_summary: h.Summary | None = None
    changes: Changes | None = None
    error_counts: dict[str, int]
    wrong_question_ids: list[str]
    rows: list[Row]
    evidence_note: str = (
        "Evidence IDs are inspected only after scoring. ID presence is a diagnostic proxy, "
        "not proof of full supporting text or semantic entailment. No gold/evidence enters retrieval."
    )


class PublicAnswer(BaseModel):
    answer: str
    correct: bool
    status: str
    derived_answer_f1: float
    retrieval_ms: float
    context_tokens: int | None = None


class PublicRow(BaseModel):
    question_id: str
    conversation_id: str
    category: int
    mem0: PublicAnswer
    hindsight: PublicAnswer


class PublicMetrics(BaseModel):
    count: int
    correct: int
    errors: int
    accuracy: float
    derived_answer_f1: float
    derived_retrieval_p50_ms: float
    derived_retrieval_p95_ms: float
    context_tokens_mean: float | None


class PublicComparison(BaseModel):
    schema_version: int = 1
    question_scope_sha256: str
    mem0_source: Source
    hindsight_source: Source
    mem0_answer_model: str
    mem0_judge_model: str
    hindsight_answer_model: str
    hindsight_judge_model: str
    mem0_metrics: PublicMetrics
    hindsight_metrics: PublicMetrics
    rows: list[PublicRow]
    note: str = (
        "Pinned historical public snapshots, not the latest headline scores. Verdicts remain each vendor's own; "
        "models, judges and retrieval boundaries differ. F1 and latency percentiles are derived offline, "
        "not vendor-published metrics. No public answers enter ContextBase ingestion/retrieval/answering. "
        "Context tokens exclude answer/judge usage; missing Mem0 context tokens are unknown, not zero."
    )


class Mem0Cutoff(BaseModel):
    judgment: Literal["CORRECT", "WRONG", "ERROR"]
    generated_answer: str


class Mem0Row(BaseModel):
    question_id: str
    conversation_idx: int
    category: int
    question: str
    ground_truth_answer: str | int | float
    search_latency_ms: float
    cutoff_results: dict[str, Mem0Cutoff]


class Mem0Metadata(BaseModel):
    answerer_model: str
    judge_model: str
    total_questions: int


class Mem0Results(BaseModel):
    metadata: Mem0Metadata
    evaluations: list[Mem0Row]


class HindsightRow(BaseModel):
    query_id: str
    query: str
    answer: str
    gold_answers: list[str | int | float]
    correct: bool
    retrieve_time_ms: float
    context_tokens: int


class HindsightResults(BaseModel):
    answer_llm: str
    judge_llm: str
    total_queries: int
    correct: int
    results: list[HindsightRow]


def public_metrics(rows: list[PublicAnswer]) -> PublicMetrics:
    if not rows or any(r.retrieval_ms < 0 or not np.isfinite(r.retrieval_ms) for r in rows):
        raise ValueError("Missing or invalid public latency samples")
    tokens = [r.context_tokens for r in rows if r.context_tokens is not None]
    return PublicMetrics(
        count=len(rows),
        correct=sum(r.correct for r in rows),
        errors=sum(r.status == "ERROR" for r in rows),
        accuracy=sum(r.correct for r in rows) / len(rows),
        derived_answer_f1=sum(r.derived_answer_f1 for r in rows) / len(rows),
        derived_retrieval_p50_ms=float(np.percentile([r.retrieval_ms for r in rows], 50)),
        derived_retrieval_p95_ms=float(np.percentile([r.retrieval_ms for r in rows], 95)),
        context_tokens_mean=sum(tokens) / len(tokens) if len(tokens) == len(rows) else None,
    )


def public_rows(directory: Path, mem0: Mem0Results, hindsight: HindsightResults) -> list[PublicRow]:
    manifest = manifest_at(directory)
    raw = [
        h.core.RawConversation.model_validate(v) for v in json.loads((directory / "inputs/locomo10.json").read_text())
    ]
    scoring = h.core.FrozenScoring(directory)
    questions = {h.amb_id(q): q for c in manifest.conversations for q in c.questions}
    mapped: dict[str, Mem0Row] = {}
    for row in mem0.evaluations:
        match = re.fullmatch(r"conv(\d+)_q(\d+)", row.question_id)
        if match is None or int(match[1]) != row.conversation_idx or not 0 <= row.conversation_idx < len(raw):
            raise ValueError("Invalid Mem0 conversation/index mapping")
        conv = raw[row.conversation_idx]
        index = int(match[2])
        if not 0 <= index < len(conv.qa):
            raise ValueError("Invalid Mem0 question index")
        original = conv.qa[index]
        qid = f"{conv.sample_id}_q{index}"
        if (
            qid in mapped
            or original.question != row.question
            or original.category != row.category
            or str(original.answer) != str(row.ground_truth_answer)
        ):
            raise ValueError("Mem0 duplicate/question/category/gold mismatch")
        mapped[qid] = row
    hs = {r.query_id: r for r in hindsight.results}
    if (
        len(hs) != len(hindsight.results)
        or set(hs) != set(questions)
        or set(mapped) != set(questions)
        or mem0.metadata.total_questions != len(questions)
        or hindsight.total_queries != len(questions)
        or hindsight.correct != sum(r.correct for r in hindsight.results)
    ):
        raise ValueError("Public result scopes/counts disagree")
    result = []
    for qid, question in questions.items():
        m = mapped[qid]
        cut = m.cutoff_results["top_200"]
        s = hs[qid]
        # Canonical full gold (AMB uses this), not category-3 F1's first-answer convention.
        gold = str(scoring.gold[question.conversation_id][question.original_index].answer)
        if s.query != question.question or [str(v) for v in s.gold_answers] != [gold]:
            raise ValueError("Hindsight question/gold mismatch")
        result.append(
            PublicRow(
                question_id=qid,
                conversation_id=question.conversation_id,
                category=question.category,
                mem0=PublicAnswer(
                    answer=cut.generated_answer,
                    correct=cut.judgment == "CORRECT",
                    status=cut.judgment,
                    derived_answer_f1=scoring.f1(question, cut.generated_answer),
                    retrieval_ms=m.search_latency_ms,
                ),
                hindsight=PublicAnswer(
                    answer=s.answer,
                    correct=s.correct,
                    status="CORRECT" if s.correct else "WRONG",
                    derived_answer_f1=scoring.f1(question, s.answer),
                    retrieval_ms=s.retrieve_time_ms,
                    context_tokens=s.context_tokens,
                ),
            )
        )
    return result


def export_public(directory: Path, mem0_path: Path, hindsight_path: Path, output: Path) -> PublicComparison:
    if output.exists():
        raise FileExistsError("Preserve existing public comparison")
    # URLs identify these exact snapshots; another input must get its own versioned importer.
    if (
        h.core.file_sha(mem0_path) != "36338fa6c1ca38bcf9e3fc33a5cbc3b6e53bdc4bafaeeaee0947cf13b5527911"
        or h.core.file_sha(hindsight_path) != "2c70253b80555de105d19ceaca6cea3fd10a0ddee030623991f597bc8007dc1c"
    ):
        raise ValueError("Official snapshot bytes do not match pinned sources")
    mem0 = Mem0Results.model_validate_json(mem0_path.read_bytes())
    hindsight = HindsightResults.model_validate_json(gzip.decompress(hindsight_path.read_bytes()))
    rows = public_rows(directory, mem0, hindsight)
    result = PublicComparison(
        question_scope_sha256=manifest_at(directory).question_scope_sha256,
        mem0_source=Source(
            url="https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_results.json",
            sha256=h.core.file_sha(mem0_path),
        ),
        hindsight_source=Source(
            url="https://raw.githubusercontent.com/vectorize-io/agent-memory-benchmark/28b644bd4dd653c0207c7507280439390c829155/outputs/locomo/locomo-hindsight/rag/locomo10.json.gz",
            sha256=h.core.file_sha(hindsight_path),
        ),
        mem0_answer_model=mem0.metadata.answerer_model,
        mem0_judge_model=mem0.metadata.judge_model,
        hindsight_answer_model=hindsight.answer_llm,
        hindsight_judge_model=hindsight.judge_llm,
        mem0_metrics=public_metrics([r.mem0 for r in rows]),
        hindsight_metrics=public_metrics([r.hindsight for r in rows]),
        rows=rows,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    h.core.save_model(output, result)
    return result


def contains_id(text: str, identifier: str) -> bool:
    return re.search(r"(?<![\w:])" + re.escape(identifier) + r"(?!\d)", text) is not None


def manifest_at(directory: Path) -> h.Manifest:
    # Read historical schemas without importing/executing an archived implementation.
    # Do not require today's helper hashes to match an older transport-only version.
    path = directory / "manifest.json"
    raw = json.loads(path.read_text())
    fingerprint = raw["fingerprint"]
    raw["fingerprint"] = ""
    if hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != fingerprint:
        raise ValueError("Invalid manifest fingerprint")
    manifest = h.core.read_model(path, h.Manifest)
    for name, expected in [("runner.py", manifest.harness_sha256), ("support.py", manifest.core_sha256)]:
        if h.core.file_sha(directory / name) != expected:
            raise ValueError("Frozen source modified: " + name)
    for name, filename in h.core.SOURCE_FILES.items():
        if h.core.file_sha(directory / "inputs" / filename) != getattr(manifest.config.sources, name).sha256:
            raise ValueError("Frozen dataset/scoring changed")
    return manifest


def completed(directory: Path) -> h.Summary:
    summary = h.core.read_model(directory / "summary.json", h.Summary)
    if not summary.valid_complete_run or summary.failed or summary.pending:
        raise ValueError("Only complete valid runs may be exported as a baseline")
    return summary


def export(directory: Path, output: Path, baseline: Path | None = None) -> Export:
    if output.exists():
        raise FileExistsError("Preserve the existing exported baseline")
    manifest = manifest_at(directory)
    summary = completed(directory)
    if summary.fingerprint != manifest.fingerprint:
        raise ValueError("Summary belongs to another manifest")
    old_manifest = manifest_at(baseline) if baseline else None
    old_summary = completed(baseline) if baseline else None
    if old_manifest and (old_manifest.question_scope_sha256 != manifest.question_scope_sha256):
        raise ValueError("Paired comparison requires the exact same question scope")
    raw = [
        h.core.RawConversation.model_validate(v) for v in json.loads((directory / "inputs/locomo10.json").read_text())
    ]
    raw_by_id = {c.sample_id: c for c in raw}
    rows = []
    for conversation in manifest.conversations:
        for question in conversation.questions:
            qid = h.amb_id(question)
            saved = h.unseal(directory / f"results/{qid}.json", h.SavedResult, manifest)
            retrieved = h.unseal(directory / f"retrievals/{qid}.json", h.RetrievalRecord, manifest)
            if retrieved.error or retrieved.recall is None or retrieved.packing is None:
                raise ValueError("Invalid retrieval checkpoint")
            result = saved.amb_result
            packed = retrieved.packing
            json.loads(packed.text)
            if packed.tokens > manifest.config.packing.max_tokens:
                raise ValueError("Context exceeds its frozen budget")
            evidence = raw_by_id[conversation.id].qa[question.original_index].evidence
            chunks = retrieved.recall.chunks or {}
            text = "\n".join(chunk.text for chunk in chunks.values())
            previous = None
            if baseline is not None:
                old = h.unseal(baseline / f"results/{qid}.json", h.SavedResult, old_manifest)
                if old.amb_result.query != result.query or old.amb_result.gold_answers != result.gold_answers:
                    raise ValueError("Question/gold changed between paired runs")
                previous = Previous(
                    correct=old.amb_result.correct,
                    answer=old.amb_result.answer,
                    answer_f1=old.answer_f1,
                    judge_reason=old.amb_result.judge_reason,
                )
            rows.append(
                Row(
                    question_id=qid,
                    conversation_id=conversation.id,
                    category=question.category,
                    question=question.question,
                    gold=result.gold_answers,
                    answer=result.answer,
                    reasoning=result.reasoning,
                    correct=result.correct,
                    judge_reason=result.judge_reason,
                    answer_f1=saved.answer_f1,
                    context_tokens=packed.tokens,
                    recall_ms=retrieved.retrieval_elapsed_ms,
                    fact_count=len(retrieved.recall.results),
                    included_facts=len(packed.included_fact_ids),
                    returned_chunks=len(chunks),
                    included_chunks=len(packed.included_chunk_ids),
                    server_truncated_chunks=sum(bool((c.model_extra or {}).get("truncated")) for c in chunks.values()),
                    evidence_ids=evidence,
                    evidence_ids_in_returned_chunks=[e for e in evidence if contains_id(text, e)],
                    evidence_ids_in_packed_context=[e for e in evidence if contains_id(packed.text, e)],
                    previous=previous,
                )
            )
    if len(rows) != summary.expected or sum(r.correct for r in rows) != summary.correct:
        raise ValueError("Row counts/verdicts disagree with summary")
    errors: dict[str, int] = {}
    for path in (directory / "calls").glob("*.json"):
        call = h.unseal(path, h.CallRecord, manifest)
        for attempt in call.attempts:
            if attempt.error:
                errors[attempt.error] = errors.get(attempt.error, 0) + 1
    cfg = manifest.config
    result = Export(
        run_id=manifest.run_id,
        baseline_run_id=old_manifest.run_id if old_manifest else None,
        manifest_sha256=h.core.file_sha(directory / "manifest.json"),
        harness_sha256=manifest.harness_sha256,
        support_sha256=manifest.core_sha256,
        question_scope_sha256=manifest.question_scope_sha256,
        dataset=Source(url=cfg.sources.dataset.url, sha256=cfg.sources.dataset.sha256),
        scoring=Source(url=cfg.sources.scoring.url, sha256=cfg.sources.scoring.sha256),
        amb_commit=cfg.amb_commit,
        settings=Settings(
            memory=cfg.memory_profile,
            answer=Model.model_validate(cfg.answer.model_dump()),
            judge=Model.model_validate(cfg.judge.model_dump()),
            packing=cfg.packing,
            recall=cfg.recall,
            categories=list(cfg.categories),
            concurrency=cfg.concurrency,
            model_max_attempts=cfg.model_max_attempts,
            request_timeout_s=cfg.request_timeout_s,
            protocol=cfg.protocol,
            judge_protocol=cfg.judge_protocol,
            f1_protocol=cfg.f1_protocol,
            timestamp_policy=cfg.timestamp_policy,
        ),
        summary=summary,
        previous_summary=old_summary,
        error_counts=errors,
        wrong_question_ids=[r.question_id for r in rows if not r.correct],
        rows=rows,
    )
    if baseline:
        result.changes = Changes(
            both_correct=sum(r.previous is not None and r.previous.correct and r.correct for r in rows),
            both_wrong=sum(r.previous is not None and not r.previous.correct and not r.correct for r in rows),
            fixed=[r.question_id for r in rows if r.previous is not None and not r.previous.correct and r.correct],
            regressed=[r.question_id for r in rows if r.previous is not None and r.previous.correct and not r.correct],
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    h.core.save_model(output, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--official-mem0", type=Path)
    parser.add_argument("--official-hindsight", type=Path)
    args = parser.parse_args()
    if args.official_mem0 or args.official_hindsight:
        if not args.official_mem0 or not args.official_hindsight or args.baseline:
            parser.error("Public export requires both official sources and no --baseline")
        result_public = export_public(args.run_dir, args.official_mem0, args.official_hindsight, args.output)
        print(result_public.model_dump_json(exclude={"rows"}))
        return
    result = export(args.run_dir, args.output, args.baseline)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "completed": result.summary.completed,
                "correct": result.summary.correct,
                "wrong": len(result.wrong_question_ids),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
