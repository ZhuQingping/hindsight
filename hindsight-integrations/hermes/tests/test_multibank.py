"""Tests for explicitly configured additional Banks."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import contextbase_hermes as plugin
import pytest

ContextBaseMemoryProvider = plugin.ContextBaseMemoryProvider


@pytest.fixture(autouse=True)
def _pin_update_mode_probe(monkeypatch):
    from conftest import SECRETS

    monkeypatch.setitem(SECRETS, "CONTEXTBASE_API_URL", "https://api.example.com")
    # The /version probe is a live HTTP call; pin the capability, as conftest's provider fixture does.
    monkeypatch.setattr(plugin, "_check_api_supports_update_mode_append", lambda *a, **k: True)


def _fake_recall(provider, answers: dict, queried: list | None = None) -> None:
    """Route the provider's recall to *answers*: bank id -> list of texts, or an
    exception to raise for that bank. Runs the real async operation."""

    class _Client:
        async def arecall(self, bank_id, **kwargs):
            if queried is not None:
                queried.append(bank_id)
            answer = answers.get(bank_id, [])
            if isinstance(answer, Exception):
                raise answer
            return SimpleNamespace(results=[SimpleNamespace(text=t) for t in answer])

    provider._run_contextbase_operation = lambda op: asyncio.run(op(_Client()))


def test_provider_recall_dedupes_across_banks():
    provider = ContextBaseMemoryProvider()
    provider._bank_id = "primary"
    provider._write_bank_ids = ["primary", "secondary"]
    _fake_recall(provider, {"primary": ["Fact 1", "Fact 2"], "secondary": ["Fact 2", "Fact 3"]})

    results = provider._recall("test query")
    texts = [r.text for r in results]
    assert texts == ["Fact 1", "Fact 2", "Fact 3"]


def test_provider_sync_turn_retains_to_all_write_banks():
    provider = ContextBaseMemoryProvider()
    provider._bank_id = "b1"
    provider._write_bank_ids = ["b1", "b2"]
    retained_banks = []

    def mock_retain_batch(item, bank_id, **kwargs):
        retained_banks.append(bank_id)
        return SimpleNamespace(operation_id=f"op-{bank_id}")

    provider._retain_batch = mock_retain_batch
    provider._ensure_writer = MagicMock()
    provider._register_atexit = MagicMock()

    # Enqueue a turn
    provider.sync_turn("User message", "Assistant reply", session_id="s1")

    # Drain queue
    job = provider._retain_queue.get_nowait()
    job()

    assert retained_banks == ["b1", "b2"]
    assert provider._pending_retain_ops == {("b1", "op-b1"), ("b2", "op-b2")}


def _provider_with(cfg: dict) -> ContextBaseMemoryProvider:
    provider = ContextBaseMemoryProvider()
    provider._config = {"bank_id": cfg.get("bank_id", "hermes")}
    provider._apply_connection_settings(cfg)
    return provider


def test_recall_only_banks_are_recalled_after_the_write_set_and_never_written():
    provider = _provider_with(
        {
            "bank_id": "primary",
            "additional_banks": ["shared"],
            "recall_additional_banks": ["vault"],
        }
    )
    assert provider._write_bank_ids == ["primary", "shared"]
    assert provider._build_recall_bank_ids() == ["primary", "shared", "vault"]


def test_recall_only_banks_accept_the_camel_case_alias():
    provider = _provider_with({"bank_id": "primary", "recallAdditionalBanks": ["vault"]})
    assert provider._write_bank_ids == ["primary"]
    assert provider._build_recall_bank_ids() == ["primary", "vault"]


def test_bank_in_both_lists_stays_writable_and_is_recalled_once():
    provider = _provider_with(
        {
            "bank_id": "primary",
            "additional_banks": ["shared"],
            "recall_additional_banks": ["shared", "vault", " "],
        }
    )
    assert provider._write_bank_ids == ["primary", "shared"]
    assert provider._build_recall_bank_ids() == ["primary", "shared", "vault"]


def test_recall_queries_recall_only_banks_last():
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["vault"]})
    queried = []
    _fake_recall(provider, {"primary": ["fact from primary"], "vault": ["fact from vault"]}, queried)
    texts = [r.text for r in provider._recall("query")]
    assert queried == ["primary", "vault"]
    assert texts == ["fact from primary", "fact from vault"]


def test_sync_turn_never_retains_to_recall_only_banks():
    provider = _provider_with(
        {
            "bank_id": "primary",
            "additional_banks": ["shared"],
            "recall_additional_banks": ["vault"],
        }
    )
    retained_banks = []

    def mock_retain_batch(item, bank_id, **kwargs):
        retained_banks.append(bank_id)
        return SimpleNamespace(operation_id=f"op-{bank_id}")

    provider._retain_batch = mock_retain_batch
    provider._ensure_writer = MagicMock()
    provider._register_atexit = MagicMock()

    provider.sync_turn("User message", "Assistant reply", session_id="s1")
    provider._retain_queue.get_nowait()()

    assert retained_banks == ["primary", "shared"]


def test_bank_lists_accept_comma_separated_text_from_the_settings_panel():
    provider = _provider_with(
        {
            "bank_id": "primary",
            "additional_banks": "shared, team",
            "recall_additional_banks": "vault,notes",
        }
    )
    assert provider._write_bank_ids == ["primary", "shared", "team"]
    assert provider._build_recall_bank_ids() == ["primary", "shared", "team", "vault", "notes"]


def test_bank_lists_accept_a_json_encoded_list():
    provider = _provider_with({"bank_id": "primary", "additional_banks": '["shared", "team"]'})
    assert provider._write_bank_ids == ["primary", "shared", "team"]


def test_empty_bank_list_text_means_no_extra_banks():
    provider = _provider_with({"bank_id": "primary", "additional_banks": "", "recall_additional_banks": " , "})
    assert provider._write_bank_ids == ["primary"]
    assert provider._build_recall_bank_ids() == ["primary"]


def test_recall_skips_a_failing_extra_bank_with_a_warning(caplog):
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["vault", "notes"]})
    _fake_recall(provider, {"primary": ["from primary"], "vault": RuntimeError("vault down"), "notes": ["from notes"]})

    with caplog.at_level(logging.WARNING):
        texts = [r.text for r in provider._recall("query")]

    assert texts == ["from primary", "from notes"]
    assert "skipping bank vault" in caplog.text


def test_recall_raises_when_the_primary_bank_fails():
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["vault"]})
    _fake_recall(provider, {"primary": RuntimeError("401 Unauthorized"), "vault": ["from vault"]})

    with pytest.raises(RuntimeError, match="401"):
        provider._recall("query")


def test_single_bank_recall_error_reaches_the_tool_as_a_failure():
    provider = _provider_with({"bank_id": "primary"})
    _fake_recall(provider, {"primary": RuntimeError("connection refused")})

    result = provider.handle_tool_call("contextbase_recall", {"query": "q"})
    assert "Failed to search memory: connection refused" in result
    assert "No relevant memories found" not in result


def _fake_retain(provider, failing: set) -> list:
    """Record retained banks; raise for banks in *failing*."""
    written = []

    def retain_batch(item, bank_id, **kwargs):
        written.append(bank_id)
        if bank_id in failing:
            raise RuntimeError(f"{bank_id} unavailable")
        return SimpleNamespace(operation_id=f"op-{bank_id}")

    provider._retain_batch = retain_batch
    provider._ensure_writer = MagicMock()
    provider._register_atexit = MagicMock()
    return written


def test_turn_retain_continues_past_a_failing_extra_bank(caplog):
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["broken", "shared"]})
    written = _fake_retain(provider, failing={"broken"})

    provider.sync_turn("User message", "Assistant reply", session_id="s1")
    with caplog.at_level(logging.WARNING):
        provider._retain_queue.get_nowait()()

    assert written == ["primary", "broken", "shared"]
    assert "skipping bank broken" in caplog.text


def test_turn_retain_raises_when_the_primary_fails_before_touching_extra_banks():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["shared"]})
    written = _fake_retain(provider, failing={"primary"})

    provider.sync_turn("User message", "Assistant reply", session_id="s1")
    with pytest.raises(RuntimeError, match="primary unavailable"):
        provider._retain_queue.get_nowait()()
    assert written == ["primary"]


def test_retain_tool_reports_success_when_only_an_extra_bank_fails():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["broken"]})
    written = _fake_retain(provider, failing={"broken"})

    result = provider.handle_tool_call("contextbase_retain", {"content": "a fact"})

    assert written == ["primary", "broken"]
    assert "Memory queued for storage" in result  # retain_async defaults on


def test_retain_tool_reports_failure_when_the_primary_fails():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["shared"]})
    written = _fake_retain(provider, failing={"primary"})

    result = provider.handle_tool_call("contextbase_retain", {"content": "a fact"})

    assert written == ["primary"]
    assert "Failed to store memory: primary unavailable" in result


def test_a_hung_extra_bank_cannot_cost_the_primary_its_results():
    """Runs through the real _run_sync deadline, so it fails if the extra bank's own
    deadline were ever allowed past the operation's."""
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["slow"]})
    provider._timeout = 5

    class _Client:
        async def arecall(self, bank_id, **kwargs):
            if bank_id == "slow":
                await asyncio.sleep(30)
            return SimpleNamespace(results=[SimpleNamespace(text=f"from {bank_id}")])

    provider._get_client = lambda: _Client()
    assert [r.text for r in provider._recall("q")] == ["from primary"]


