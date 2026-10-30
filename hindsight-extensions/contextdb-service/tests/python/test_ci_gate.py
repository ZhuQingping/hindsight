"""Extension reports must not hide missing or skipped test coverage."""

import importlib.util
from pathlib import Path

import pytest

from ..paths import EXTENSION

SPEC = importlib.util.spec_from_file_location("contextdb_ci_gate", EXTENSION / "scripts/ci_gate.py")
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("defect", [None, "skipped", "failure", "error", "empty", "suite_error", "missing", "invalid"])
def test_reports_cannot_hide_optional_dependency_skips(tmp_path: Path, defect: str | None) -> None:
    import xml.etree.ElementTree as ET

    report = tmp_path / "tests.xml"
    suite = ET.Element("testsuite")
    if defect != "empty":
        case = ET.SubElement(suite, "testcase", name="boundary regression")
        if defect in {"skipped", "failure", "error"}:
            ET.SubElement(case, defect)
    if defect == "suite_error":
        suite.set("errors", "1")
    if defect != "missing":
        ET.ElementTree(suite).write(report)
    if defect == "invalid":
        report.write_text("truncated XML")
    if defect is None:
        gate.check_report(report)
    else:
        with pytest.raises((ValueError, FileNotFoundError, ET.ParseError)):
            gate.check_report(report)
