"""Offline deployment initialization; no instance-registration HTTP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg

from . import METADATA_VERSION
from .bootstrap import (
    AdministratorCredential,
    load_deployment_secrets,
    prepare_deployment,
    read_credential,
    rotate_administrator,
    save_credential,
)
from .config import Settings
from .database_checks import verify_binding, verify_format
from .migrations import migrate_connection
from .preflight import preflight
from .security import issue_admin_key


async def migrate(credential_path: Path) -> None:
    settings = Settings.from_environment()
    credential = read_credential(credential_path)
    url = os.environ.get("HINDSIGHT_API_DATABASE_URL")
    if not url:
        raise ValueError("Set HINDSIGHT_API_DATABASE_URL for the deployment database")
    connection = await asyncpg.connect(url)
    try:
        await migrate_connection(
            connection,
            settings.instance_id,
            settings.cloud_tenant_id,
            pepper=settings.pepper,
            admin_secret=credential.secret,
        )
    finally:
        await connection.close()


async def rotate(credential_path: Path) -> None:
    settings = Settings.from_environment()
    credential = read_credential(credential_path)
    url = os.environ.get("HINDSIGHT_API_DATABASE_URL")
    if not url:
        raise ValueError("Set HINDSIGHT_API_DATABASE_URL for the deployment database")
    connection = await asyncpg.connect(url, timeout=10)
    try:
        async with connection.transaction():
            await verify_format(connection)
            await verify_binding(connection, settings.instance_id, settings.cloud_tenant_id)
            await rotate_administrator(connection, credential.secret, settings.pepper)
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ContextDB deployment initialization")
    parser.add_argument(
        "command",
        choices=["migrate", "generate-admin-key", "rotate-admin-key", "preflight", "prepare", "run", "build-ui"],
    )
    parser.add_argument(
        "--admin-key-file", type=Path, help="Private persisted administrator credential for initialization"
    )
    parser.add_argument("--output", type=Path, help="Atomically save generated credential without overwriting")
    parser.add_argument("--source-root", type=Path, help="Require source artifacts to import from this checkout")
    parser.add_argument("--ui-build", action="store_true", help="Check Node/npm and esbuild before a source UI build")
    parser.add_argument("--embedded", action="store_true", help="Also require the optional pg0-embedded dependency")
    parser.add_argument("--language", choices=["english", "chinese", "multilingual"], default="english")
    parser.add_argument("--directory", type=Path, help="Private persistent deployment directory")
    parser.add_argument("--component", choices=["api", "worker", "ui"], help="Foreground component for the node Agent")
    args = parser.parse_args()
    if args.command == "build-ui":
        if args.source_root is None:
            parser.error("build-ui requires --source-root")
        from .artifacts import build_ui

        build_ui(args.source_root.resolve())
        print("Matching ContextDB UI artifact built and stamped")
    elif args.command == "prepare":
        if args.directory is None or not os.environ.get("HINDSIGHT_API_DATABASE_URL"):
            parser.error("prepare requires --directory and HINDSIGHT_API_DATABASE_URL")
        asyncio.run(
            prepare_deployment(
                args.directory, os.environ["HINDSIGHT_API_DATABASE_URL"], os.environ.get("HINDSIGHT_CP_ACCESS_KEY")
            )
        )
        print("Deployment secrets persisted; existing values preserved")
    elif args.command == "run":
        if args.directory is None or args.component is None or args.source_root is None:
            parser.error("run requires --directory, --component and --source-root")
        from .launch import launch

        launch(args.component, args.directory, args.source_root)
    elif args.command == "preflight":
        report = asyncio.run(
            preflight(
                source_root=args.source_root, ui_build=args.ui_build, embedded=args.embedded, language=args.language
            )
        )
        print(report.model_dump_json(indent=2))
        raise SystemExit(0 if report.passed else 1)
    elif args.command in {"migrate", "rotate-admin-key"}:
        if args.admin_key_file is None:
            parser.error("This command requires --admin-key-file pointing to the persisted credential")
        if args.directory:
            load_deployment_secrets(args.directory, "api")
        if args.command == "migrate":
            asyncio.run(migrate(args.admin_key_file))
            print(f"ContextDB metadata version {METADATA_VERSION} initialized; credentials preserved")
        else:
            asyncio.run(rotate(args.admin_key_file))
            print("Administrator Key rotated; update the protected UI configuration and restart UI")
    else:
        credential = issue_admin_key()
        output = AdministratorCredential(
            key_id=credential.key_id,
            secret=credential.secret,
            sha256=credential.digest.hex(),
        )
        if args.output:
            save_credential(args.output, output)
            print("Administrator credential saved to private file")
        else:
            # Explicit one-time operator output. Runtime verifies a PG HMAC;
            # the optional SHA here is only an offline handoff checksum.
            print(output.model_dump_json())


if __name__ == "__main__":
    main()
