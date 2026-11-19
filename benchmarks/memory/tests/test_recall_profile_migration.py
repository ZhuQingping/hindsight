"""Default isolation and historical-oracle checks for the production server selector."""

import hashlib
import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path

import pytest
from hindsight_api.engine.chunk_ids import build_chunk_id

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


server = load(
    "recall_profiles_server_test",
    ROOT.parents[1] / "hindsight-api-slim/hindsight_api/engine/recall_profiles/locomo.py",
)
client = load("recall_profiles_client_test", ROOT / "support.py")


def inputs(seed=0):
    rng = random.Random(seed)
    bank = "migration_bank"
    turns = [
        {
            "speaker": "A" if i % 2 else "B",
            "dia_id": f"D1:{i}",
            "text": rng.choice(["art seven years", "coffee pastries", "日本語 🍵", "unrelated"]),
            "blip_caption": "a painting" if i == 3 else None,
            "query": "IMAGE_QUERY_MUST_NOT_APPEAR",
        }
        for i in range(14)
    ]
    chunks = {
        build_chunk_id(bank, "session-1", i): {"text": json.dumps(turns[i * 4 : i * 4 + 6], ensure_ascii=False)}
        for i in range(3)
    }
    # Exercise clipped JSON without manufacturing incomplete messages.
    chunks[build_chunk_id(bank, "session-1", 3)] = {"text": json.dumps(turns)[1:-15]}
    reply = {
        "results": [{"id": "fact-1", "text": "A makes art.", "document_id": "session-1"}],
        "chunks": chunks,
        "trace": {"sentinel": "unchanged"},
    }
    session = {"document_id": "session-1", "timestamp": "2023-01-01T00:00:00+00:00"}
    context = {"bank_id": bank, "sessions": [session]}
    conversation = {
        "id": "conv",
        "bank_id": bank,
        "speaker_a": "A",
        "speaker_b": "B",
        "sessions": [{**session, "content": "NOT_READ_BY_PACKER"}],
        "questions": [],
        "reference_date": session["timestamp"],
        "message_count": 14,
    }
    return reply, context, conversation


def test_default_is_identity_passthrough_without_dates_query_or_tokenizer(monkeypatch):
    reply = server.RecallReply.model_validate(inputs()[0])
    before = reply.model_dump_json()
    monkeypatch.setattr(server.tiktoken, "get_encoding", lambda *_: pytest.fail("default invoked tokenizer"))
    assert server.apply_profile(reply) is reply
    assert server.apply_profile(reply, recall_profile="default", query="") is reply
    assert reply.model_dump_json() == before


@pytest.mark.parametrize("profile,error", [("beam", NotImplementedError), ("typo", ValueError)])
def test_reserved_and_unknown_profiles_fail_explicitly(profile, error):
    with pytest.raises(error):
        server.apply_profile(server.RecallReply(results=[]), recall_profile=profile)


@pytest.mark.parametrize("seed", range(12))
def test_complete_selection_matches_existing_client_including_order_and_budgets(seed):
    raw, context, conversation = inputs(seed)
    settings = {
        "algorithm": "query-turn-windows-v1",
        "chunk_order": "query_relevance",
        "max_tokens": 600,
        "fact_tokens": 180,
        "chunk_tokens": 400,
    }
    source = server.RecallReply.model_validate(raw)
    before = source.model_dump_json()
    expected = client.pack_context(
        client.RecallReply.model_validate(raw),
        client.Conversation.model_validate(conversation),
        client.PackingSettings.model_validate(settings),
        "How long art seven years?",
    )
    actual = server.apply_profile(
        source,
        recall_profile="locomo",
        query="How long art seven years?",
        context=server.SelectionContext.model_validate(context),
        settings=server.PackingSettings.model_validate(settings),
    )
    assert actual.model_dump() == expected.model_dump()
    assert actual.tokens <= 600 and actual.chunk_tokens <= 400
    assert "IMAGE_QUERY_MUST_NOT_APPEAR" not in actual.text
    assert source.model_dump_json() == before


def test_bank_document_scope_empty_query_and_duplicate_dates_are_rejected():
    raw, context, _ = inputs()
    reply = server.RecallReply.model_validate(raw)
    for invalid in [
        {**context, "bank_id": "other"},
        {**context, "sessions": []},
        {**context, "sessions": context["sessions"] * 2},
    ]:
        with pytest.raises(ValueError):
            server.apply_profile(
                reply, recall_profile="locomo", query="art", context=server.SelectionContext.model_validate(invalid)
            )
    with pytest.raises(ValueError):
        server.apply_profile(
            reply, recall_profile="locomo", query=" ", context=server.SelectionContext.model_validate(context)
        )
    with pytest.raises(ValueError):
        server.apply_profile(reply, recall_profile="locomo", query="art")


