"""Supervise a frozen overnight baseline without changing its evaluation policy or overwriting evidence."""

from __future__ import annotations

import argparse
import fcntl
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

spec = importlib.util.spec_from_file_location("_night_memory_analysis", Path(__file__).with_name("analysis.py"))
if spec is None or spec.loader is None:
    raise RuntimeError("Missing analysis/export helpers")
a = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = a
spec.loader.exec_module(a)


class WatchState(BaseModel):
    run_id: str
    run_dir: str
    supervisor_pid: int
    original_pid: int | None = None
    child_pid: int | None = None
    stage: Literal["monitoring", "ingest", "run", "export", "completed", "needs_attention"] = "monitoring"
    last_update: str
    attempts: dict[str, int] = Field(default_factory=dict)
    exit_codes: dict[str, int] = Field(default_factory=dict)
    error_type: str | None = None


def next_stage(
    state: a.h.core.State, summary: a.h.Summary | None, expected_banks: int
) -> Literal["ingest", "run", "export", "needs_attention"]:
    if summary and summary.valid_complete_run:
        if state.status != "completed" or summary.failed or summary.pending:
            raise ValueError("Summary and state disagree")
        return "export"
    if state.status == "completed":
        return "needs_attention"
    if state.status == "interrupted_or_failed":
        return "needs_attention"
    if len(state.banks) != expected_banks or not all(b.verified for b in state.banks.values()):
        return "ingest"
    return "run"


def owner_alive(pid: int | None, directory: Path) -> bool:
    if pid is None:
        return False
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False)
    # Validate process identity as well as PID, avoiding a stale reused PID.
    return result.returncode == 0 and (
        str(directory) in result.stdout or "contextbase-locomo-full-active-run" in result.stdout
    )


def locked(directory: Path) -> bool:
    with (directory / ".run.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
    return False


def run(directory: Path, output: Path, original_pid: int | None, poll_s: float) -> int:
    manifest = a.manifest_at(directory)
    if output.exists():
        raise FileExistsError("Use a fresh supervisor record; preserve prior attempts")
    record = WatchState(
        run_id=manifest.run_id,
        run_dir=str(directory.resolve()),
        supervisor_pid=os.getpid(),
        original_pid=original_pid,
        last_update=a.h.core.now(),
    )

    def save() -> None:
        record.last_update = a.h.core.now()
        a.h.core.save_model(output, record)

    save()
    try:
        while True:
            state = a.h.core.read_model(directory / "state.json", a.h.core.State)
            summary = (
                a.h.core.read_model(directory / "summary.json", a.h.Summary)
                if (directory / "summary.json").exists()
                else None
            )
            if owner_alive(original_pid, directory) or locked(directory):
                record.stage = "monitoring"
                save()
                time.sleep(poll_s)
                continue
            stage = next_stage(state, summary, len(manifest.conversations))
            if stage == "needs_attention":
                record.stage = "needs_attention"
                save()
                return 1
            if stage == "export":
                record.stage = "export"
                save()
                result_path = directory / "public-results.json"
                if result_path.exists():
                    exported = a.h.core.read_model(result_path, a.Export)
                    if exported.manifest_sha256 != a.h.core.file_sha(directory / "manifest.json"):
                        raise ValueError("An existing export belongs to another run")
                else:
                    a.export(directory, result_path)
                record.stage = "completed"
                save()
                return 0
            if record.attempts.get(stage, 0) >= 2:
                record.stage = "needs_attention"
                save()
                return 1
            # Another existing launcher may be between ingest and run. Give it a
            # grace period, then recheck ownership before attempting the CLI lock.
            time.sleep(min(poll_s, 10))
            if owner_alive(original_pid, directory) or locked(directory):
                continue
            record.stage = stage
            record.attempts[stage] = record.attempts.get(stage, 0) + 1
            log = directory / f"night-{stage}-{record.attempts[stage]}.log"
            with log.open("xb") as stream:
                child = subprocess.Popen(
                    [sys.executable, "-u", str(directory / "runner.py"), stage, str(directory)],
                    stdin=subprocess.DEVNULL,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                record.child_pid = child.pid
                save()
                while child.poll() is None:
                    time.sleep(poll_s)
                    save()
                record.exit_codes[stage] = child.returncode
                record.child_pid = None
            save()
            if child.returncode:
                record.stage = "needs_attention"
                save()
                return 1
    except Exception as error:
        # Exception text may include provider configuration. Keep its class only.
        record.stage = "needs_attention"
        record.error_type = type(error).__name__
        save()
        raise RuntimeError("Night supervisor stopped; inspect its preserved state and stage logs") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--original-pid", type=int)
    parser.add_argument("--poll-seconds", type=float, default=30)
    args = parser.parse_args()
    if args.poll_seconds < 1:
        parser.error("Poll interval must be at least one second")
    sys.exit(run(args.run_dir, args.record, args.original_pid, args.poll_seconds))


if __name__ == "__main__":
    main()
