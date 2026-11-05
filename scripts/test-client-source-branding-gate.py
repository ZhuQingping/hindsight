"""Regression checks for source audit boundaries and negative install assertions."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "source_branding", Path(__file__).with_name("test-client-source-branding.py")
)
assert spec is not None and spec.loader is not None
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class SourceBrandingTests(unittest.TestCase):
    def check_source(self, relative: str, content: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(content)
            listing = subprocess.CompletedProcess([], 0, stdout=relative + "\0")
            with patch.object(audit, "ROOT", root), patch.object(audit.subprocess, "run", return_value=listing):
                audit.main()

    def test_svg_markup_is_scanned(self) -> None:
        path = "hindsight-integrations/example/logo.svg"
        self.check_source(path, '<svg aria-label="ContextBase"/>')
        with self.assertRaisesRegex(SystemExit, "logo.svg:1"):
            self.check_source(path, '<svg aria-label="Vectorize"/>')

    def test_installer_negative_assertions_keep_their_original_subject(self) -> None:
        path = "hindsight-integrations/coding-agents/scripts/test-customer-install.mjs"
        self.check_source(path, "assert(!/hindsight|contextbase-local-engine/i.test(manifestText));")
        self.check_source(path, "assert(!/hindsight/i.test(bundle));")
        with self.assertRaisesRegex(SystemExit, "test-customer-install.mjs:1"):
            self.check_source(path, 'assert(!/hindsight/i.test(bundle), "Vectorize");')

    def test_ordinary_source_cannot_use_the_installer_exception(self) -> None:
        with self.assertRaisesRegex(SystemExit, "client.js:1"):
            self.check_source("hindsight-clients/example/client.js", "assert(!/hindsight/i.test(bundle));")


if __name__ == "__main__":
    unittest.main()
