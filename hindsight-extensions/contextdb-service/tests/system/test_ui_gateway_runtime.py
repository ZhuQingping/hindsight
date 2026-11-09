"""Node-dependent UI process stories belong to the production UI test profile."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from ..paths import EXTENSION


@pytest.mark.parametrize("mode", ["graceful", "child-failure", "stubborn"])
def test_gateway_owns_node_and_propagates_its_failure(tmp_path: Path, mode: str) -> None:
    if not shutil.which("node"):
        pytest.skip("Node is required for UI runtime acceptance")
    server = tmp_path / "contextbase-control-plane/standalone/server.js"
    server.parent.mkdir(parents=True)
    pidfile = tmp_path / "node.pid"
    server.write_text(
        "const fs=require('fs'), http=require('http');\n"
        f"fs.writeFileSync({str(pidfile)!r}, String(process.pid));\n"
        + ("process.on('SIGTERM',()=>{});\n" if mode == "stubborn" else "")
        + (
            "process.exit(7);\n"
            if mode == "child-failure"
            else "http.createServer((req,res)=>{res.end(process.env.HINDSIGHT_CP_PUBLIC_ORIGIN+'|'+process.env.CONTEXTBASE_CP_PUBLIC_ORIGIN+'|'+process.env.HOSTNAME+'|'+process.env.CONTEXTBASE_CP_TRUST_EXTERNAL_ORIGIN);}).listen(Number(process.env.PORT),process.env.HOSTNAME);\n"
        )
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(EXTENSION),
        "CONTEXTBASE_CP_CONTEXTDB_ENABLED": "true",
        "CONTEXTBASE_CP_HOST": "127.0.0.1",
        "CONTEXTBASE_CP_PORT": str(port),
    }
    command = [
        sys.executable,
        "-c",
        "from pathlib import Path; import sys; from hindsight_ext_contextdb.ui_gateway import run; run(Path(sys.argv[1]))",
        str(tmp_path),
    ]
    with (tmp_path / "runtime.log").open("w") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
        try:
            if mode == "child-failure":
                assert process.wait(timeout=15) == 7
            else:
                deadline = time.monotonic() + 15
                with httpx.Client(trust_env=False, timeout=1) as client:
                    while True:
                        assert process.poll() is None, (tmp_path / "runtime.log").read_text()
                        try:
                            response = client.get(f"http://127.0.0.1:{port}/")
                            if response.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        assert time.monotonic() < deadline
                        time.sleep(0.05)
                stable = f"http://127.0.0.1:{port}"
                assert response.text == stable + "|" + stable + "|127.0.0.1|1"
                process.terminate()
                assert process.wait(timeout=15) == 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if pidfile.exists():
                pid = int(pidfile.read_text())
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    os.kill(pid, 9)
                    pytest.fail("The owned Node child survived gateway shutdown")
