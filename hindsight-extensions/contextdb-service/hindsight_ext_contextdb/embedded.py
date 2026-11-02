"""Private pg0 control subprocess: isolate its registry from other local instances."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import secrets
from pathlib import Path

from pydantic import BaseModel, Field

from .bootstrap import save_credential
from .deployment import read_secret


class DatabaseSecret(BaseModel):
    password: str = Field(min_length=32, repr=False)


class DatabaseConnection(BaseModel):
    uri: str = Field(repr=False)


def private_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError("Local state directories must be private (0700)")


def control(command: str, directory: Path, data_dir: Path) -> DatabaseConnection | None:
    from pg0 import Pg0

    private_directory(directory)
    private_directory(data_dir)
    secret_path = directory / "pg-secrets.json"
    if not secret_path.exists():
        if (data_dir / "PG_VERSION").exists():
            raise ValueError("Restore pg-secrets.json for the existing database")
        save_credential(secret_path, DatabaseSecret(password=secrets.token_urlsafe(48)))
    secret = DatabaseSecret.model_validate_json(read_secret(secret_path))
    name = "contextbase-" + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:16]
    pg = Pg0(
        name=name, data_dir=str(data_dir), username="contextbase", password=secret.password, database="contextbase"
    )
    if command == "stop":
        pg.stop()
        return None
    # A lock in the owning launcher excludes concurrent starts for this directory.
    # Reuse after an interrupted launcher; never address pg0's default instance.
    try:
        try:
            info = pg.info()
        except (ValueError, FileNotFoundError):
            info = None
        if info is None or not info.running:
            info = pg.start()
        if not info.uri or Path(info.data_dir or "").resolve() != data_dir.resolve():
            raise ValueError("Embedded database directory does not match local state")
        return DatabaseConnection(uri=info.uri)
    except BaseException:
        # A pg0 failure after spawning postgres must not orphan this owned instance.
        pg.stop()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    try:
        if platform.system() != "Linux" or platform.machine() != "x86_64":
            raise ValueError("Embedded local deployment supports Linux x86_64")
        libc, version = platform.libc_ver()
        if libc != "glibc" or tuple(int(part) for part in version.split(".")[:2]) < (2, 35):
            parser.exit(2, "Embedded PostgreSQL requires glibc 2.35 or later\n")
        if os.geteuid() == 0:
            parser.exit(2, "Embedded PostgreSQL must run as a non-root user\n")
        result = control(args.command, args.directory, args.data_dir)
        if result is not None:
            # Internal captured pipe to the launcher; never emit this to its console.
            print(result.model_dump_json())
    except Exception:
        parser.exit(2, "Embedded PostgreSQL failed; check pg0 installation, private data directory and saved secrets\n")


if __name__ == "__main__":
    main()
