"""Configure an explicitly supplied ContextBase service through Hermes' setup UI."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from agent.secret_scope import get_secret
from hermes_cli.secret_prompt import masked_secret_prompt

from .settings import validate_api_url


def _secret_prompt(label: str) -> str:
    sys.stdout.write(label)
    sys.stdout.flush()
    return masked_secret_prompt("") if sys.stdin.isatty() else sys.stdin.readline().strip()


def _write_env(env_path: Path, env_writes: dict[str, str]) -> None:
    """Update only our keys and preserve other profile settings."""
    if any("\n" in v or "\r" in v for v in env_writes.values()):
        raise ValueError("ContextBase credentials must fit on one line.")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    lines = env_path.read_text(encoding="utf-8-sig").splitlines() if env_path.exists() else []
    updated = set()
    result = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        result.append(f"{key}={json.dumps(env_writes[key])}" if key in env_writes else line)
        updated.add(key)
    result.extend(f"{key}={json.dumps(value)}" for key, value in env_writes.items() if key not in updated)
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")
    env_path.chmod(0o600)


def run_setup(provider: Any, hermes_home: str, config: dict[str, Any]) -> None:
    """Merge connection settings; never download or start a server."""
    from hermes_cli.config import save_config
    from utils import atomic_json_write, read_json_or_empty

    from . import _load_config

    existing = provider._config if isinstance(provider._config, dict) else _load_config()
    config_path = Path(hermes_home) / "contextbase" / "config.json"
    values = {**read_json_or_empty(config_path), **existing}
    current_url = values.get("api_url") or get_secret("CONTEXTBASE_API_URL", "")
    api_url = input(f"ContextBase API Endpoint [{current_url}]: ").strip() or current_url
    api_url = validate_api_url(api_url)
    bank = input(f"Existing Bank ID [{values.get('bank_id', '')}]: ").strip() or values.get("bank_id", "")
    if not bank:
        raise ValueError("An existing authorized Bank ID is required.")
    token = _secret_prompt("ContextBase API Key (blank to keep current): ")
    if not token and not (
        values.get("apiKey")
        or values.get("api_key")
        or get_secret("CONTEXTBASE_API_TOKEN", "")
        or get_secret("CONTEXTBASE_API_KEY", "")
    ):
        raise ValueError("A ContextBase API Key is required.")
    for key in (
        "llm_provider",
        "llm_model",
        "llm_api_key",
        "llm_base_url",
        "idle_timeout",
        "port_health_grace_timeout",
        "profile",
    ):
        values.pop(key, None)
    for key in ("bank_id_template", "trusted_project_dirs", "mirror_to_own_bank"):
        values.pop(key, None)
    values.update(mode="cloud", api_url=api_url.rstrip("/"), bank_id=bank)
    if token:
        values.pop("apiKey", None)
        values.pop("api_key", None)
        _write_env(Path(hermes_home) / ".env", {"CONTEXTBASE_API_TOKEN": token})
    # This is the complete cleaned configuration. Merging again would restore deleted keys.
    atomic_json_write(config_path, values, mode=0o600)
    config.setdefault("memory", {})["provider"] = "contextbase"
    save_config(config)
    print("ContextBase configured. Start a new Hermes session to activate.")
