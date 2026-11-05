"""Check all SDKs and framework integrations, including development harnesses."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = re.compile(r"hindsight|agentstratum|vectorize|RSIXDB", re.IGNORECASE)
INTERNAL_PATH = re.compile(
    r"hindsight-(?:clients|integrations|docs|api(?:-slim)?|embed|dev|cli|extensions|all(?:-npm)?)"
)
NATIVE_MODULE = re.compile(r"hindsight_(?:api|embed|dev)\b")
NATIVE_ENV = re.compile(r"HINDSIGHT_(?:API|EMBED)_[A-Z0-9_]+")
# These cases explicitly prove that customer text, service errors and old plugin
# registry entries remain intact. They are never included in customer archives.
NEGATIVE_CASES = {
    "hindsight-integrations/coding-agents/src/core/public-brand.test.ts",
    "hindsight-integrations/coding-agents/src/core/log.test.ts",
    "hindsight-integrations/coding-agents/src/core/legacy.test.ts",
    "hindsight-integrations/claude-code/tests/test_public_brand.py",
    "hindsight-integrations/zcode/tests/test_public_brand.py",
}
SKIP_PARTS = {"node_modules", "dist", "target", "__pycache__", ".venv", ".git", ".ruff_cache", ".pytest_cache"}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".jar", ".pdf", ".svg", ".pyc"}


def main() -> None:
    failures: list[str] = []
    count = 0
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "hindsight-clients",
            "hindsight-integrations",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    for relative in sorted(set(filter(None, tracked.stdout.split("\0")))):
        path = ROOT / relative
        if not path.is_file() or SKIP_PARTS.intersection(path.parts) or path.suffix in BINARY_SUFFIXES:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.name == "LICENSE" or relative in NEGATIVE_CASES:
            continue
        if path.suffix in {".tgz", ".whl", ".zip"}:
            failures.append(f"{relative}: generated client archive must not be checked in")
            continue
        count += 1
        for number, line in enumerate(path.read_text().splitlines(), 1):
            # Repository paths and native engine interfaces are not public
            # SDK identities; changing them requires the engine to move too.
            if ("/tests/" in relative or ".test." in path.name) and (
                "not.toMatch" in line or re.search(r"assert .+ not in", line)
            ):
                continue
            checked = INTERNAL_PATH.sub("", line)
            checked = NATIVE_MODULE.sub("", checked)
            if path.name in {"daemon.py", "llm.py"} or relative.endswith("openclaw/tests/integration.test.ts"):
                checked = NATIVE_ENV.sub("", checked)
            if LEGACY.search(checked):
                failures.append(f"{relative}:{number}: {line.strip()[:160]}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"PASS: {count} SDK and integration source files; only native contracts and negative fixtures are exempt")


if __name__ == "__main__":
    main()
