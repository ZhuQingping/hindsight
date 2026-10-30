#!/usr/bin/env python3
"""Build and audit the public Coding Agents tarball without repository metadata."""

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
SOURCE = ROOT / "hindsight-integrations/coding-agents"
# A separate manifest prevents development dependencies and build paths from reaching customers.
PUBLIC_FIELDS = {
    "name",
    "version",
    "description",
    "type",
    "main",
    "types",
    "bin",
    "exports",
    "dsh",
    "cline",
    "engines",
    "dependencies",
    "optionalDependencies",
    "peerDependencies",
}
RUNTIME_ENTRIES = (
    "dist",
    "skill",
    "hooks",
    "index.js",
    "cordis.patch.yml",
    "plugin.json",
)
FORBIDDEN_CONTENT = re.compile(rb"hindsight|agentstratum|RSIXDB|/workspace/|/home/runner/work/", re.IGNORECASE)
UPSTREAM_BRAND = re.compile(rb"vectorize", re.IGNORECASE)
STALE_CUSTOMER_DOCS = re.compile(
    rb"OBS/CDN|Huawei Cloud OBS|download root is pending|Historical internal fields|"
    rb"daemonIdleTimeout|daemonProfile|embedVersion|embedPackage(?:Path)?",
    re.IGNORECASE,
)
SOURCE_MAP_DIRECTIVE = re.compile(rb"(?m)^\s*(?://[#@]|/\*[#@])\s*(?:sourceMappingURL|sourceURL)\s*=")


def audit_tarball(artifact: Path) -> None:
    """Inspect the actual archive, including implicit npm metadata files."""
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members if member.isfile()}
        required = {
            "package/package.json",
            "package/README.md",
            "package/dist/installer.js",
            "package/dist/mcp-server.js",
            "package/skill/SKILL.md",
        }
        if not required <= names:
            raise ValueError(f"Missing public runtime files: {sorted(required - names)}")
        for member in members:
            path = Path(member.name)
            if member.isdir():
                continue
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unsafe archive member: {member.name}")
            relative = path.relative_to("package")
            allowed = (
                len(relative.parts) == 1 and relative.name in {"package.json", "README.md", *RUNTIME_ENTRIES[3:]}
            ) or (len(relative.parts) > 1 and relative.parts[0] in RUNTIME_ENTRIES[:3])
            if not allowed or relative.suffix not in {
                ".json",
                ".md",
                ".js",
                ".ts",
                ".yml",
                "",
            }:
                raise ValueError(f"Unexpected public file: {member.name}")
            if relative.suffix == ".ts" and not relative.name.endswith(".d.ts"):
                raise ValueError(f"TypeScript source must not ship: {member.name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable archive member: {member.name}")
            content = stream.read()
            if FORBIDDEN_CONTENT.search(member.name.encode() + b"\n" + content) or SOURCE_MAP_DIRECTIVE.search(content):
                raise ValueError(f"Repository details or source map in {member.name}")
            if UPSTREAM_BRAND.search(member.name.encode() + b"\n" + content):
                raise ValueError(f"Upstream brand in {member.name}")
            if relative.suffix == ".md" and STALE_CUSTOMER_DOCS.search(content):
                raise ValueError(f"Stale distribution or internal configuration docs in {member.name}")
            if relative.name == "package.json" and len(relative.parts) == 1:
                manifest = json.loads(content)
                if set(manifest) - (PUBLIC_FIELDS | {"license", "files"}):
                    raise ValueError("Unexpected public package metadata")
                if (
                    manifest.get("name") != "@huaweicloud/contextbase-coding-agents"
                    or manifest.get("bin", {}).get("contextbase-coding-agents") != "dist/installer.js"
                ):
                    raise ValueError("Unexpected public package name or executable")
                for field in (
                    "dependencies",
                    "optionalDependencies",
                    "peerDependencies",
                ):
                    if any(
                        re.match(r"(?:file:|link:|workspace:|git|https?:)", value)
                        for value in manifest.get(field, {}).values()
                    ):
                        raise ValueError(f"Non-registry dependency in {field}")


def package_coding_agents(output: Path) -> Path:
    """Stage only the remote client and publishable metadata; never mutate source files."""
    manifest = json.loads((SOURCE / "package.json").read_text())
    if manifest["name"] != "@huaweicloud/contextbase-coding-agents":
        raise ValueError("Unexpected Coding Agents distribution identity")
    version = manifest["version"]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Invalid Coding Agents version")
    plugin = json.loads((SOURCE / "plugin.json").read_text())
    if plugin["version"] != version:
        raise ValueError("Plugin and npm versions must match")
    if (SOURCE / "dist/daemon-start.js").exists():
        raise ValueError("Local engine entrypoint must not be distributed")
    # npm flattens a scoped package name in its tarball filename.
    package_slug = manifest["name"].removeprefix("@").replace("/", "-")
    destination = output.resolve() / package_slug / version
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="contextbase-npm-") as temporary:
        stage = Path(temporary)
        for entry in RUNTIME_ENTRIES:
            source = SOURCE / entry
            if source.is_dir():
                shutil.copytree(source, stage / entry)
            else:
                shutil.copy2(source, stage / entry)
        public = {key: value for key, value in manifest.items() if key in PUBLIC_FIELDS}
        public["license"] = "MIT"
        public["files"] = list(RUNTIME_ENTRIES)
        (stage / "package.json").write_text(json.dumps(public, indent=2) + "\n")
        shutil.copy2(SOURCE / "README.public.md", stage / "README.md")
        # Pack outside the checkout: npm cannot add its source gitHead to this manifest.
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
    artifact = destination / f"{package_slug}-{version}.tgz"
    try:
        audit_tarball(artifact)
    except Exception:
        artifact.unlink(missing_ok=True)
        raise
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (destination / "SHA256SUMS").write_text(f"{checksum}  {artifact.name}\n")
    print(f"PASS: public Coding Agents package audited: {artifact}")
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package_coding_agents(args.output)


if __name__ == "__main__":
    main()
