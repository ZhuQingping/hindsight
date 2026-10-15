"""Installing and removing hooks must preserve other plugins' hooks."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_install_is_idempotent_and_uninstall_preserves_unrelated_hooks(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    original = {
        "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "other-plugin"}]}]},
        "env": {"OTHER": "keep"},
    }
    settings_path.write_text(json.dumps(original))
    script = Path(__file__).resolve().parents[1] / "scripts" / "setup_hooks.py"
    environment = {**os.environ, "HOME": str(tmp_path)}
    command = [sys.executable, str(script)]
    subprocess.run(command, env=environment, check=True, capture_output=True)
    first = json.loads(settings_path.read_text())
    subprocess.run(command, env=environment, check=True, capture_output=True)
    assert json.loads(settings_path.read_text()) == first
    assert first["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    subprocess.run([*command, "--uninstall"], env=environment, check=True, capture_output=True)
    assert json.loads(settings_path.read_text()) == original
