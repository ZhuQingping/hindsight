"""Build and inspect downloadable ContextBase Python SDK packages."""

import argparse
import hashlib
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from zipfile import ZipFile

from client_artifact_audit import check_member

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("language", choices=["python"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = ROOT / "hindsight-clients/python"
    # The repository stages canonical licenses rather than tracking a copy in every Python package.
    if not (source / "LICENSE").exists():
        (source / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    import tomllib

    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    if project["name"] != "contextbase-client":
        raise ValueError("Unexpected SDK distribution name")
    version = project["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[a-zA-Z0-9.-]+)?", version):
        raise ValueError("Invalid SDK version")
    destination = args.output.resolve() / f"contextbase-{args.language}-sdk" / version
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "build", str(source), "--outdir", str(destination)], check=True)
    artifacts = list(destination.glob("*.whl")) + list(destination.glob("*.tar.gz"))
    if len(artifacts) != 2:
        raise ValueError("Expected one Python wheel and one source archive")
    for artifact in artifacts:
        check_member(artifact.name, b"")
        if artifact.suffix == ".whl":
            with ZipFile(artifact) as archive:
                for name in archive.namelist():
                    check_member(name, archive.read(name))
        else:
            with tarfile.open(artifact) as archive:
                for member in archive.getmembers():
                    stream = archive.extractfile(member) if member.isfile() else None
                    check_member(member.name, stream.read() if stream else b"")
    checksums = "".join(
        f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {artifact.name}\n" for artifact in sorted(artifacts)
    )
    (destination / "SHA256SUMS").write_text(checksums)
    print(f"PASS: {args.language} SDK packages and branding checked at {destination}")


if __name__ == "__main__":
    main()
