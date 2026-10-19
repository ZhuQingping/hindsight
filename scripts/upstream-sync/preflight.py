"""Report pinned merge inputs and conflicts without changing refs, index or worktree."""

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass


@dataclass
class Preflight:
    ours: str
    theirs: str
    bases: list[str]
    ours_commits: int
    theirs_commits: int
    worktree_status: list[str]
    overlapping_paths: list[str]
    conflict_paths: list[str]
    migrations_changed: list[str]
    simulation_clean: bool
    runtime_validation: str = "NOT_RUN"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).rstrip("\n")


def inspect(ours_ref: str, theirs_ref: str) -> Preflight:
    ours = git("rev-parse", "--verify", "--end-of-options", f"{ours_ref}^{{commit}}")
    theirs = git("rev-parse", "--verify", "--end-of-options", f"{theirs_ref}^{{commit}}")
    bases = git("merge-base", "--all", ours, theirs).splitlines()
    if len(bases) != 1:
        raise SystemExit("Multiple merge bases require explicit ancestry review")
    counts = git("rev-list", "--left-right", "--count", f"{ours}...{theirs}").split()
    our_paths = set(git("diff", "--name-only", bases[0], ours).splitlines())
    their_paths = set(git("diff", "--name-only", bases[0], theirs).splitlines())
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", "--name-only", "-z", ours, theirs],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(result.stderr or "Git merge simulation failed")
    # With -z, the first empty field separates conflicted filenames from messages.
    fields = result.stdout.split("\0")
    conflicts = fields[1 : fields.index("", 1)] if result.returncode == 1 else []
    return Preflight(
        ours=ours,
        theirs=theirs,
        bases=bases,
        ours_commits=int(counts[0]),
        theirs_commits=int(counts[1]),
        worktree_status=git("status", "--short").splitlines(),
        overlapping_paths=sorted(our_paths & their_paths),
        conflict_paths=conflicts,
        migrations_changed=git(
            "diff", "--name-only", bases[0], theirs, "--", "hindsight-api-slim/hindsight_api/alembic"
        ).splitlines(),
        simulation_clean=result.returncode == 0,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ours", required=True)
    parser.add_argument("--theirs", required=True)
    args = parser.parse_args()
    print(json.dumps(asdict(inspect(args.ours, args.theirs)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
