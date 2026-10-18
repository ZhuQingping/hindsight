"""Generate only the optional ContextDB management contract, without a database."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import cast
from unittest.mock import patch

import yaml
from fastapi import FastAPI
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.http import ContextDBHttpExtension


def generate() -> str:
    # A contract build must never consume deployment credentials or initialize
    # providers. Router construction needs configuration, but no startup hooks.
    environment = {
        "CONTEXTDB_INSTANCE_ID": "contract-instance",
        "CONTEXTDB_CLOUD_TENANT_ID": "contract-tenant",
        "CONTEXTDB_KEY_PEPPER": "synthetic-contract-pepper-at-least-32-characters",
        "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
    }
    with patch.dict(os.environ, environment, clear=True):
        app = FastAPI(title="ContextDB management", version="1.0.0")
        extension = ContextDBHttpExtension({})
        app.include_router(extension.get_router(cast(MemoryEngine, object())), prefix="/ext")
        document = app.openapi()
    prefix = "/ext/contextdb/v1"
    document["paths"] = {path.removeprefix(prefix): value for path, value in document["paths"].items()}
    document["servers"] = [{"url": prefix}]
    document["security"] = [{"AdministratorKey": []}]
    return yaml.safe_dump(document, allow_unicode=True, sort_keys=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "contextdb-control-plane.openapi.yaml",
    )
    args = parser.parse_args()
    content = generate()
    if args.check:
        if not args.output.is_file() or args.output.read_text() != content:
            raise SystemExit("ContextDB OpenAPI is stale; rerun scripts/generate_openapi.py")
        print("ContextDB OpenAPI is current")
    else:
        args.output.write_text(content)
        print(f"Generated {args.output}")


if __name__ == "__main__":
    main()
