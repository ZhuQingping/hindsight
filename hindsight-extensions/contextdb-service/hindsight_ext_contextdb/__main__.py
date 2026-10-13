"""Deployment-only bootstrap. It is never exposed as a customer management API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path

import asyncpg
from pydantic import BaseModel, Field


class ControlCredential(BaseModel):
    key_id: str
    secret: str = Field(repr=False)
    sha256: str


async def migrate() -> None:
    url = os.environ.get("CONTEXTDB_BOOTSTRAP_DATABASE_URL")
    if not url:
        raise ValueError("Set CONTEXTDB_BOOTSTRAP_DATABASE_URL explicitly for the deployment database")
    connection = await asyncpg.connect(url)
    try:
        # Deployment tooling must run a single bootstrap owner. Runtime replicas
        # only verify the version, so no global DDL races occur on startup.
        async with connection.transaction():
            await connection.execute(Path(__file__).with_name("schema.sql").read_text())
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="ContextDB deployment bootstrap")
    parser.add_argument("command", choices=["migrate", "generate-control-key"])
    args = parser.parse_args()
    if args.command == "migrate":
        asyncio.run(migrate())
        print("ContextDB metadata schema installed")
    else:
        key_id = secrets.token_hex(16)
        secret = f"ctx_ctrl_{key_id}_{secrets.token_urlsafe(32)}"
        credential = ControlCredential(key_id=key_id, secret=secret, sha256=hashlib.sha256(secret.encode()).hexdigest())
        # This is deliberate one-time operator output. Store secret in the cloud
        # control backend's protected configuration, digest only in API settings.
        print(credential.model_dump_json())


if __name__ == "__main__":
    main()
