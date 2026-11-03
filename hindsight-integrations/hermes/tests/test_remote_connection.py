"""Cloud configuration fails explicitly and never loads an engine dependency."""

import json

import contextbase_hermes as plugin
import pytest
from conftest import SECRETS
from contextbase_hermes.settings import validate_api_url


@pytest.mark.parametrize(
    "value",
    [
        "",
        "file:///tmp/data",
        "https://user:secret@example.com",
        "https://example.com?key=secret",
        "https://example.com#bank",
    ],
)
def test_invalid_endpoint_is_rejected(value):
    with pytest.raises(ValueError, match="ContextBase API URL"):
        validate_api_url(value)


def test_api_prefix_is_preserved():
    assert validate_api_url(" https://api.example.com/customer/ ") == "https://api.example.com/customer"


def test_token_is_profile_scoped_and_config_has_precedence(hermes_env):
    SECRETS["CONTEXTBASE_API_TOKEN"] = "profile-token"
    SECRETS["CONTEXTBASE_API_KEY"] = "older-key"
    assert plugin._cloud_api_key({}) == "profile-token"
    assert plugin._cloud_api_key({"api_key": "configured"}) == "configured"


def test_empty_configuration_is_unavailable_and_does_not_choose_a_service(hermes_env):
    provider = plugin.ContextBaseMemoryProvider()
    assert not provider.is_available()
    with pytest.raises(ValueError, match="API URL is required"):
        provider.initialize("session")


def test_local_engine_mode_is_rejected(provider):
    with pytest.raises(ValueError, match="only cloud or self-hosted"):
        provider({"mode": "local_embedded"})


def test_setup_merges_connection_and_keeps_the_key_out_of_config(hermes_env, monkeypatch):
    from contextbase_hermes import setup

    instance = plugin.ContextBaseMemoryProvider()
    instance._config = {"auto_recall": False, "api_key": "old"}
    config_path = hermes_env / "contextbase/config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    retired = {"bank_id_template": "hermes-{session}", "trusted_project_dirs": ["/work"], "mirror_to_own_bank": True}
    config_path.write_text(json.dumps({**retired, "api_key": "old", "retain_every_n_turns": 5}))
    answers = iter(["https://api.example.com/prefix", "team"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(setup, "_secret_prompt", lambda _: "new-key")
    setup.run_setup(instance, str(hermes_env), {"memory": {}})
    saved = json.loads((hermes_env / "contextbase/config.json").read_text())
    assert saved["auto_recall"] is False
    assert saved["bank_id"] == "team"
    assert "api_key" not in saved
    assert not retired.keys() & saved.keys()
    assert saved["retain_every_n_turns"] == 5
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert 'CONTEXTBASE_API_TOKEN="new-key"' in (hermes_env / ".env").read_text()


@pytest.mark.parametrize("bank", [None, "", "  ", 42])
def test_missing_bank_is_rejected_before_client_use(provider, bank):
    with pytest.raises(ValueError, match="Bank ID is required"):
        provider({"bank_id": bank})


def test_configured_bank_survives_repository_and_session_changes(provider, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".contextbase").mkdir()
    (tmp_path / ".contextbase/config.toml").write_text('bank_id = "other-bank"')
    instance, fake = provider(
        {
            "bank_id": " team ",
            "bank_id_template": "hermes-{session}-{project}",
            "trusted_project_dirs": [str(tmp_path)],
        },
        cwd=str(tmp_path),
    )
    assert instance._bank_id == "team"
    instance.handle_tool_call("contextbase_retain", {"text": "first"})
    instance.on_session_switch("second-session")
    instance.handle_tool_call("contextbase_retain", {"text": "second"})
    assert instance._bank_id == "team"
    assert instance._write_bank_ids == ["team"]
    assert all(call["bank_id"] == "team" for call in fake.retains)


def test_environment_only_connection_requires_a_bank(hermes_env):
    SECRETS["CONTEXTBASE_API_URL"] = "https://api.example.com"
    instance = plugin.ContextBaseMemoryProvider()
    assert not instance.is_available()
    with pytest.raises(ValueError, match="Bank ID is required"):
        instance.initialize("session")
