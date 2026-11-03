"""Stage and audit the scoped Node.js SDK for public npm distribution."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hindsight-clients/typescript"
PUBLIC_NAME = "@huaweicloud/contextbase-client"
PUBLIC_FIELDS = {
    "version",
    "description",
    "main",
    "module",
    "types",
    "exports",
    "engines",
    "license",
}
PUBLIC_FILES = {
    "package.json",
    "README.md",
    "dist/index.js",
    "dist/index.mjs",
    "dist/index.d.ts",
    "dist/index.d.mts",
}
FORBIDDEN = re.compile(
    rb"hindsight|agentstratum|vectorize|RSIXDB|/workspace/|/home/runner/work/",
    re.IGNORECASE,
)
SOURCE_MAP = re.compile(rb"(?:sourceMappingURL|sourceURL)\s*=", re.IGNORECASE)


def audit_tarball(artifact: Path) -> None:
    """Reject unexpected files, development metadata and brands in the final archive."""
    with tarfile.open(artifact, "r:gz") as archive:
        names = set()
        for member in archive.getmembers():
            path = Path(member.name)
            if member.isdir():
                continue
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            relative = path.relative_to("package").as_posix()
            if relative not in PUBLIC_FILES or relative in names:
                raise ValueError(f"Unexpected archive member: {member.name}")
            names.add(relative)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable archive member: {member.name}")
            content = stream.read()
            if FORBIDDEN.search(member.name.encode() + b"\n" + content) or SOURCE_MAP.search(content):
                raise ValueError(f"Brand, repository details or source map in {member.name}")
            if relative == "package.json":
                manifest = json.loads(content)
                if manifest["name"] != PUBLIC_NAME or set(manifest) - (PUBLIC_FIELDS | {"name", "files"}):
                    raise ValueError("Unexpected public SDK metadata")
        if names != PUBLIC_FILES:
            raise ValueError(f"Missing public SDK files: {sorted(PUBLIC_FILES - names)}")


def package_node_sdk(output: Path) -> Path:
    """Keep the repository SDK identity intact for existing workspace consumers."""
    manifest = json.loads((SOURCE / "package.json").read_text())
    if manifest["name"] != "contextbase-client":
        raise ValueError("Unexpected source SDK identity")
    version = manifest["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid SDK version")
    destination = output.resolve() / "huaweicloud-contextbase-client" / version
    destination.mkdir(parents=True, exist_ok=True)
    # A clean staging directory prevents npm from including source files, development metadata,
    # source maps or the checkout's gitHead. It follows the Coding Agents public-package policy.
    with tempfile.TemporaryDirectory(prefix="contextbase-sdk-npm-") as temporary:
        stage = Path(temporary)
        (stage / "dist").mkdir()
        for name in sorted(PUBLIC_FILES - {"package.json", "README.md"}):
            shutil.copy2(SOURCE / name, stage / name)
        public = {key: value for key, value in manifest.items() if key in PUBLIC_FIELDS}
        public["name"] = PUBLIC_NAME
        public["files"] = ["dist"]
        (stage / "package.json").write_text(json.dumps(public, indent=2) + "\n")
        readme = (SOURCE / "README.md").read_text()
        readme = readme.replace("Install the downloaded package", "Install the npm package")
        readme = re.sub(
            r"npm install ./contextbase-client-[^\s]+\.tgz",
            f"npm install {PUBLIC_NAME}",
            readme,
        )
        readme = readme.replace('"contextbase-client"', f'"{PUBLIC_NAME}"')
        (stage / "README.md").write_text(readme)
        subprocess.run(
            [
                "npm",
                "pack",
                "--ignore-scripts",
                "--workspaces=false",
                "--pack-destination",
                str(destination),
            ],
            cwd=stage,
            check=True,
        )
    artifact = destination / f"huaweicloud-contextbase-client-{version}.tgz"
    try:
        audit_tarball(artifact)
    except Exception:
        artifact.unlink(missing_ok=True)
        raise
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{checksum}  {artifact.name}\n")
    print(f"PASS: public Node.js SDK audited: {artifact}")
    return artifact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    package_node_sdk(parser.parse_args().output)
