"""Native local startup contracts; real Windows smoke coverage runs without Bash."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values
from filelock import FileLock, Timeout

from hindsight_ext_contextdb import local
from hindsight_ext_contextdb.bootstrap import UiSecrets, load_deployment_secrets, save_credential
from hindsight_ext_contextdb.deployment import write_environment
from hindsight_ext_contextdb.private_paths import private_directory, private_file
from hindsight_ext_contextdb.windows import load_environment


def test_local_defaults_force_both_auth_layers_and_user_management(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    directory = tmp_path / "private-state"
    private_directory(directory)
    monkeypatch.setenv("CONTEXTBASE_API_TENANT_EXTENSION", "")
    monkeypatch.setenv("CONTEXTBASE_CP_AUTH_MODE", "bootstrap")
    monkeypatch.setenv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "false")
    monkeypatch.setenv("CONTEXTBASE_API_LLM_API_KEY", "synthetic-model-secret")
    local.configure(directory, "postgresql://synthetic", 8888, 9999)
    api = dotenv_values(directory / "api.env", interpolate=False)
    ui = dotenv_values(directory / "ui.env", interpolate=False)
    assert api["CONTEXTBASE_API_TENANT_EXTENSION"] == "hindsight_ext_contextdb.tenant:ContextDBTenantExtension"
    assert ui["CONTEXTBASE_CP_AUTH_MODE"] == "local"
    assert ui["CONTEXTBASE_CP_CONTEXTDB_ENABLED"] == "true"
    assert "synthetic-model-secret" not in (directory / "ui.env").read_text(encoding="utf-8")


def test_private_secrets_are_reused_and_never_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    directory = tmp_path / "private-state"
    private_directory(directory)
    path = directory / "ui-secrets.json"
    save_credential(path, UiSecrets(password="saved-ui-password", admin_key="saved-admin-key"))
    before = path.read_bytes()
    private_file(path)
    with pytest.raises(FileExistsError):
        save_credential(path, UiSecrets(password="replacement", admin_key="replacement"))
    assert path.read_bytes() == before
    monkeypatch.setenv("CONTEXTBASE_CP_ACCESS_KEY", "ambient-password")
    load_deployment_secrets(directory, "ui")
    assert os.environ["CONTEXTBASE_CP_ACCESS_KEY"] == "saved-ui-password"
    assert os.environ["CONTEXTBASE_CP_DATAPLANE_API_KEY"] == "saved-admin-key"


def test_windows_environment_preserves_literal_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    directory = tmp_path / "private-state"
    private_directory(directory)
    values = {
        "CONTEXTBASE_CP_SESSION_DIR": str(directory / "中文 sessions"),
        "MODEL_SECRET": "quote'\"$value${NOT_EXPANDED}\\end",
    }
    # The Windows format is JSON-quoted dotenv, never shell-evaluated.
    path = directory / "ui.env"
    path.write_text(
        "".join(f"{key}={json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items()), encoding="utf-8"
    )
    if sys.platform != "win32":
        path.chmod(0o600)
    load_environment(directory, "ui")
    assert all(os.environ[key] == value for key, value in values.items())
    write_environment(path, values, replace=True)
    if sys.platform == "win32":
        load_environment(directory, "ui")
        assert all(os.environ[key] == value for key, value in values.items())


def test_local_lock_excludes_a_second_process(tmp_path: Path) -> None:
    lock = tmp_path / "local.lock"
    with FileLock(str(lock), timeout=0):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from filelock import FileLock, Timeout; import sys;\ntry: FileLock(sys.argv[1], timeout=0).acquire()\nexcept Timeout: sys.exit(7)",
                str(lock),
            ],
            check=False,
        )
        assert result.returncode == 7
    with FileLock(str(lock), timeout=0):
        pass


@pytest.mark.skipif(sys.platform != "win32", reason="Requires real Windows NTFS access control")
def test_windows_rejects_a_public_acl(tmp_path: Path) -> None:
    directory = tmp_path / "private-state"
    private_directory(directory)
    secret = directory / "ui-secrets.json"
    save_credential(secret, UiSecrets(password="private-password", admin_key="private-key"))
    result = subprocess.run(["icacls.exe", str(secret), "/grant", "*S-1-1-0:R"], capture_output=True, check=False)
    assert result.returncode == 0
    with pytest.raises(ValueError, match="private NTFS ACL"):
        private_file(secret)
