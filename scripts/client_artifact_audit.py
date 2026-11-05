"""Inspect shipped client files, including SDK archives bundled inside plugins."""

import io
import re
import tarfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
LEGACY_IDENTITY = re.compile(rb"hindsight|agentstratum|vectorize|RSIXDB", re.IGNORECASE)
ARCHIVE_SUFFIXES = (".whl", ".zip", ".tgz", ".tar.gz")


def check_member(name: str, content: bytes) -> None:
    if LEGACY_IDENTITY.search(name.encode()):
        raise ValueError(f"Legacy client identity in artifact member: {name}")
    if LEGACY_IDENTITY.search(content):
        # Preserve the exact upstream copyright notice, without exempting other
        # license-like files or allowing product text appended to that notice.
        if Path(name).name == "LICENSE" and content == (ROOT / "LICENSE").read_bytes():
            return
        raise ValueError(f"Legacy client identity in artifact member: {name}")


def inspect_archive(artifact: Path) -> None:
    """Check build-time files only; never rewrite customer data or service errors."""
    _inspect_archive(artifact.name, artifact.read_bytes())


def _inspect_archive(name: str, content: bytes) -> None:
    check_member(name, b"")
    if name.endswith((".whl", ".zip")):
        with ZipFile(io.BytesIO(content)) as archive:
            for member in archive.infolist():
                _inspect_member(f"{name}!/{member.filename}", archive.read(member))
    else:
        with tarfile.open(fileobj=io.BytesIO(content)) as archive:
            for member in archive:
                stream = archive.extractfile(member) if member.isfile() else None
                _inspect_member(f"{name}!/{member.name}", stream.read() if stream else b"")


def _inspect_member(name: str, content: bytes) -> None:
    if name.endswith(ARCHIVE_SUFFIXES):
        _inspect_archive(name, content)
    else:
        check_member(name, content)
