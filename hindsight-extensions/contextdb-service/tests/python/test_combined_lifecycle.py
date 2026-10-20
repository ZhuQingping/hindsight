"""A combined container must not leave a surviving API or UI after failure."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from ..paths import EXTENSION

SUPERVISOR = EXTENSION / "scripts/run_combined.py"


@pytest.mark.parametrize("exit_code", [None, 0, 7])
def test_combined_stop_and_peer_failure(tmp_path: Path, exit_code: int | None) -> None:
    child = tmp_path / "child.py"
    child.write_text(
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "root, role = Path(sys.argv[1]), sys.argv[2]\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "(root / (role + '.pid')).write_text(str(os.getpid()))\n"
        "while True:\n"
        "    if role == 'api' and (root / 'fail').exists():\n"
        "        sys.exit(int((root / 'fail').read_text()))\n"
        "    time.sleep(0.05)\n"
    )
    service = tmp_path / "service.sh"
    service.write_text('exec "$TEST_PYTHON" "$TEST_CHILD" "$TEST_ROOT" "$1"\n')
    process = subprocess.Popen(
        [sys.executable, str(SUPERVISOR), str(service), "--stop-timeout", "2"],
        env={**os.environ, "TEST_PYTHON": sys.executable, "TEST_CHILD": str(child), "TEST_ROOT": str(tmp_path)},
    )
    try:
        deadline = time.monotonic() + 10
        while not all((tmp_path / f"{role}.pid").exists() for role in ("api", "ui")):
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.05)
        if exit_code is None:
            process.send_signal(signal.SIGTERM)
        else:
            (tmp_path / "fail").write_text(str(exit_code))
        assert process.wait(timeout=10) == (0 if exit_code is None else 1)
        for role in ("api", "ui"):
            pid = int((tmp_path / f"{role}.pid").read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
