"""Verify real SDK artifacts outside the checkout against a local HTTP fixture."""

import argparse
import json
import os
import subprocess
import tempfile
import threading
import venv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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
CUSTOMER_TEXT = "customer document mentions hindsight"


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/customer-api/version":
            self.send_error(404)
            return
        if self.headers.get("Authorization") != "Bearer sdk-test-key":
            status, body = 403, {"detail": CUSTOMER_TEXT}
        elif not self.headers.get("User-Agent", "").startswith("contextbase-client-"):
            status, body = 400, {"detail": "SDK user agent missing"}
        else:
            status, body = (
                200,
                {
                    "api_version": CUSTOMER_TEXT,
                    "features": dict.fromkeys(FEATURES, False),
                },
            )
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        pass


PYTHON_CHECK = """
import asyncio, importlib.metadata, os
from contextbase_client import ContextBase
from contextbase_client_api import Configuration

assert importlib.metadata.version("contextbase-client")
endpoint = os.environ["SDK_TEST_ENDPOINT"]
with ContextBase(base_url=endpoint, api_key="sdk-test-key") as client:
    assert client.get_version().api_version == os.environ["SDK_CUSTOMER_TEXT"]
async def verify():
    client = ContextBase(base_url=endpoint, api_key="sdk-test-key")
    try:
        assert (await client.aget_version()).api_version == os.environ["SDK_CUSTOMER_TEXT"]
    finally:
        await client.aclose()
asyncio.run(verify())
try:
    with ContextBase(base_url=endpoint, api_key="wrong") as client:
        client.get_version()
except Exception as error:
    assert os.environ["SDK_CUSTOMER_TEXT"] in str(error), str(error)
else:
    raise AssertionError("Expected service error")
"""

NODE_CHECK = """
const endpoint = process.env.SDK_TEST_ENDPOINT;
const client = new ContextBaseClient({baseUrl:endpoint, apiKey:"sdk-test-key"});
if ((await client.getVersion()).api_version !== process.env.SDK_CUSTOMER_TEXT) throw Error("Response changed");
try {
  await new ContextBaseClient({baseUrl:endpoint, apiKey:"wrong"}).getVersion();
  throw Error("Expected service error");
} catch (error) {
  if (!String(error).includes(process.env.SDK_CUSTOMER_TEXT)) throw error;
}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "node"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--package-name", default="contextbase-client")
    args = parser.parse_args()
    directory = args.directory.resolve()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "SDK_TEST_ENDPOINT": f"http://127.0.0.1:{server.server_port}/customer-api/",
        "SDK_CUSTOMER_TEXT": CUSTOMER_TEXT,
    }
    env.pop("PYTHONPATH", None)
    try:
        with tempfile.TemporaryDirectory(prefix="contextbase-sdk-install-") as temporary:
            work = Path(temporary)
            if args.language == "python":
                archives = [*directory.glob("*.whl"), *directory.glob("*.tar.gz")]
                assert len(archives) == 2, "Expected wheel and sdist"
                for number, artifact in enumerate(archives):
                    environment = work / str(number)
                    venv.EnvBuilder(with_pip=True).create(environment)
                    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                    subprocess.run(
                        [str(python), "-m", "pip", "install", str(artifact)],
                        cwd=work,
                        env=env,
                        check=True,
                    )
                    subprocess.run([str(python), "-c", PYTHON_CHECK], cwd=work, env=env, check=True)
            else:
                (artifact,) = directory.glob("*.tgz")
                (work / "package.json").write_text('{"private":true}')
                subprocess.run(
                    [
                        "npm",
                        "install",
                        "--ignore-scripts",
                        "--workspaces=false",
                        str(artifact),
                    ],
                    cwd=work,
                    env=env,
                    check=True,
                )
                for name, code in (
                    (
                        "verify.mjs",
                        f"import {{ContextBaseClient}} from {json.dumps(args.package_name)};\n" + NODE_CHECK,
                    ),
                    (
                        "verify.cjs",
                        f"const {{ContextBaseClient}} = require({json.dumps(args.package_name)});\n(async () => {{\n"
                        + NODE_CHECK
                        + "\n})().catch(error => {console.error(error); process.exit(1);});",
                    ),
                ):
                    (work / name).write_text(code)
                    subprocess.run(["node", name], cwd=work, env=env, check=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print(f"PASS: installed {args.language} SDK uses custom endpoint/auth/brand and preserves response/error text")


if __name__ == "__main__":
    main()
