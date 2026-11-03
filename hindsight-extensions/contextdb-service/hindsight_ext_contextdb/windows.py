"""Native Windows adapter for the existing authenticated local deployment."""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import os
import signal
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import aiohttp
from dotenv import dotenv_values

from .environment import service_env
from .private_paths import private_file


def own_process_tree() -> int:
    """Kill descendants when this supervisor exits, including abrupt termination."""
    if sys.platform != "win32":
        raise RuntimeError("Windows process ownership requires Windows")

    # Assign this supervisor before it creates any children. This avoids the race
    # of assigning an already-running child which could have spawned descendants.
    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("process_time", ctypes.c_int64),
            ("job_time", ctypes.c_int64),
            ("flags", wintypes.DWORD),
            ("min_working_set", ctypes.c_size_t),
            ("max_working_set", ctypes.c_size_t),
            ("active_processes", wintypes.DWORD),
            ("affinity", ctypes.c_size_t),
            ("priority", wintypes.DWORD),
            ("scheduling", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "reads",
                "writes",
                "other",
                "read_bytes",
                "write_bytes",
                "other_bytes",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("basic", BasicLimits),
            ("io", IoCounters),
            ("process_memory", ctypes.c_size_t),
            ("job_memory", ctypes.c_size_t),
            ("peak_process_memory", ctypes.c_size_t),
            ("peak_job_memory", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    limits = ExtendedLimits()
    limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        kernel.CloseHandle(job)
        raise ctypes.WinError(ctypes.get_last_error())
    # The non-inheritable handle intentionally remains open for this process's
    # lifetime. Closing it here would also terminate this supervisor itself.
    return job


def serve_windows(command: list[str], environment: dict[str, str], *, stop_timeout: float = 40) -> int:
    if sys.platform != "win32":
        raise RuntimeError("Windows supervision requires Windows")
    process = subprocess.Popen(command, env=environment, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK)}
    try:
        while process.poll() is None and not stopping:
            time.sleep(0.1)
        if process.poll() is None:
            process.send_signal(signal.CTRL_BREAK_EVENT)
            try:
                process.wait(timeout=stop_timeout)
            except subprocess.TimeoutExpired:
                # Terminating the Job Object owner closes its handle and kills
                # the whole owned tree, without addressing unrelated processes.
                process.kill()
        return process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def load_environment(directory: Path, component: str) -> None:
    path = directory / ("ui.env" if component == "ui" else "api.env")
    private_file(path)
    values = dotenv_values(path, encoding="utf-8", interpolate=False)
    os.environ.update({key: value for key, value in values.items() if value is not None})
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"


async def wait_for_api(timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    url = service_env("CP_DATAPLANE_API_URL", "http://127.0.0.1:8888").rstrip("/") + "/health/ready"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1), trust_env=False) as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status == 200:
                        return
            except (aiohttp.ClientError, TimeoutError):
                pass
            await asyncio.sleep(0.2)
    raise ValueError("API readiness timed out; UI was not started")


def combined() -> int:
    if sys.platform != "win32":
        raise RuntimeError("Windows supervision requires Windows")
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGBREAK):
        signal.signal(sig, stop)
    children: list[subprocess.Popen[bytes]] = []
    try:
        for component in ("api", "ui"):
            children.append(
                subprocess.Popen(
                    [sys.executable, "-m", "hindsight_ext_contextdb.windows", component],
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            )
        while not stopping and all(child.poll() is None for child in children):
            time.sleep(0.1)
        return 0 if stopping else 1
    finally:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.CTRL_BREAK_EVENT)
        deadline = time.monotonic() + 30
        while any(child.poll() is None for child in children) and time.monotonic() < deadline:
            time.sleep(0.1)
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["init", "api", "ui", "all"])
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Use the existing service.sh entrypoint on POSIX hosts")
    own_process_tree()
    directory = Path(os.environ["CONTEXTDB_DEPLOY_DIR"])
    root = Path(__file__).resolve().parents[3]
    if args.component == "all":
        return combined()
    load_environment(directory, args.component)
    if args.component == "ui":
        asyncio.run(wait_for_api())
    else:
        from .preflight import preflight

        report = asyncio.run(preflight(source_root=root))
        if not report.passed:
            raise ValueError("Local API preflight failed; check database extensions and matching dependencies")
        if args.component == "init":
            from .__main__ import migrate
            from .bootstrap import load_deployment_secrets

            load_deployment_secrets(directory, "api")
            asyncio.run(migrate(directory / "admin-key.json"))
            return 0
    from .launch import launch

    launch(args.component, directory, root)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise SystemExit(
            "Windows local startup failed; check private state, database and runtime dependencies"
        ) from None
