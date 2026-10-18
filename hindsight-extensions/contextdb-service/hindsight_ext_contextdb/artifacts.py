"""Match a source-built UI to its API/extension checkout before starting it."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pydantic import BaseModel


class UiBuild(BaseModel):
    format: int = 1
    source_sha256: str
    bundle_sha256: str


def bundle_fingerprint(directory: Path) -> str:
    if not (directory / "server.js").is_file():
        raise ValueError("UI standalone server is missing")
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if (
            not path.is_file()
            or {"node_modules", "cache"}.intersection(relative.parts)
            or path.name == "contextdb-release.json"
        ):
            continue
        digest.update(str(relative).encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def source_fingerprint(root: Path) -> str:
    directories = [
        "hindsight-api-slim/hindsight_api",
        "hindsight-extensions/contextdb-service/hindsight_ext_contextdb",
        "hindsight-control-plane/src",
        "hindsight-clients/typescript/src",
    ]
    files: set[Path] = set()
    for directory in directories:
        area = root / directory
        if not area.is_dir():
            raise ValueError("Matching API, extension, client and UI source trees are required")
        files.update(
            path
            for path in area.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
            and ".test." not in path.name
        )
    for name in [
        "package-lock.json",
        "uv.lock",
        "hindsight-control-plane/next.config.mjs",
        "hindsight-control-plane/package.json",
        "hindsight-clients/typescript/package.json",
        "hindsight-api-slim/pyproject.toml",
        "hindsight-extensions/contextdb-service/pyproject.toml",
    ]:
        path = root / name
        if not path.is_file():
            raise ValueError("Matching source dependency locks and configuration are required")
        files.add(path)
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_ui(root: Path) -> None:
    """Stamp only after a successful build of unchanged sources."""
    before = source_fingerprint(root)
    subprocess.run(["npm", "run", "build", "-w", "@vectorize-io/hindsight-control-plane"], cwd=root, check=True)
    if before != source_fingerprint(root):
        raise ValueError("Source changed during UI build; rebuild before deployment")
    server = root / "hindsight-control-plane/standalone/server.js"
    manifest = UiBuild(source_sha256=before, bundle_sha256=bundle_fingerprint(server.parent))
    server.with_name("contextdb-release.json").write_text(manifest.model_dump_json(indent=2) + "\n")


def verify_ui_build(root: Path) -> None:
    server = root / "hindsight-control-plane/standalone/server.js"
    try:
        manifest = UiBuild.model_validate_json(server.with_name("contextdb-release.json").read_text())
        valid = (
            manifest.format == 1
            and manifest.source_sha256 == source_fingerprint(root)
            and manifest.bundle_sha256 == bundle_fingerprint(server.parent)
        )
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise ValueError(
            "UI artifact is missing, stale or mismatched; run the ContextDB build-ui command on this checkout"
        )
