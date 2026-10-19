"""Tests for the contextbase-roo-code CLI entry point."""

import json
from pathlib import Path

import pytest

from contextbase_roo_code.cli import main
from contextbase_roo_code.install import DEFAULT_API_URL


def test_install_writes_both_files(tmp_path: Path) -> None:
    rc = main(["install", "--project-dir", str(tmp_path), "--api-url", "http://localhost:8888"])
    assert rc == 0

    roo_dir = tmp_path / ".roo"
    assert (roo_dir / "mcp.json").exists()
    assert (roo_dir / "rules" / "contextbase-memory.md").exists()


def test_install_requires_an_explicit_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONTEXTBASE_API_URL", raising=False)
    with pytest.raises(ValueError, match="CONTEXTBASE_API_URL"):
        main(["install", "--project-dir", str(tmp_path)])
    assert not (tmp_path / ".roo" / "mcp.json").exists()


def test_install_custom_api_url(tmp_path: Path) -> None:
    main(
        [
            "install",
            "--project-dir",
            str(tmp_path),
            "--api-url",
            "http://localhost:8888",
        ]
    )

    data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
    assert data["mcpServers"]["contextbase"]["url"] == "http://localhost:8888/mcp"


def test_api_url_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBASE_API_URL", "http://env-url:9999")
    main(["install", "--project-dir", str(tmp_path)])

    data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
    assert data["mcpServers"]["contextbase"]["url"] == "http://env-url:9999/mcp"


def test_no_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0
