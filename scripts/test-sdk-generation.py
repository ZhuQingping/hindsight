"""Check SDK generation, imports and repository paths."""

import argparse
import ast
import importlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_python_sdk_imports() -> None:
    """Resolve SDK imports in production code, integrations, tests and examples."""
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    references = 0
    for relative in filter(None, tracked.stdout.split("\0")):
        path = ROOT / relative
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_bytes(), filename=relative)):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules = [node.module]
            else:
                continue
            for name in modules:
                package = name.split(".")[0]
                assert package not in {"hindsight_client", "hindsight_client_api"}, (
                    f"{relative}:{node.lineno}: obsolete SDK import {name}"
                )
                if package not in {"contextbase_client", "contextbase_client_api"}:
                    continue
                module = importlib.import_module(name)
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name != "*" and not hasattr(module, alias.name):
                            importlib.import_module(f"{name}.{alias.name}")
                references += 1
    print(f"PASS: resolved {references} repository Python SDK imports")


def check_python_repository_paths() -> None:
    """Exercise the real coverage command and compare lock metadata with source configuration."""
    subprocess.run(
        [sys.executable, str(ROOT / "hindsight-dev/hindsight_dev/client_coverage_check.py")],
        cwd=ROOT,
        check=True,
    )
    for name in ("hindsight-system-tests", "hindsight-system-evals"):
        project = ROOT / name
        config = tomllib.loads((project / "pyproject.toml").read_text())
        source = config["tool"]["uv"]["sources"]["contextbase-client"]
        assert (project / source["path"]).resolve() == ROOT / "hindsight-clients/python"
        lock = tomllib.loads((project / "uv.lock").read_text())
        sdk = next(package for package in lock["package"] if package["name"] == "contextbase-client")
        owner = next(package for package in lock["package"] if package["name"] == name)
        requirement = next(item for item in owner["metadata"]["requires-dist"] if item["name"] == "contextbase-client")
        assert source["editable"] is True
        assert sdk["source"]["editable"] == requirement["editable"] == source["path"]


def check_node_generation() -> None:
    """Use the checked-in config and real spec without overwriting maintained generated code."""
    source = ROOT / "hindsight-clients/typescript"
    with tempfile.TemporaryDirectory(prefix="contextbase-sdk-generation-") as temporary:
        root = Path(temporary)
        sdk = root / "hindsight-clients/typescript"
        sdk.mkdir(parents=True)
        for name in ("package.json", "openapi-ts.config.ts"):
            shutil.copyfile(source / name, sdk / name)
        (sdk / "node_modules").symlink_to(source / "node_modules", target_is_directory=True)
        spec = root / "hindsight-docs/static/openapi.json"
        spec.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "hindsight-docs/static/openapi.json", spec)
        subprocess.run(["npm", "run", "generate", "--workspaces=false"], cwd=sdk, check=True)
        # The generator can log a missing-input error without returning failure.
        # Require actual output so neither a wrong path nor a no-op can pass.
        assert (sdk / "generated/sdk.gen.ts").is_file(), "SDK generation produced no API client"
        assert (sdk / "generated/types.gen.ts").is_file(), "SDK generation produced no models"
        for generated in (sdk / "generated").rglob("*.ts"):
            assert not re.search("hindsight|agentstratum|vectorize", generated.read_text(), re.IGNORECASE), (
                f"Legacy SDK identity in generated file: {generated.name}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python", "node"])
    args = parser.parse_args()
    if args.language == "python":
        check_python_sdk_imports()
        check_python_repository_paths()
    else:
        check_node_generation()
    print(f"PASS: {args.language} SDK checks")


if __name__ == "__main__":
    main()
