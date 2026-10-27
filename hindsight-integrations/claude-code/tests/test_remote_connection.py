"""Remote configuration must not discover or launch a local engine."""

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from lib.client import ContextBaseClient
from lib.connection import get_api_url


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_endpoint_is_actionable(value: str | None) -> None:
    with pytest.raises(RuntimeError, match="API Endpoint is required"):
        get_api_url(value)


@pytest.mark.parametrize("value", ["file:///tmp/api", "https://u:p@tenant.example", "https://tenant.example?key=x"])
def test_invalid_endpoint(value: str) -> None:
    with pytest.raises(ValueError):
        get_api_url(value)


def test_distinct_endpoints_and_credentials() -> None:
    seen: list[str] = []

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            token = self.headers.get("Authorization", "")
            seen.append(f"{self.server.server_port} {self.path} {token}")
            self.send_response(401 if token == "Bearer rejected" else 200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, format: str, *args: object) -> None:
            pass

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Receiver) for _ in range(2)]
    threads = [Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    try:
        for index, server in enumerate(servers):
            url = get_api_url(f"http://127.0.0.1:{server.server_port}/")
            ContextBaseClient(url, f"key-{index}").request("GET", "/version")
        denied = ContextBaseClient(f"http://127.0.0.1:{servers[0].server_port}", "rejected")
        with pytest.raises(RuntimeError, match="HTTP 401"):
            denied.request("GET", "/version")
        assert seen == [
            f"{servers[0].server_port} /version Bearer key-0",
            f"{servers[1].server_port} /version Bearer key-1",
            f"{servers[0].server_port} /version Bearer rejected",
        ]
    finally:
        for server, thread in zip(servers, threads):
            server.shutdown()
            server.server_close()
            thread.join()


@pytest.mark.parametrize("endpoint", ["", "https://tenant.example"])
def test_session_start_reports_configuration_once_without_deprecation(tmp_path: Path, endpoint: str) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "session_start.py"
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(("CONTEXTBASE_", "CLAUDE_PLUGIN_"))
    }
    environment.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), CONTEXTBASE_API_URL=endpoint)
    result = subprocess.run(
        [sys.executable, str(script)], input="{}", text=True, capture_output=True, env=environment, check=True
    )
    if endpoint:
        assert result.stdout == ""
    else:
        assert "API Endpoint is required" in json.loads(result.stdout)["systemMessage"]
    assert "DEPRECATED" not in result.stdout
