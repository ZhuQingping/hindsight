"""Regression tests for the exact public npm archive's disclosure boundary."""

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


def load_packager() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "coding_agents_package", Path(__file__).with_name("package-coding-agents.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACKAGER = load_packager()


class PublicArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.artifact = Path(self.temporary.name) / "client.tgz"
        self.files = {
            "package/package.json": json.dumps({"name": "contextbase-coding-agents", "version": "1.0.0"}).encode(),
            "package/README.md": b"ContextBase client",
            "package/LICENSE": b"MIT License\nCopyright (c) 2025 Vectorize AI, Inc.",
            "package/dist/installer.js": b"console.log('install')",
            "package/dist/mcp-server.js": b"console.log('mcp')",
            "package/skill/SKILL.md": b"Client tools",
        }

    def audit(self) -> None:
        with tarfile.open(self.artifact, "w:gz") as archive:
            for name, content in self.files.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        PACKAGER.audit_tarball(self.artifact)

    def test_public_client_and_dependency_sourceurl_literal_are_allowed(self) -> None:
        # AJV generates schema sourceURL strings at runtime; that is not an emitted source map.
        self.files["package/dist/mcp-server.js"] = b"const code = `/*# sourceURL=${schemaId} */`;"
        self.audit()

    def test_source_and_source_maps_are_rejected(self) -> None:
        for name in (
            "package/src/index.ts",
            "package/dist/index.js.map",
            "package/dist/test.ts",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.files[name] = b"implementation"
                try:
                    self.audit()
                finally:
                    del self.files[name]

    def test_source_map_directive_and_repository_details_are_rejected(self) -> None:
        for content in (
            b"//# sourceMappingURL=index.js.map",
            b"//# sourceURL=/private/index.js",
            b"https://github.com/RSIXDB/private",
            b"hindsight-integrations",
            b'const names = ["ContextBase", "agentstratum"];',
            b"Vectorize",
            b"/workspace/private",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.files["package/dist/installer.js"] = content
                self.audit()

    def test_upstream_brand_is_only_allowed_in_the_license(self) -> None:
        self.audit()
        for name in ("package/README.md", "package/skill/SKILL.md"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.files[name] = b"Vectorize AI"
                try:
                    self.audit()
                finally:
                    self.files[name] = b"ContextBase client"

    def test_stale_distribution_and_internal_skill_docs_are_rejected(self) -> None:
        for content in (
            b"Public distribution uses Huawei Cloud OBS + CDN.",
            b"The OBS/CDN release does not use registry-based updates.",
            b"The concrete download root is pending.",
            b"Historical internal fields: daemonProfile, embedPackagePath",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.files["package/skill/SKILL.md"] = content
                self.audit()

    def test_repository_and_development_metadata_are_rejected(self) -> None:
        for field in ("repository", "gitHead", "devDependencies", "scripts", "private"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.files["package/package.json"] = json.dumps({field: "internal"}).encode()
                self.audit()

    def test_local_dependencies_are_rejected(self) -> None:
        self.files["package/package.json"] = b'{"dependencies":{"client":"file:../../client"}}'
        with self.assertRaises(ValueError):
            self.audit()

    def test_missing_license_is_rejected(self) -> None:
        del self.files["package/LICENSE"]
        with self.assertRaises(ValueError):
            self.audit()

    def test_path_traversal_is_rejected(self) -> None:
        self.files["package/../secret.json"] = b"secret"
        with self.assertRaises(ValueError):
            self.audit()


if __name__ == "__main__":
    unittest.main()
