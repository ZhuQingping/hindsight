"""Background SQL must not be attributed to an unrelated in-flight HTTP recall."""

import asyncio
import importlib.util
import sys
from contextvars import ContextVar
from pathlib import Path
from types import SimpleNamespace

import pytest

FILE = Path(__file__).resolve().parents[2] / "benchmarks/memory/recall-pushdown/verify.py"
SPEC = importlib.util.spec_from_file_location("recall_verification_scope", FILE)
assert SPEC is not None and SPEC.loader is not None
VERIFY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VERIFY
SPEC.loader.exec_module(VERIFY)


def sample(question: str):
    return VERIFY.Sample(question_id=question, repeat=0, http_ms=0, status=0, claimed=False, sql=[])


def record():
    return SimpleNamespace(query="SELECT 1", elapsed=0.001, exception=None)


def test_database_target_is_snapshot_only_by_default(tmp_path):
    assert (
        VERIFY.validate_database_target(tmp_path / "pgdata", tmp_path, None, superuser=True, read_only=False)
        == "private snapshot"
    )
    with pytest.raises(RuntimeError, match="private PG snapshot"):
        VERIFY.validate_database_target(tmp_path / "existing", tmp_path, None, superuser=False, read_only=True)


@pytest.mark.parametrize("superuser,read_only", [(True, True), (False, False), (True, False)])
def test_existing_database_requires_read_only_non_superuser(tmp_path, superuser, read_only):
    with pytest.raises(RuntimeError, match="non-superuser read-only"):
        VERIFY.validate_database_target(
            tmp_path, tmp_path / "snapshot", tmp_path, superuser=superuser, read_only=read_only
        )


def test_existing_database_requires_exact_explicit_path(tmp_path):
    with pytest.raises(RuntimeError, match="does not match"):
        VERIFY.validate_database_target(
            tmp_path / "other", tmp_path / "snapshot", tmp_path, superuser=False, read_only=True
        )
    assert VERIFY.validate_database_target(
        tmp_path, tmp_path / "snapshot", tmp_path, superuser=False, read_only=True
    ).startswith("existing PG")


def test_background_query_has_no_request_owner():
    context = ContextVar("request", default=None)
    recorder = VERIFY.SQLRecorder(context)
    active_http_sample = sample("q0")
    recorder.observe(record())
    assert active_http_sample.sql == []
    assert recorder.outside_request == 1


@pytest.mark.asyncio
async def test_child_phase_is_visible_to_parent_response_task():
    context = ContextVar("request", default=None)
    recorder = VERIFY.SQLRecorder(context)
    scope = VERIFY.RequestSQLScope(sample("q0"))
    token = context.set(scope)
    try:

        async def core_recall():
            context.get().stage = "postprocess"

        await asyncio.create_task(core_recall())
        recorder.observe(record())
        assert scope.sample.sql[0].stage == "postprocess"
    finally:
        context.reset(token)


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_share_query_ownership():
    context = ContextVar("request", default=None)
    recorder = VERIFY.SQLRecorder(context)
    first, second = sample("q0"), sample("q1")

    async def request(value):
        token = context.set(VERIFY.RequestSQLScope(value, value.question_id))
        try:
            await asyncio.sleep(0)
            recorder.observe(record())
        finally:
            context.reset(token)

    await asyncio.gather(request(first), request(second))
    assert [r.stage for r in first.sql] == ["q0"]
    assert [r.stage for r in second.sql] == ["q1"]
    assert recorder.outside_request == 0