def test_a_failing_extra_bank_is_skipped_for_the_cooldown_and_warns_once(caplog):
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["vault"]})
    answers = {"primary": ["from primary"], "vault": RuntimeError("vault down")}
    queried = []
    _fake_recall(provider, answers, queried)

    with caplog.at_level(logging.DEBUG):
        provider._recall("q")
        provider._recall("q")
    assert queried == ["primary", "vault", "primary"]
    assert [r.levelno for r in caplog.records if "skipping bank vault" in r.getMessage()] == [logging.WARNING]

    # Cooldown over and the bank answers again: it is queried and the outage ends.
    provider._extra_bank_down_until[("recall", "vault")] = 0.0
    answers["vault"] = ["from vault"]
    with caplog.at_level(logging.INFO):
        texts = [r.text for r in provider._recall("q")]
    assert texts == ["from primary", "from vault"]
    assert ("recall", "vault") not in provider._extra_bank_down_until
    assert "bank vault is answering again" in caplog.text


def test_writes_skip_an_extra_bank_while_it_cools_down():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["broken", "shared"]})
    written = _fake_retain(provider, failing={"broken"})

    provider.handle_tool_call("contextbase_retain", {"content": "one"})
    provider.handle_tool_call("contextbase_retain", {"content": "two"})

    assert written == ["primary", "broken", "shared", "primary", "shared"]


