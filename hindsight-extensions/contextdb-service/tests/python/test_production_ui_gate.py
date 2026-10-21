"""The CI gate rejects a green-but-skipped or incomplete production UI run."""

from __future__ import annotations

import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ..paths import EXTENSION

SCRIPT = EXTENSION / "scripts/check_production_ui.py"
SPEC = importlib.util.spec_from_file_location("contextdb_production_ui_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


@pytest.mark.parametrize("defect", [None, "missing", "duplicate", "skipped", "failure", "error", "suite_error"])
def test_production_ui_report_requires_both_successful_worker_modes(tmp_path: Path, defect: str | None) -> None:
    suite = ET.Element("testsuite")
    names = sorted(gate.EXPECTED_CASES)
    for name in names:
        ET.SubElement(suite, "testcase", name=name)
    if defect == "missing":
        suite.remove(suite[0])
    elif defect == "duplicate":
        ET.SubElement(suite, "testcase", name=names[0])
    elif defect == "suite_error":
        suite.set("errors", "1")
    elif defect:
        ET.SubElement(suite[0], defect)
    report = tmp_path / "ui.xml"
    ET.ElementTree(suite).write(report)
    if defect is None:
        gate.verify_results(report)
    else:
        with pytest.raises(ValueError):
            gate.verify_results(report)


def test_production_ui_gate_rejects_missing_report(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        gate.verify_results(tmp_path / "absent.xml")
