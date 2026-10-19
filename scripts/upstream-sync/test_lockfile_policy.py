"""The private development helper exception must not admit published/runtime links."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class LockfilePolicyTest(unittest.TestCase):
    def test_private_helper_and_rejected_release_variants(self) -> None:
        checker = Path(__file__).resolve().parents[1] / "check-integration-lockfiles.sh"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            shutil.copy2(checker, root / "scripts" / checker.name)
            package = root / "hindsight-integrations/coding-agents"
            package.mkdir(parents=True)
            # Each case changes a release boundary while keeping the same linked package.
            for private, dev, runtime, allowed in [
                (True, True, False, True),
                (False, True, False, False),
                (True, False, False, False),
                (True, True, True, False),
            ]:
                with self.subTest(private=private, dev=dev, runtime=runtime):
                    manifest = {
                        "name": "agentstratum-coding-agents",
                        "private": private,
                        "devDependencies": {"agentstratum-local-engine": "file:../../hindsight-all-npm"},
                        "dependencies": {"agentstratum-local-engine": "*"} if runtime else {},
                    }
                    lock = {
                        "packages": {
                            "node_modules/agentstratum-local-engine": {
                                "link": True,
                                "resolved": "../../hindsight-all-npm",
                            },
                            "../../hindsight-all-npm": {"dev": dev},
                        }
                    }
                    (package / "package.json").write_text(json.dumps(manifest))
                    (package / "package-lock.json").write_text(json.dumps(lock))
                    result = subprocess.run(
                        ["bash", str(root / "scripts" / checker.name)], capture_output=True, check=False
                    )
                    self.assertEqual(result.returncode == 0, allowed, result.stdout.decode())


if __name__ == "__main__":
    unittest.main()
