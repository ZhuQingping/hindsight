"""Exercise real Git histories, including conflicts, without touching the caller's index."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from preflight import inspect


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(os.chdir, self.original)
        os.chdir(self.temp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.hooksPath", "/dev/null")
        Path("file").write_text("base\n")
        self.git("add", "file")
        self.git("commit", "-qm", "base")
        self.git("branch", "upstream")

    def git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], text=True).strip()

    def test_conflicts_reported_without_mutating_worktree_or_refs(self) -> None:
        Path("file").write_text("ours\n")
        self.git("commit", "-qam", "ours")
        self.git("checkout", "-q", "upstream")
        Path("file").write_text("theirs\n")
        self.git("commit", "-qam", "theirs")
        self.git("tag", "-a", "v1", "-m", "release")
        self.git("checkout", "-q", "main")
        Path("untracked").write_text("preserve me\n")
        before = self.git("show-ref")
        status = self.git("status", "--porcelain")
        report = inspect("main", "v1")
        self.assertFalse(report.simulation_clean)
        self.assertEqual(report.conflict_paths, ["file"])
        self.assertEqual(report.overlapping_paths, ["file"])
        self.assertEqual(report.theirs, self.git("rev-parse", "v1^{commit}"))
        self.assertEqual(report.runtime_validation, "NOT_RUN")
        self.assertEqual(self.git("show-ref"), before)
        self.assertEqual(self.git("status", "--porcelain"), status)
        self.assertEqual(Path("file").read_text(), "ours\n")

    def test_clean_merge_and_invalid_ref(self) -> None:
        Path("new").write_text("new\n")
        self.git("add", "new")
        self.git("commit", "-qm", "new")
        report = inspect("upstream", "main")
        self.assertTrue(report.simulation_clean)
        self.assertEqual(report.conflict_paths, [])
        self.assertEqual(report.theirs_commits, 1)
        with self.assertRaises(subprocess.CalledProcessError):
            inspect("missing", "main")


if __name__ == "__main__":
    unittest.main()
