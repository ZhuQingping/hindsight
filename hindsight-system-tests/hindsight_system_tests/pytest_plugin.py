"""Shared model stubs and per-test call guards for native and extension stories."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from hindsight_system_tests import LLMStub, Stubs, start_stub_server


@pytest.fixture(scope="session")
def stubs() -> Stubs:
    return Stubs()


@pytest.fixture(scope="session")
def stub_server(stubs: Stubs) -> Iterator[object]:
    server = start_stub_server(stubs)
    yield server
    server.stop()


@pytest.fixture
def llm(stubs: Stubs) -> LLMStub:
    """The chat-completions rulebook. Declare what the model says before acting."""
    return stubs.llm


@pytest.fixture(autouse=True)
def _reset_stubs(stubs: Stubs) -> Iterator[None]:
    stubs.reset()
    yield
    # A net, not the mechanism: ``async with llm.hold(...)`` releases inside the story,
    # which is what keeps a parked call from outliving the bank it belongs to. This
    # catches the story that never entered the block, or died before it — the stub
    # server and its rulebook are session-scoped, so one wedged request would
    # otherwise reach the next test.
    stubs.llm.release_all()


@pytest.fixture(autouse=True)
def _no_unstubbed_calls(stubs: Stubs, request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail a test that let a call through unscripted, or sent a malformed request.

    Both are silent-success hazards. An unmatched call means the test proved less
    than it claims; a rejected request means we sent something a real provider
    would have refused. Neither is allowed to be a warning.
    """
    yield

    if request.node.stash.get(_ALREADY_FAILED, False):
        return

    if stubs.llm.unmatched:
        suggestions = "\n".join(f"    {call.suggestion()}" for call in stubs.llm.unmatched)
        pytest.fail(
            f"{len(stubs.llm.unmatched)} LLM call(s) matched no stub rule. Add:\n{suggestions}",
            pytrace=False,
        )

    if stubs.rejected_requests:
        rejections = "\n".join(f"    {reason}" for reason in stubs.rejected_requests)
        pytest.fail(
            "The server sent request(s) the stub rejected as malformed — a real provider\n"
            f"would have returned 400 too:\n{rejections}",
            pytrace=False,
        )


_ALREADY_FAILED = pytest.StashKey[bool]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Iterator[None]:
    """Remember a failure, so the guards above don't bury the real error."""
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" and report.failed:
        item.stash[_ALREADY_FAILED] = True
