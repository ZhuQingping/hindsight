"""Exercise the shipped archive boundary, including nested SDKs and legal notices."""

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch
from zipfile import ZipFile

from client_artifact_audit import ROOT, check_member, inspect_archive


def load_packager(filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(filename, Path(__file__).with_name(filename))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SDK = load_packager("package-sdks.py")
ASSISTANTS = load_packager("package-agent-assistants.py")
PLUGINS = load_packager("package-client-plugins.py")


class ClientArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.license = (ROOT / "LICENSE").read_bytes()

    def test_all_identities_are_rejected_in_names_and_contents(self) -> None:
        for check in (check_member, SDK.check_member):
            for identity in ("Hindsight", "AGENTSTRATUM", "Vectorize", "RSIXDB"):
                with self.subTest(check=check, identity=identity):
                    with self.assertRaises(ValueError):
                        check("package/README.md", identity.encode())
                    with self.assertRaises(ValueError):
                        check(f"package/{identity}.txt", b"ContextBase")

    def test_only_exact_canonical_license_is_exempt(self) -> None:
        check_member("package/LICENSE", self.license)
        for name, content in (
            ("package/README.md", self.license),
            ("package/LICENSE", self.license + b"\nHindsight product instructions"),
            ("package/hindsight/LICENSE", self.license),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_member(name, content)

    def test_nested_sdk_contents_are_checked_for_zip_and_tar_plugins(self) -> None:
        for identity in (b"ContextBase", b"Hindsight", b"AGENTSTRATUM", b"Vectorize", b"RSIXDB"):
            sdk = io.BytesIO()
            with ZipFile(sdk, "w") as archive:
                archive.writestr("contextbase_client/client.py", identity)
                archive.writestr("contextbase_client-1.0.0.dist-info/licenses/LICENSE", self.license)
            for extension in ("zip", "tgz"):
                with self.subTest(identity=identity, extension=extension):
                    artifact = self.work / f"contextbase-plugin.{extension}"
                    if extension == "zip":
                        with ZipFile(artifact, "w") as archive:
                            archive.writestr("plugin/sdk/contextbase_client.whl", sdk.getvalue())
                    else:
                        with tarfile.open(artifact, "w:gz") as archive:
                            member = tarfile.TarInfo("package/sdk/contextbase_client.whl")
                            member.size = len(sdk.getvalue())
                            archive.addfile(member, io.BytesIO(sdk.getvalue()))
                    for inspect in (inspect_archive, ASSISTANTS.inspect_archive):
                        if identity == b"ContextBase":
                            inspect(artifact)
                        else:
                            with self.assertRaisesRegex(ValueError, "client.py"):
                                inspect(artifact)

    def test_plugin_packager_checks_real_zip_and_removes_rejected_artifact(self) -> None:
        source = self.work / "hindsight-integrations/claude-code"
        source.mkdir(parents=True)
        (source / "plugin.json").write_text(json.dumps({"name": "contextbase", "version": "1.0.0"}))
        (self.work / "LICENSE").write_bytes(self.license)
        output = self.work / "artifacts"
        artifact = output / "contextbase-claude-code/1.0.0/contextbase-claude-code-1.0.0.zip"
        with patch.object(PLUGINS, "ROOT", self.work):
            for content in ("ContextBase", "@vectorize-io/self-driving-agents"):
                (source / "README.md").write_text(content)
                if content == "ContextBase":
                    PLUGINS.package_archive(
                        "claude-code", "contextbase-claude-code", "plugin.json", ["README.md"], output
                    )
                    inspect_archive(artifact)
                else:
                    with self.assertRaises(ValueError):
                        PLUGINS.package_archive(
                            "claude-code", "contextbase-claude-code", "plugin.json", ["README.md"], output
                        )
                    self.assertFalse(artifact.exists())


if __name__ == "__main__":
    unittest.main()
