"""Run integration acceptance against a fresh task-owned PG, never the dev DB.

Run with the repository .venv/bin/python (pg0 must be installed). Suite-specific
virtual environments must be synchronized beforehand; the UI must be built for
system acceptance. Extra pytest arguments follow --.
"""

from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

from pg0 import Pg0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["api", "system", "contextdb-system", "extension", "contracts"])
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HINDSIGHT_API_", "CONTEXTBASE_API_", "AGENTSTRATUM_API_"))
    }
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    extension = root / "hindsight-extensions/contextdb-service"
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(extension), str(root / "hindsight-system-tests"), str(root / "hindsight-api-slim")]
    )
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="contextdb-acceptance-") as directory:
        database = Pg0(
            name="contextdb-acceptance-" + secrets.token_hex(6),
            port=port,
            data_dir=directory,
            database="integration_test",
        )
        try:
            info = database.start()
            if not info.uri:
                raise RuntimeError("Test database did not return a connection URL")
            if args.suite == "api":
                package = root / "hindsight-api-slim"
                interpreter = root / ".venv/bin/python"
                environment["HINDSIGHT_API_DATABASE_URL"] = info.uri
                environment["HINDSIGHT_TEST_PRIVATE_DATABASE"] = "1"
                selection = [
                    "-n",
                    "4",
                    "-m",
                    "not hs_llm_mat and not hs_llm_core and not integration and not slow and not oracle",
                ]
                targets = ["tests"]
            elif args.suite in {"system", "contextdb-system", "contracts"}:
                package = root / "hindsight-system-tests"
                interpreter = package / ".venv/bin/python"
                environment["HINDSIGHT_SYSTEM_TEST_DATABASE_URL"] = info.uri
                if args.suite == "contextdb-system":
                    # Ordinary developer runs may skip an absent UI. Acceptance
                    # must fail before collection rather than silently lose it.
                    server = Path(
                        environment.get("CONTEXTDB_UI_SERVER", root / "contextbase-control-plane/standalone/server.js")
                    )
                    if not server.is_file():
                        raise RuntimeError("ContextDB system acceptance requires a matching production UI build")
                    selection = ["-c", str(extension / "pytest-system.ini")]
                    targets = [str(extension / "tests/system")]
                elif args.suite == "contracts":
                    selection = ["-c", str(extension / "pyproject.toml")]
                    targets = [str(extension / "tests/contracts")]
                else:
                    selection = []
                    targets = ["tests"]
            else:
                package = extension
                interpreter = package / ".venv/bin/python"
                environment["CONTEXTDB_DEPLOYMENT_TEST_ADMIN_URL"] = info.uri
                selection = []
                targets = ["tests/python"]
            extra = args.pytest_args
            if extra[:1] == ["--"]:
                extra = extra[1:]
            process = subprocess.Popen(
                [str(interpreter), "-m", "pytest", *selection, *targets, "--tb=short", *extra],
                cwd=package,
                env=environment,
            )
            try:
                return process.wait()
            except BaseException:
                # Readiness/setup/interrupt never transfers process ownership
                # outside this runner; stop pytest before stopping its database.
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
        finally:
            database.stop()


if __name__ == "__main__":
    raise SystemExit(main())
