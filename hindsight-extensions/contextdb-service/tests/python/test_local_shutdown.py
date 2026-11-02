"""Stopping local launchers must bound cleanup even when children ignore signals."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.mark.parametrize("stop_signal", [signal.SIGTERM, signal.SIGINT])
@pytest.mark.parametrize("descendant", [False, True])
def test_local_stop_kills_uncooperative_process_group(tmp_path: Path, stop_signal: int, descendant: bool) -> None:
    marker = tmp_path / "ready"
    group_marker = tmp_path / "group"
    stubborn = (
        "import os, signal, time\nfrom pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
        "while True: time.sleep(.05)\n"
    )
    child = (
        "import subprocess, sys, os, time\nfrom pathlib import Path\n"
        f"Path({str(group_marker)!r}).write_text(str(os.getpid()))\n"
    )
    if descendant:
        child += f"subprocess.Popen([sys.executable, '-c', {stubborn!r}])\nwhile True: time.sleep(.05)\n"
    else:
        child += stubborn
    wrapper = (
        "from hindsight_ext_contextdb.local import serve\nimport os, sys\n"
        f"sys.exit(serve([sys.executable, '-c', {child!r}], dict(os.environ), stop_timeout=.3))\n"
    )
    process = subprocess.Popen([sys.executable, "-c", wrapper], start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() or not marker.stat().st_size:
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        process.send_signal(stop_signal)
        process.wait(timeout=5)
        pid = int(marker.read_text())
        state = Path(f"/proc/{pid}/stat")
        # Orphan zombies may await the container's init reaper; they cannot run.
        deadline = time.monotonic() + 2
        while state.exists() and state.read_text().split()[2] != "Z":
            assert time.monotonic() < deadline
            time.sleep(0.02)
    finally:
        if group_marker.exists():
            try:
                os.killpg(int(group_marker.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
