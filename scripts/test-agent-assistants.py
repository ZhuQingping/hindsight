"""Install actual assistant artifacts outside the checkout and exercise their real HTTP clients."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
CUSTOMER_TEXT = "Customer content mentions hindsight without alteration"
FEATURES = (
    "observations",
    "mcp",
    "worker",
    "bank_config_api",
    "bank_llm_health",
    "file_upload_api",
    "document_export_api",
    "document_import_api",
    "audit_log",
    "llm_trace",
    "store_document_text",
)


class FixtureHandler(BaseHTTPRequestHandler):
    saved: list[str] = []

    def respond(self, status: int, body: object) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def dispatch(self, body: bytes = b"") -> None:
        if self.headers.get("Authorization") != "Bearer customer-key":
            self.respond(401, {"detail": CUSTOMER_TEXT})
        elif self.path == "/customer-api/health":
            self.respond(200, {"status": "ok"})
        elif self.path == "/customer-api/version":
            self.respond(200, {"api_version": "1.0.0", "features": dict.fromkeys(FEATURES, False)})
        elif self.path == "/customer-api/v1/default/banks/team/memories":
            payload = json.loads(body)
            self.saved.extend(item["content"] for item in payload["items"])
            self.respond(
                200, {"success": True, "bank_id": "team", "items_count": len(payload["items"]), "async": False}
            )
        elif self.path == "/customer-api/v1/default/banks/team/memories/recall":
            self.respond(200, {"results": [{"id": "fact", "text": "\n".join(self.saved), "type": "world"}]})
        else:
            self.respond(403, {"detail": "This business key cannot administer Banks or access another Bank."})

    def do_GET(self) -> None:
        self.dispatch()

    def do_POST(self) -> None:
        self.dispatch(self.rfile.read(int(self.headers.get("Content-Length", "0"))))

    def log_message(self, format: str, *args: object) -> None:
        pass


NODE_CHECK = r"""
import assert from 'node:assert/strict';
import plugin from 'contextbase-openclaw';
const hooks = new Map(); const services = [];
const config = {plugins:{entries:{'contextbase-openclaw':{config:{
  contextbaseApiUrl:process.env.TEST_API_URL, contextbaseApiToken:'customer-key',
  dynamicBankId:false, bankId:'team', logLevel:'off'
}}}}};
plugin({config, logger:{info(){},warn(){},error(){}}, on(name,fn){hooks.set(name,fn)}, registerService(service){services.push(service)}});
try {
  await services[0].start();
  const bridge = globalThis.__contextbaseClient;
  await bridge.waitForReady();
  const client = await bridge.getClientForContext({agentId:'main',sessionKey:'test-session'});
  assert.equal(client.bankId,'team');
  await client.retain({content:process.env.TEST_CUSTOMER_TEXT});
  const response = await client.recall({query:'What did the customer say?'});
  assert(JSON.stringify(response).includes(process.env.TEST_CUSTOMER_TEXT));
  assert(hooks.has('before_prompt_build') && hooks.has('agent_end'));
} finally {await services[0].stop();}
"""

PYTHON_CHECK = r"""
import importlib.util, json, os, runpy, sys
from pathlib import Path
# Simulate Hermes' host contract; all plugin code and the SDK under test come from the installed artifacts.
runpy.run_path(os.environ['TEST_HERMES_HOST_FIXTURE'])
for name in list(sys.modules):
    if name == 'contextbase_hermes' or name.startswith('contextbase_hermes.'):
        del sys.modules[name]
source=Path(os.environ['TEST_HERMES_PLUGIN'])
spec=importlib.util.spec_from_file_location('contextbase_hermes',source/'__init__.py',submodule_search_locations=[str(source)])
plugin=importlib.util.module_from_spec(spec);sys.modules['contextbase_hermes']=plugin;spec.loader.exec_module(plugin)
plugin._load_config=lambda:{'mode':'cloud','api_url':os.environ['TEST_API_URL'],'api_key':'customer-key','bank_id':'team'}
first=plugin.ContextBaseMemoryProvider();first.initialize('session-one')
first.sync_turn(os.environ['TEST_CUSTOMER_TEXT'],'Acknowledged.');first.shutdown()
second=plugin.ContextBaseMemoryProvider();second.initialize('session-two')
try:
    result=second.handle_tool_call('contextbase_recall',{'query':'What did the customer say?'})
    assert os.environ['TEST_CUSTOMER_TEXT'] in str(result), result
    assert second._bank_id=='team'
finally:second.shutdown()
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["openclaw", "hermes"])
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args()
    artifact = args.artifact.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="contextbase-assistant-install-") as temporary:
            work = Path(temporary)
            env = {
                **os.environ,
                "TEST_API_URL": f"http://127.0.0.1:{server.server_port}/customer-api",
                "TEST_CUSTOMER_TEXT": CUSTOMER_TEXT,
            }
            env.pop("PYTHONPATH", None)
            if args.component == "openclaw":
                (work / "package.json").write_text('{"private":true,"type":"module"}')
                subprocess.run(
                    ["npm", "install", "--ignore-scripts", "--workspaces=false", str(artifact)],
                    cwd=work,
                    env=env,
                    check=True,
                )
                (work / "verify.mjs").write_text(NODE_CHECK)
                subprocess.run(["node", "verify.mjs"], cwd=work, env=env, check=True)
            else:
                with ZipFile(artifact) as archive:
                    archive.extractall(work)
                plugin = work / "hermes-plugin-contextbase"
                subprocess.run(["uv", "sync", "--project", str(plugin), "--no-dev"], cwd=work, env=env, check=True)
                python = plugin / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                # pytest is used only by the host-contract fixture, not by the shipped plugin.
                subprocess.run(
                    ["uv", "pip", "install", "--python", str(python), "pytest"], cwd=work, env=env, check=True
                )
                env.update(
                    TEST_HERMES_PLUGIN=str(plugin),
                    TEST_HERMES_HOST_FIXTURE=str(ROOT / "hindsight-integrations/hermes/tests/conftest.py"),
                )
                subprocess.run([str(python), "-c", PYTHON_CHECK], cwd=work, env=env, check=True)
            assert any(CUSTOMER_TEXT in text for text in FixtureHandler.saved), (
                "No customer memory reached the configured Bank"
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(f"PASS: installed {args.component} artifact uses explicit endpoint/auth/Bank and preserves customer text")


if __name__ == "__main__":
    main()
