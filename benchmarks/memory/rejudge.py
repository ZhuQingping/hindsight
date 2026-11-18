"""Rejudge fixed public answers with the baseline judge; no memory or answer-model calls."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

spec = importlib.util.spec_from_file_location("_public_rejudge_analysis", Path(__file__).with_name("analysis.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("Missing benchmark analysis helpers")
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a
spec.loader.exec_module(a)
h = a.h
PRODUCTS = ("mem0", "hindsight")


class Plan(BaseModel):
    kind: Literal["public-answer-rejudging"] = "public-answer-rejudging"
    run_id: str
    baseline_path: str
    baseline_manifest_sha256: str
    public_results_sha256: str
    question_scope_sha256: str
    expected_per_product: int
    judge: a.Model
    concurrency: int = Field(default=2, ge=1, le=8)
    child_manifest_hashes: dict[str, str]
    source_hashes: dict[str, str]
    fingerprint: str = ""
    note: str = (
        "Derived common-judge comparison of historical public answers, not new Mem0/Hindsight service runs. "
        "No ingestion, recall, new answers or modified judge prompts. Identical full prompts share a verdict; "
        "completed baseline verdicts are reused first. Models and original vendor scores remain separately labelled."
    )


class Verdict(h.Sealed):
    product: str
    question_id: str
    prompt_sha256: str
    answer_sha256: str
    correct: bool
    reason: str
    call_path: str
    call_sha256: str
    origin: Literal["baseline", "rejudge"]


class CachedVerdict(BaseModel):
    parsed: h.JudgeData
    path: str
    sha256: str
    origin: Literal["baseline", "rejudge"]


class CallSource(BaseModel):
    directory: Path
    manifest: h.Manifest
    origin: Literal["baseline", "rejudge"]


class ProductScore(BaseModel):
    expected: int
    completed: int
    correct: int
    accuracy_all_expected: float


class Summary(BaseModel):
    kind: Literal["public-answer-rejudging"] = "public-answer-rejudging"
    plan_fingerprint: str
    valid_complete_comparison: bool
    products: dict[str, ProductScore]
    baseline_reused_rows: int
    newly_generated_unique_prompts: int
    model_usage: h.TokenUsage
    attempts_without_usage: int
    note: str = "Derived common-judge scores, not vendor-published scores or memory retrieval measurements."


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def prepare(source: Path, public_path: Path, output: Path, run_id: str) -> Plan:
    manifest = a.manifest_at(source)
    public = a.PublicComparison.model_validate_json(public_path.read_bytes())
    qids = {h.amb_id(q) for c in manifest.conversations for q in c.questions}
    if (
        public.question_scope_sha256 != manifest.question_scope_sha256
        or len(public.rows) != len(qids)
        or {r.question_id for r in public.rows} != qids
    ):
        raise ValueError("Public answers and baseline scope differ")
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "source"
    frozen.mkdir()
    names = ["rejudge.py", "analysis.py", "runner.py", "support.py"]
    for name in names:
        shutil.copyfile(Path(__file__).with_name(name), frozen / name)
    shutil.copyfile(public_path, output / "public-results.json")
    cfg = manifest.config.model_copy(deep=True)
    cfg.reuse_banks = {c.id: c.bank_id for c in manifest.conversations}
    cfg.checkpoint_source = None
    cfg.resume_connection_failures = False
    h.core.save_model(output / "configuration-template.json", cfg)
    children: dict[str, str] = {}
    for product in PRODUCTS:
        child = output / product
        generated = h.init_run(output / "configuration-template.json", child, run_id + "_" + product)
        if generated.question_scope_sha256 != manifest.question_scope_sha256:
            raise ValueError("Rejudge scope changed during initialization")
        if generated.client_source_sha256 != manifest.client_source_sha256 or generated.amb_files != manifest.amb_files:
            raise ValueError("Judge SDK or AMB source differs from the baseline")
        children[product] = h.core.file_sha(child / "manifest.json")
        (output / "verdicts" / product).mkdir(parents=True)
    plan = Plan(
        run_id=run_id,
        baseline_path=str(source.resolve()),
        baseline_manifest_sha256=h.core.file_sha(source / "manifest.json"),
        public_results_sha256=h.core.file_sha(public_path),
        question_scope_sha256=manifest.question_scope_sha256,
        expected_per_product=len(qids),
        judge=a.Model.model_validate(cfg.judge.model_dump()),
        concurrency=cfg.concurrency,
        child_manifest_hashes=children,
        source_hashes={name: h.core.file_sha(frozen / name) for name in names},
    )
    plan.fingerprint = h.core.canonical_sha(plan.model_copy(update={"fingerprint": ""}))
    h.core.save_model(output / "plan.json", plan)
    return plan


def load_plan(directory: Path) -> Plan:
    plan = h.core.read_model(directory / "plan.json", Plan)
    if plan.fingerprint != h.core.canonical_sha(plan.model_copy(update={"fingerprint": ""})):
        raise ValueError("Rejudge plan modified")
    for name, expected in plan.source_hashes.items():
        if h.core.file_sha(directory / "source" / name) != expected:
            raise ValueError("Frozen rejudge source modified")
        if h.core.file_sha(Path(__file__).with_name(name)) != expected:
            raise ValueError("Use the frozen source/rejudge.py for this plan")
    if h.core.file_sha(directory / "public-results.json") != plan.public_results_sha256:
        raise ValueError("Public answers modified")
    if h.core.file_sha(Path(plan.baseline_path) / "manifest.json") != plan.baseline_manifest_sha256:
        raise ValueError("Baseline manifest modified")
    for product, expected in plan.child_manifest_hashes.items():
        if h.core.file_sha(directory / product / "manifest.json") != expected:
            raise ValueError("Child manifest modified")
    return plan


def read_verdict(path: Path, plan: Plan) -> Verdict:
    result = h.core.read_model(path, Verdict)
    if result.fingerprint != plan.fingerprint or result.checksum != h.core.canonical_sha(
        result.model_copy(update={"checksum": ""})
    ):
        raise ValueError("Rejudge verdict modified")
    if h.core.file_sha(Path(result.call_path)) != result.call_sha256:
        raise ValueError("Reused judge call modified")
    call = h.core.read_model(Path(result.call_path), h.CallRecord)
    parsed = h.JudgeData.model_validate(call.parsed)
    if (
        call.checksum != h.core.canonical_sha(call.model_copy(update={"checksum": ""}))
        or call.stage != "judge"
        or call.status != "completed"
        or digest(call.prompt) != result.prompt_sha256
        or parsed.correct != result.correct
        or parsed.reason != result.reason
    ):
        raise ValueError("Verdict disagrees with its recorded judge call")
    return result


async def run(directory: Path, factory: Any = None) -> Summary:
    plan = load_plan(directory)
    source = Path(plan.baseline_path)
    baseline = a.manifest_at(source)
    if not (source / "summary.json").exists():
        raise ValueError("A complete source baseline is required before rejudging")
    a.completed(source)  # Never compete with the still-running baseline.
    public = a.PublicComparison.model_validate_json((directory / "public-results.json").read_bytes())
    cache: dict[str, CachedVerdict] = {}
    archives: dict[str, Any] = {}
    modules: dict[str, Any] = {}
    manifests: dict[str, Any] = {}
    for product in PRODUCTS:
        child = directory / product
        manifest = h.load_manifest(child)
        if manifest.config.judge != baseline.config.judge:
            raise ValueError("Judge settings differ from the baseline")
        manifests[product] = manifest
        archives[product] = h.Archive(child, manifest, factory or h.core.make_provider)
        modules[product] = h.amb_modules(child)
    # Whole-prompt identity includes query, full gold and generated answer. Cache
    # priority is fixed, never selected by whether a prior verdict was favourable.
    call_sources = [
        CallSource(directory=source, manifest=baseline, origin="baseline"),
        *[CallSource(directory=directory / p, manifest=manifests[p], origin="rejudge") for p in PRODUCTS],
    ]
    for call_source in call_sources:
        for path in sorted((call_source.directory / "calls").glob("*-judge.json")):
            record = h.unseal(path, h.CallRecord, call_source.manifest)
            if record.status == "completed":
                cache.setdefault(
                    digest(record.prompt),
                    CachedVerdict(
                        parsed=h.JudgeData.model_validate(record.parsed),
                        path=str(path.resolve()),
                        sha256=h.core.file_sha(path),
                        origin=call_source.origin,
                    ),
                )
    pending: dict[str, asyncio.Task[CachedVerdict]] = {}
    semaphore = asyncio.Semaphore(plan.concurrency)

    async def generate(product: str, qid: str, prompt: str) -> CachedVerdict:
        async with semaphore:
            value = await archives[product].generate(qid, "judge", prompt, modules[product]["judge"]._SCHEMA)
        path = archives[product].call_path(qid, "judge")
        return CachedVerdict(
            parsed=h.JudgeData.model_validate(value),
            path=str(path.resolve()),
            sha256=h.core.file_sha(path),
            origin="rejudge",
        )

    async def one(product: str, row: Any) -> None:
        answer = getattr(row, product).answer
        question = archives[product].questions[row.question_id]
        full_gold = str(archives[product].scoring.gold[question.conversation_id][question.original_index].answer)
        dataset = modules[product]["dataset.locomo"].LoComoDataset()
        prompt = dataset.build_judge_prompt(question.question, [full_gold], answer)
        key = digest(prompt)
        path = directory / "verdicts" / product / (row.question_id + ".json")
        if path.exists():
            result = read_verdict(path, plan)
            if (
                result.product != product
                or result.question_id != row.question_id
                or result.prompt_sha256 != key
                or result.answer_sha256 != digest(answer)
            ):
                raise ValueError("Saved public answer/verdict identity changed")
            return
        if key not in cache:
            if key not in pending:
                pending[key] = asyncio.create_task(generate(product, row.question_id, prompt))
            cache[key] = await pending[key]
        value = cache[key]
        h.seal(
            path,
            Verdict(
                fingerprint=plan.fingerprint,
                product=product,
                question_id=row.question_id,
                prompt_sha256=key,
                answer_sha256=digest(answer),
                correct=value.parsed.correct,
                reason=value.parsed.reason,
                call_path=value.path,
                call_sha256=value.sha256,
                origin=value.origin,
            ),
        )

    tasks = [asyncio.create_task(one(product, row)) for row in public.rows for product in PRODUCTS]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in [*tasks, *pending.values()]:
            task.cancel()
        await asyncio.gather(*tasks, *pending.values(), return_exceptions=True)
        raise
    rows = [read_verdict(p, plan) for product in PRODUCTS for p in (directory / "verdicts" / product).glob("*.json")]
    if len(rows) != len(public.rows) * len(PRODUCTS) or {(r.product, r.question_id) for r in rows} != {
        (p, r.question_id) for p in PRODUCTS for r in public.rows
    }:
        raise ValueError("Rejudge verdict scope mismatch")
    usage = h.TokenUsage()
    unknown = calls = 0
    for product in PRODUCTS:
        for path in (directory / product / "calls").glob("*.json"):
            call = h.unseal(path, h.CallRecord, manifests[product])
            if call.stage != "judge" or call.status != "completed":
                raise ValueError("Invalid rejudge-only call checkpoint")
            calls += 1
            for attempt in call.attempts:
                if attempt.usage is not None:
                    usage += attempt.usage
                else:
                    unknown += 1
    products = {
        product: ProductScore(
            expected=plan.expected_per_product,
            completed=sum(r.product == product for r in rows),
            correct=sum(r.product == product and r.correct for r in rows),
            accuracy_all_expected=sum(r.product == product and r.correct for r in rows) / plan.expected_per_product,
        )
        for product in PRODUCTS
    }
    summary = Summary(
        plan_fingerprint=plan.fingerprint,
        valid_complete_comparison=all(v.completed == v.expected for v in products.values()),
        products=products,
        baseline_reused_rows=sum(r.origin == "baseline" for r in rows),
        newly_generated_unique_prompts=calls,
        model_usage=usage,
        attempts_without_usage=unknown,
    )
    h.core.save_model(directory / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("prepare")
    init.add_argument("--source", type=Path, required=True)
    init.add_argument("--public-results", type=Path, required=True)
    init.add_argument("--output", type=Path, required=True)
    init.add_argument("--run-id", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.source, args.public_results, args.output, args.run_id).model_dump_json())
    else:
        with h.core.run_lock(args.directory):
            print(asyncio.run(run(args.directory)).model_dump_json())


if __name__ == "__main__":
    main()
