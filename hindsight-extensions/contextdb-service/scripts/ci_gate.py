"""Reject missing, empty, skipped or failed extension test reports."""

import argparse
import xml.etree.ElementTree as ET
from pathlib import Path


def check_report(path: Path) -> None:
    """A successful pytest exit alone does not prove optional cases actually ran."""
    root = ET.parse(path).getroot()
    if not list(root.iter("testcase")):
        raise ValueError(f"Empty test report: {path}")
    for node in root.iter():
        if node.tag in {"skipped", "failure", "error"} or any(
            int(node.get(field, "0")) for field in ("skipped", "failures", "errors")
        ):
            raise ValueError(f"Incomplete or failed test report: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.reports:
        check_report(path)


if __name__ == "__main__":
    main()
