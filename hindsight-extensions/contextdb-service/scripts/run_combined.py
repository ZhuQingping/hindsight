"""Supervise the API (with its worker) and UI as one container lifecycle."""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", type=Path)
    parser.add_argument("--stop-timeout", type=float, default=30)
    args = parser.parse_args()
    if args.stop_timeout <= 0:
        parser.error("stop-timeout must be positive")
    stopping = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    children: list[subprocess.Popen[bytes]] = []
    result = 0
    try:
        for role in ("api", "ui"):
            if stopping:
                break
            # Separate process groups include preflight/readiness subprocesses;
            # stop the entire group even if its original service has exited.
            children.append(subprocess.Popen(["bash", str(args.service), role], start_new_session=True))
        while not stopping:
            if any(child.poll() is not None for child in children):
                print("API or UI exited; stopping the combined service", flush=True)
                result = 1
                break
            time.sleep(0.2)
    finally:
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + args.stop_timeout
        while any(child.poll() is None for child in children) and time.monotonic() < deadline:
            time.sleep(0.1)
        # Also kill descendants whose service leader has already exited.
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
