#!/usr/bin/env python3
"""Stage the three plugin distributions; never build or publish a server package."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


class PackageManifest(TypedDict):
    name: str
    version: str


def read_manifest(path: Path) -> PackageManifest:
    return cast(PackageManifest, json.loads(path.read_text()))


def package_archive(component: str, public_name: str, manifest: str, entries: list[str], output: Path) -> None:
    source = ROOT / "hindsight-integrations" / component
    version = read_manifest(source / manifest)["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError(f"Invalid version for {component}")
    destination = output / public_name / version
    destination.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination / f"{public_name}-{version}.zip", "w", ZIP_DEFLATED) as archive:
        for entry in entries:
            path = source / entry
            files = sorted(path.rglob("*")) if path.is_dir() else [path]
            for file in files:
                if not file.is_file() or "__pycache__" in file.parts or file.suffix == ".pyc":
                    continue
                if file.name in {"daemon.py", "llm.py", "upgrade_notice.py"}:
                    continue
                archive.write(file, f"{public_name}/{file.relative_to(source).as_posix()}")
        archive.write(ROOT / "LICENSE", f"{public_name}/LICENSE")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    subprocess.run(
        ["bash", str(ROOT / "scripts/sync-product-brand.sh"), "--check"],
        cwd=ROOT,
        check=True,
    )
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    package_archive(
        "agent-plugin",
        "contextbase-agent-plugin",
        "plugin.json",
        ["plugin.json", "mcp.json", "skills", "README.md"],
        output,
    )
    package_archive(
        "claude-code",
        "contextbase-claude-code",
        ".claude-plugin/plugin.json",
        [
            ".claude-plugin",
            ".mcp.json",
            "hooks",
            "scripts",
            "skills",
            "settings.json",
            "requirements.txt",
            "README.md",
        ],
        output,
    )

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/package-coding-agents.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )

    for directory in sorted(path for path in output.glob("*/*") if path.is_dir()):
        artifacts = sorted(path for path in directory.iterdir() if path.suffix in {".zip", ".tgz"})
        checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts)
        (directory / "SHA256SUMS").write_text(checksums)


if __name__ == "__main__":
    main()
