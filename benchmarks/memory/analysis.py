"""Offline, credential-free LoCoMo result exports and evidence coverage for every wrong answer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

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
    args = parser.parse_args()
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
