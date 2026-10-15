"""Installing and removing hooks must preserve other plugins' hooks."""

import json
import os
import subprocess
import sys
from pathlib import Path


def test_install_is_idempotent_and_uninstall_preserves_unrelated_hooks(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    original = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "other-plugin"}],
                }
            ]
        },
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


def test_relocation_replaces_owned_hooks_and_preserves_mixed_groups(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    original = {
        "hooks": {
            "Stop": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "other-plugin"}],
                }
            ],
            "SessionStart": [{"matcher": "startup", "hooks": []}],
            "PreToolUse": [{"hooks": [{"type": "command", "command": "keep-tool-hook"}]}],
        },
        "env": {"OTHER": "keep"},
    }
    settings_path.write_text(json.dumps(original))
    script = Path(__file__).resolve().parents[1] / "scripts" / "setup_hooks.py"
    environment = {**os.environ, "HOME": str(tmp_path)}
    command = [sys.executable, str(script)]
    first_root = tmp_path / "install A"
    second_root = tmp_path / "install B 'quote' $(unused)"
    subprocess.run(
        [*command, "--plugin-root", str(first_root)],
        env=environment,
        check=True,
        capture_output=True,
    )
    first = json.loads(settings_path.read_text())
    # Mix another plugin's command into our group. Removing our hook must keep
    # both that command and the group's matcher/other host metadata.
    first["hooks"]["Stop"][-1]["matcher"] = "custom"
    other_hook = {"type": "command", "command": 'python3 "/other/scripts/retain.py"'}
    first["hooks"]["Stop"][-1]["hooks"].append(other_hook)
    settings_path.write_text(json.dumps(first))
    subprocess.run(
        [*command, "--plugin-root", str(second_root)],
        env=environment,
        check=True,
        capture_output=True,
    )
    second = json.loads(settings_path.read_text())
    assert second["env"] == original["env"]
    assert second["hooks"]["PreToolUse"] == original["hooks"]["PreToolUse"]
    assert second["hooks"]["SessionStart"][0] == original["hooks"]["SessionStart"][0]
    assert second["hooks"]["Stop"][1] == {"matcher": "custom", "hooks": [other_hook]}
    for event in ("UserPromptSubmit", "Stop", "SessionStart", "SessionEnd"):
        commands = [hook["command"] for group in second["hooks"][event] for hook in group["hooks"]]
        assert sum("AGENTSTRATUM_HOOK_OWNER=agentstratum-memory " in c for c in commands) == 1
        assert all(str(first_root) not in c for c in commands)
    subprocess.run(
        [*command, "--plugin-root", str(second_root)],
        env=environment,
        check=True,
        capture_output=True,
    )
    assert json.loads(settings_path.read_text()) == second
    # Removal works even from a third path; it does not depend on old files.
    subprocess.run(
        [*command, "--plugin-root", str(tmp_path / "C"), "--uninstall"],
        env=environment,
        check=True,
        capture_output=True,
    )
    original["hooks"]["Stop"].append({"matcher": "custom", "hooks": [other_hook]})
    assert json.loads(settings_path.read_text()) == original


def test_generated_commands_run_with_literal_plugin_paths(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir()
    settings_path.write_text("{}")
    root = tmp_path / "install 'quoted' $(must-not-run)"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    for name in ("recall", "retain", "session_start", "session_end"):
        (scripts / f"{name}.py").write_text(f"print({name!r})")
    setup = Path(__file__).resolve().parents[1] / "scripts" / "setup_hooks.py"
    subprocess.run(
        [sys.executable, str(setup), "--plugin-root", str(root)],
        env={**os.environ, "HOME": str(tmp_path)},
        check=True,
        capture_output=True,
    )
    settings = json.loads(settings_path.read_text())
    outputs = []
    for groups in settings["hooks"].values():
        result = subprocess.run(
            groups[0]["hooks"][0]["command"],
            shell=True,
            check=True,
            text=True,
            capture_output=True,
        )
        outputs.append(result.stdout.strip())
    assert set(outputs) == {"recall", "retain", "session_start", "session_end"}
