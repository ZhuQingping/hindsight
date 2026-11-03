"""CI failures reveal the safe failure marker, never arbitrary child log content."""

import io
from pathlib import Path

import pytest

from ..system.support.startup_diagnostics import startup_diagnostics


def test_startup_report_excludes_config_and_arbitrary_child_errors(tmp_path: Path) -> None:
    log = tmp_path / "child.log"
    marker = "Local initialization failed during configuration (ValueError at local.py:234); Authentication remains required."
    log.write_text(
        'password="synthetic-ui-password"\n'
        "Authorization: Bearer ctx_admin_synthetic-key\n"
        'Traceback: ValueError("postgresql://user:synthetic-db-password@host/database")\n' + marker + "\n"
    )
    assert startup_diagnostics(log) == marker


def test_startup_report_retains_redacted_embedded_error_and_exit_stage(tmp_path: Path) -> None:
    log = tmp_path / "child.log"
    lines = [
        "Embedded PostgreSQL failed: initdb rejected <redacted>",
        "Local initialization failed during embedded database startup (ValueError at local.py:58)",
    ]
    log.write_text("\n".join(lines))
    assert startup_diagnostics(log) == "\n".join(lines)


def test_startup_report_bounds_reads_lines_and_output(tmp_path: Path) -> None:
    log = tmp_path / "child.log"
    log.write_bytes(
        b"Local initialization failed ancient marker\n"
        + b"x" * 10000
        + b"\xff\n"
        + b"\n".join(b"Local initialization failed " + bytes([65 + i]) * 1000 for i in range(8))
    )
    report = startup_diagnostics(log)
    assert len(report) <= 2003
    assert len(report.splitlines()) == 4
    assert "ancient" not in report
    assert all(len(line) <= 500 for line in report.splitlines())


def test_startup_report_handles_missing_or_markerless_log(tmp_path: Path) -> None:
    log = tmp_path / "absent.log"
    assert startup_diagnostics(log).startswith("Startup diagnostics unavailable")
    log.write_text("synthetic-provider-secret\n")
    assert startup_diagnostics(log).startswith("No safe startup marker found")


def test_read_boundary_cannot_turn_a_raw_line_into_a_trusted_marker(tmp_path: Path) -> None:
    log = tmp_path / "child.log"
    fragment = b"Local initialization failed synthetic-secret\n"
    # Exactly the final 8192 bytes begin at an untrusted line's inner fragment.
    log.write_bytes(b"x" * 100 + b"untrusted-prefix:" + fragment + b"z" * (8192 - len(fragment)))
    assert startup_diagnostics(log).startswith("No safe startup marker found")


def test_concurrent_log_growth_cannot_expand_the_bounded_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "growing.log"
    marker = b"Local initialization failed during configuration\n"
    log.write_bytes(b"x" * (8192 - len(marker) - 1) + b"\n" + marker)
    original_open = Path.open

    class GrowingLog(io.BufferedReader):
        def read(self, size: int = -1) -> bytes:
            with original_open(log, "ab") as writer:
                writer.write(b"Local initialization failed unexpected-new-output\n" + b"x" * 50000)
            return super().read(size)

    def open_growing(path: Path, *args: object, **kwargs: object) -> GrowingLog:
        assert path == log
        return GrowingLog(io.FileIO(log, "r"))

    monkeypatch.setattr(Path, "open", open_growing)
    assert startup_diagnostics(log) == marker.decode().strip()