def test_empty_reply_and_no_complete_passage_fits():
    _, context, _ = inputs()
    ctx = server.SelectionContext.model_validate(context)
    result = server.apply_profile(server.RecallReply(results=[]), recall_profile="locomo", query="art", context=ctx)
    assert json.loads(result.text) == {"facts": [], "chunks": []}
    raw, _, _ = inputs()
    with pytest.raises(ValueError, match="No complete original passage"):
        server.apply_profile(
            server.RecallReply.model_validate(raw),
            recall_profile="locomo",
            query="art",
            context=ctx,
            settings=server.PackingSettings(
                algorithm="query-turn-windows-v1",
                chunk_order="query_relevance",
                max_tokens=40,
                fact_tokens=0,
                chunk_tokens=1,
            ),
        )


def test_full_recorded_client_replay():
    source = os.environ.get("RECALL_PROFILE_REPLAY_RUN_DIR")
    if not source:
        pytest.skip("Set RECALL_PROFILE_REPLAY_RUN_DIR for the private full1540 historical replay")
    directory = Path(source)
    manifest = json.loads((directory / "manifest.json").read_text())
    scope = [(conv, q) for conv in manifest["conversations"] for q in conv["questions"]]
    assert len(scope) == 1540
    settings = server.PackingSettings.model_validate(manifest["config"]["packing"])
    mismatches = []
    exact_context = exact_packing = 0
    records = []
    start = time.perf_counter()
    for index, (conv, question) in enumerate(scope, 1):
        # Manifest preparation uses padded IDs; sealed AMB files use the original
        # numeric question index. Verify the correspondence rather than skip files.
        assert int(question["id"].rsplit("_q", 1)[1]) == question["original_index"]
        qid = f"{conv['id']}_q{question['original_index']}"
        path = directory / "retrievals" / f"{qid}.json"
        result_path = directory / "results" / f"{qid}.json"
        recorded = json.loads(path.read_text())
        result = json.loads(result_path.read_text())["amb_result"]
        context = server.SelectionContext(
            bank_id=conv["bank_id"],
            sessions=[
                server.SessionMetadata(document_id=s["document_id"], timestamp=s["timestamp"]) for s in conv["sessions"]
            ],
        )
        actual = server.apply_profile(
            server.RecallReply.model_validate(recorded["recall"]),
            recall_profile="locomo",
            query=question["question"],
            context=context,
            settings=settings,
        )
        context_ok = actual.text == recorded["packing"]["text"] == result["context"]
        packing_ok = actual.model_dump() == recorded["packing"]
        exact_context += context_ok
        exact_packing += packing_ok
        if not context_ok or not packing_ok:
            mismatches.append(
                {
                    "question_id": qid,
                    "context_equal": context_ok,
                    "packing_equal": packing_ok,
                    "different_packing_fields": [
                        k for k, v in actual.model_dump().items() if v != recorded["packing"].get(k)
                    ],
                }
            )
        records.append(
            {
                "question_id": qid,
                "context_sha256": hashlib.sha256(actual.text.encode()).hexdigest(),
                "recall_record_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "result_record_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            }
        )
        if index % 100 == 0:
            print(f"replay {index}/1540 context={exact_context} packing={exact_packing}", flush=True)
    report = {
        "kind": "server-selector-historical-client-replay-not-live-http",
        "run_id": manifest["run_id"],
        "scope": len(scope),
        "exact_context": exact_context,
        "exact_packing": exact_packing,
        "mismatches": mismatches,
        "elapsed_seconds": time.perf_counter() - start,
        "server_selector_sha256": hashlib.sha256(
            (ROOT.parents[1] / "hindsight-api-slim/hindsight_api/engine/recall_profiles/locomo.py").read_bytes()
        ).hexdigest(),
        "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
        "records": records,
        "new_model_calls": 0,
        "new_recall_calls": 0,
    }
    output = ROOT / ".local/recall-profile-migration-20261120"
    output.mkdir(parents=True, exist_ok=True)
    (output / "historical-replay.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    assert not mismatches, mismatches[:10]
