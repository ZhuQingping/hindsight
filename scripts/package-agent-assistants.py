"""Build standalone ContextBase assistant plugins with their unregistered SDK dependency included."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def inspect_archive(artifact: Path) -> None:
    """Inspect build-time assets; never filter customer data or runtime API errors."""

    def check(name: str, data: bytes) -> None:
        if re.search(rb"hindsight", name.encode() + data, re.IGNORECASE):
            raise ValueError(f"Legacy brand in {artifact.name}: {name}")

    if artifact.suffix == ".zip":
        with ZipFile(artifact) as archive:
            for name in archive.namelist():
                check(name, archive.read(name))
    else:
        with tarfile.open(artifact) as archive:
            for member in archive:
                stream = archive.extractfile(member) if member.isfile() else None
                check(member.name, stream.read() if stream else b"")


def package_openclaw(sdk: Path, output: Path) -> Path:
    source = ROOT / "hindsight-integrations/openclaw"
    manifest = json.loads((source / "package.json").read_text())
    if manifest["name"] != "contextbase-openclaw":
        raise ValueError("Unexpected OpenClaw identity")
    destination = output / manifest["name"] / manifest["version"]
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="contextbase-openclaw-pack-") as temporary:
        stage = Path(temporary) / "plugin"
        stage.mkdir()
        shutil.copytree(source / "dist", stage / "dist")
        for name in ("openclaw.plugin.json", "README.md"):
            shutil.copyfile(source / name, stage / name)
        shutil.copyfile(ROOT / "LICENSE", stage / "LICENSE")
        unpacked = Path(temporary) / "sdk"
        with tarfile.open(sdk) as archive:
            archive.extractall(unpacked, filter="data")
        dependency = json.loads((unpacked / "package/package.json").read_text())
        if dependency["name"] != "contextbase-client":
            raise ValueError("Unexpected Node SDK")
        modules = stage / "node_modules"
        modules.mkdir()
        shutil.move(str(unpacked / "package"), modules / "contextbase-client")
        manifest["dependencies"]["contextbase-client"] = dependency["version"]
        manifest["bundleDependencies"] = ["contextbase-client"]
        manifest["files"].append("LICENSE")
        for field in ("devDependencies", "overrides", "scripts"):
            manifest.pop(field, None)
        (stage / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
        subprocess.run(
            ["npm", "pack", "--ignore-scripts", "--workspaces=false", "--pack-destination", str(destination)],
            cwd=stage,
            check=True,
        )
    return destination / f"contextbase-openclaw-{manifest['version']}.tgz"


def package_hermes(sdk: Path, output: Path) -> Path:
    source = ROOT / "hindsight-integrations/hermes"
    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    if project["name"] != "hermes-plugin-contextbase":
        raise ValueError("Unexpected Hermes identity")
    destination = output / project["name"] / project["version"]
    destination.mkdir(parents=True, exist_ok=True)
    artifact = destination / f"hermes-plugin-contextbase-{project['version']}.zip"
    # The directory plugin is a Hermes workspace member. Its SDK source must be
    # inside that member, never a relative path back into the source repository.
    manifest = (
        f'[project]\nname = "{project["name"]}"\nversion = "{project["version"]}"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["contextbase-client>=1.0.0,<2", "packaging>=23"]\n\n'
        "[tool.uv]\npackage = false\n\n"
        f'[tool.uv.sources]\ncontextbase-client = {{ path = "sdk/{sdk.name}" }}\n'
    )
    with ZipFile(artifact, "w", ZIP_DEFLATED) as archive:
        prefix = project["name"]
        for name in ("__init__.py", "settings.py", "config_schema.py", "setup.py", "plugin.yaml", "README.md"):
            archive.write(source / name, f"{prefix}/{name}")
        archive.write(ROOT / "LICENSE", f"{prefix}/LICENSE")
        archive.write(sdk, f"{prefix}/sdk/{sdk.name}")
        archive.writestr(f"{prefix}/pyproject.toml", manifest)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["openclaw", "hermes"])
    parser.add_argument("--sdk-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifact = (package_openclaw if args.component == "openclaw" else package_hermes)(
        args.sdk_artifact.resolve(), args.output.resolve()
    )
    inspect_archive(artifact)
    (artifact.parent / "SHA256SUMS").write_text(
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n"
    )
    print(f"PASS: standalone {args.component} package: {artifact}")


if __name__ == "__main__":
    main()
