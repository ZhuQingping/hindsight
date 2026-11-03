"""Private pg0 control subprocess: isolate its registry from other local instances."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import platform
import secrets
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from .bootstrap import save_credential
from .deployment import read_secret
from .private_paths import private_directory


class DatabaseSecret(BaseModel):
    password: str = Field(min_length=32, repr=False)


class DatabaseConnection(BaseModel):
    uri: str = Field(repr=False)


class EmbeddedDatabaseError(ValueError):
    """A pg0 diagnostic with this instance's database password removed."""


def postgres_directory(path: Path) -> Path:
    """Use a Windows short name when PostgreSQL cannot encode a Unicode path."""
    if sys.platform != "win32":
        return path
    try:
        str(path).encode("mbcs")
        return path
    except UnicodeEncodeError:
        pass
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetShortPathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetShortPathNameW.restype = ctypes.c_uint32
    size = kernel.GetShortPathNameW(str(path), None, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size)
        length = kernel.GetShortPathNameW(str(path), buffer, size)
        if 0 < length < size:
            try:
                buffer.value.encode("mbcs")
                return Path(buffer.value)
            except UnicodeEncodeError:
                pass
    raise EmbeddedDatabaseError(
        "PostgreSQL cannot encode this Windows path and no compatible NTFS short name is available. "
        "Set CONTEXTDB_DEPLOY_DIR and CONTEXTDB_PG_DATA_DIR to ASCII-only paths, then restart."
    )


def control(command: str, directory: Path, data_dir: Path) -> DatabaseConnection | None:
    from pg0 import Pg0

    private_directory(directory)
    private_directory(data_dir)
    data_dir = postgres_directory(data_dir)
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
    except BaseException as error:
        # A pg0 failure after spawning postgres must not orphan this owned instance.
        try:
            pg.stop()
        except Exception:
            pass  # Preserve the original startup failure, including when no PG was started.
        if isinstance(error, Exception):
            raise EmbeddedDatabaseError(str(error).replace(secret.password, "<redacted>")[:500]) from None
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("data_dir", type=Path)
    args = parser.parse_args()
    try:
        system = platform.system()
        if system not in {"Linux", "Windows"} or platform.machine().lower() not in {"x86_64", "amd64"}:
            raise ValueError("Embedded local deployment supports Linux and Windows x86_64")
        if sys.platform != "win32":
            libc, version = platform.libc_ver()
            if libc != "glibc" or tuple(int(part) for part in version.split(".")[:2]) < (2, 35):
                parser.exit(2, "Embedded PostgreSQL requires glibc 2.35 or later\n")
            if os.geteuid() == 0:
                parser.exit(2, "Embedded PostgreSQL must run as a non-root user\n")
        else:
            # pg0 extracts PostgreSQL under its private registry. Its binaries,
            # like initdb's data path, must be representable in the Windows ACP.
            for key in ("HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
                if os.environ.get(key):
                    os.environ[key] = str(postgres_directory(Path(os.environ[key])))
        result = control(args.command, args.directory, args.data_dir)
        if result is not None:
            # Internal captured pipe to the launcher; never emit this to its console.
            print(result.model_dump_json())
    except Exception as error:
        detail = str(error) if isinstance(error, EmbeddedDatabaseError) else type(error).__name__
        parser.exit(2, "Embedded PostgreSQL failed: " + detail + "\n")


if __name__ == "__main__":
    main()
