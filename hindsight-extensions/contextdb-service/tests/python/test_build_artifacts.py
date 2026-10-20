"""A stale or partially copied UI cannot be launched with a new source API."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from hindsight_ext_contextdb import artifacts


def test_successful_build_is_verified_and_rejects_changed_source_or_bundle(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(artifacts, "source_fingerprint", lambda root: "a" * 64)

    def compile_ui(*args, **kwargs):
        directory = tmp_path / "hindsight-control-plane/standalone"
        (directory / ".next/static").mkdir(parents=True)
        (directory / "server.js").write_text("// built server")
        (directory / ".next/static/app.js").write_text("// built client")

    build = Mock(side_effect=compile_ui)
    monkeypatch.setattr(artifacts.subprocess, "run", build)
    artifacts.build_ui(tmp_path)
    artifacts.verify_ui_build(tmp_path)
    build.assert_called_once()
    chunk = tmp_path / "hindsight-control-plane/standalone/.next/static/app.js"
    chunk.write_text("// old copied client")
    with pytest.raises(ValueError, match="mismatched"):
        artifacts.verify_ui_build(tmp_path)
    chunk.write_text("// built client")
    monkeypatch.setattr(artifacts, "source_fingerprint", lambda root: "b" * 64)
    with pytest.raises(ValueError, match="stale"):
        artifacts.verify_ui_build(tmp_path)


def test_failed_or_changing_build_never_produces_stamp(tmp_path: Path, monkeypatch):
    values = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(artifacts, "source_fingerprint", lambda root: next(values))
    monkeypatch.setattr(artifacts.subprocess, "run", Mock())
    with pytest.raises(ValueError, match="changed during"):
        artifacts.build_ui(tmp_path)
    assert not list(tmp_path.rglob("contextdb-release.json"))


def test_manifest_existence_does_not_bypass_source_or_bundle_validation(tmp_path: Path):
    directory = tmp_path / "hindsight-control-plane/standalone"
    directory.mkdir(parents=True)
    (directory / "server.js").write_text("// copied server without matching sources")
    (directory / "contextdb-release.json").write_text(
        artifacts.UiBuild(source_sha256="a" * 64, bundle_sha256="b" * 64).model_dump_json()
    )
    with pytest.raises(ValueError, match="mismatched"):
        artifacts.verify_ui_build(tmp_path)
