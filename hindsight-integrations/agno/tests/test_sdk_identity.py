"""The integration's SDK identity must survive an actual recall request."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
from threading import Thread

from agno.run.base import RunContext
from contextbase_agno import ContextBaseTools, reset_config
from contextbase_agno.tools import _USER_AGENT


def test_integration_identity_reaches_sdk_request() -> None:
    user_agents: list[str | None] = []
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            user_agents.append(self.headers.get("User-Agent"))
            paths.append(self.path)
            body = b'{"results": []}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    reset_config()
    tools: ContextBaseTools | None = None
    try:
        tools = ContextBaseTools(bank_id="test", contextbase_api_url=f"http://127.0.0.1:{server.server_port}")
        context = RunContext(run_id="run", session_id="session", user_id="user")
        assert tools.recall_memory(context, "preferences") == "No relevant memories found."
        assert user_agents == [f"{_USER_AGENT} contextbase-client-python/{version('contextbase-client')}"]
        assert paths == ["/v1/default/banks/test/memories/recall"]
    finally:
        if tools is not None:
            tools._client.close()
        reset_config()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
