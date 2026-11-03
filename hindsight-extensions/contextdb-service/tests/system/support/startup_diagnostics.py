"""Bounded, launcher-controlled diagnostics for a child that cannot become ready."""

import os
from pathlib import Path

_MARKERS = (
    "Local initialization failed",
    "Embedded PostgreSQL failed:",
    "This local deployment is already running",
    "ContextBase API:",
    "INFO:     Application startup complete.",
)


def startup_diagnostics(path: Path) -> str:
    # Native logs can include environment or credential-bearing exceptions.
    # Relay only our startup markers (embedded PG already redacts its password),
    # not a raw log tail or any private deployment configuration files.
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            offset = max(0, stream.tell() - 8192)
            stream.seek(offset)
            tail = stream.read(8192).decode("utf-8", errors="replace")
    except OSError:
        return "Startup diagnostics unavailable; inspect the private process log."
    if offset:
        # A raw line cut in the middle must not acquire a trusted-looking prefix.
        tail = tail.partition("\n")[2]
    lines = [line for line in tail.splitlines() if line.startswith(_MARKERS)]
    return (
        "\n".join(line[:500] for line in lines[-4:]) or "No safe startup marker found; inspect the private process log."
    )