def test_a_failed_recall_does_not_stop_writes_to_the_same_bank():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["team"]})
    _fake_recall(provider, {"primary": ["from primary"], "team": RuntimeError("slow search")})
    provider._recall("q")
    written = _fake_retain(provider, failing=set())

    provider.handle_tool_call("contextbase_retain", {"content": "a fact"})

    assert written == ["primary", "team"]


def test_single_bank_recall_returns_the_server_response_unchanged():
    provider = _provider_with({"bank_id": "primary"})
    results = [SimpleNamespace(text="same"), SimpleNamespace(text="same"), SimpleNamespace(text=None)]

    class _Client:
        async def arecall(self, bank_id, **kwargs):
            return SimpleNamespace(results=results)

    provider._run_contextbase_operation = lambda op: asyncio.run(op(_Client()))
    assert provider._recall("q") == results


def _not_found() -> Exception:
    from contextbase_client_api.exceptions import NotFoundException

    return NotFoundException(status=404, reason="Not Found")


def test_an_extra_bank_nothing_was_retained_to_is_empty_not_down(caplog):
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["fresh"]})
    _fake_recall(provider, {"primary": ["from primary"], "fresh": _not_found()})

    with caplog.at_level(logging.WARNING):
        texts = [r.text for r in provider._recall("query")]

    assert texts == ["from primary"]
    assert "skipping bank fresh" not in caplog.text
    assert provider._extra_bank_available("recall", "fresh")


def test_a_primary_bank_nothing_was_retained_to_still_returns_the_extra_banks():
    provider = _provider_with({"bank_id": "fresh", "recall_additional_banks": ["vault"]})
    _fake_recall(provider, {"fresh": _not_found(), "vault": ["from vault"]})

    assert [r.text for r in provider._recall("query")] == ["from vault"]


def test_score_floors_apply_to_every_recall_bank():
    provider = _provider_with({"bank_id": "primary", "recall_additional_banks": ["vault"]})
    provider._recall_min_scores = {"semantic": 0.5}
    sent = []

    class _Client:
        async def arecall(self, bank_id, **kwargs):
            sent.append(kwargs.get("min_scores"))
            scores = {"primary": [("p-strong", 0.9), ("p-weak", 0.1)], "vault": [("v-strong", 0.8), ("v-weak", 0.2)]}
            return SimpleNamespace(
                results=[SimpleNamespace(text=t, scores=SimpleNamespace(semantic=s)) for t, s in scores[bank_id]]
            )

    provider._run_contextbase_operation = lambda op: asyncio.run(op(_Client()))

    assert [r.text for r in provider._recall("query")] == ["p-strong", "v-strong"]
    assert sent == [{"semantic": 0.5}] * 2


def test_builtin_memory_writes_reach_every_write_bank():
    provider = _provider_with({"bank_id": "primary", "additional_banks": ["shared"], "recall_additional_banks": ["ro"]})
    written = _fake_retain(provider, failing=set())

    provider.on_memory_write("add", "memory", "Deploys go through Fly.io")
    provider._retain_queue.get_nowait()()

    assert written == ["primary", "shared"]
