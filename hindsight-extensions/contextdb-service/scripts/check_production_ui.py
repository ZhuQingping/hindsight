"""Require both production UI Worker stories without skips or failures."""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

STORY = "test_ui_workspace_user_key_and_native_permission_flow"
EXPECTED_CASES = frozenset(f"{STORY}[{mode}]" for mode in ("embedded-worker", "standalone-worker"))


def verify_results(report: Path) -> None:
    document = ET.parse(report).getroot()
    cases = list(document.iter("testcase"))
    names = [case.get("name") for case in cases]
    for expected in EXPECTED_CASES:
        if names.count(expected) != 1:
            raise ValueError(f"Expected exactly one successful Worker story: {expected}")
    if len(cases) != len(EXPECTED_CASES):
        raise ValueError("Production UI report contains an unexpected test selection")
    if any(case.find(tag) is not None for case in cases for tag in ("skipped", "failure", "error")):
        raise ValueError("Production UI Worker stories must pass without skips, failures or errors")
    # Collection/setup failures can be represented outside a testcase.
    for suite in document.iter("testsuite"):
        if any(int(suite.get(attribute, "0")) for attribute in ("failures", "errors", "skipped")):
            raise ValueError("Production UI suite contains skips, failures or errors")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    verify_results(args.report)


if __name__ == "__main__":
    main()
