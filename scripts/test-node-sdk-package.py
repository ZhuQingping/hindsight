"""Check that the public Node SDK audit rejects leaked metadata and unexpected files."""

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("node_sdk_package", Path(__file__).with_name("package-node-sdk.py"))
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class NodeSdkPackageAudit(unittest.TestCase):
    def test_final_archive_rejects_leaks(self) -> None:
        """Exercise bytes in real tar members, including filenames and npm-added metadata."""
        cases = [
            ("dist/index.js", b"Hindsight"),
            ("dist/index.d.ts", b"AGENTSTRATUM"),
            ("README.md", b"Vectorize"),
            ("dist/index.mjs", b"/home/runner/work/private/project"),
            (
                "dist/index.js",
                b"//# sourceMappingURL=data:application/json;base64,e30=",
            ),
            ("dist/index.js.map", b"{}"),
            ("src/index.ts", b"source"),
            ("Vectorize.txt", b"notice"),
            (
                "package.json",
                json.dumps({"name": package.PUBLIC_NAME, "gitHead": "private-commit"}).encode(),
            ),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "sdk.tgz"
            # Start from a complete archive so each negative case tests the intended leak.
            for filename, content in [(None, b""), *cases]:
                with self.subTest(filename=filename, content=content):
                    members = dict.fromkeys(package.PUBLIC_FILES, b"export {};")
                    members["package.json"] = json.dumps({"name": package.PUBLIC_NAME, "version": "1.0.0"}).encode()
                    if filename:
                        members[filename] = content
                    with tarfile.open(artifact, "w:gz") as archive:
                        for name, data in members.items():
                            member = tarfile.TarInfo(f"package/{name}")
                            member.size = len(data)
                            archive.addfile(member, io.BytesIO(data))
                    if filename:
                        with self.assertRaises(ValueError):
                            package.audit_tarball(artifact)
                    else:
                        package.audit_tarball(artifact)


if __name__ == "__main__":
    unittest.main()
