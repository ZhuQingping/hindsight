"""Managed deployment relies on the standard dotenv disable switch."""

import os
from pathlib import Path


def test_managed_entrypoint_uses_standard_dotenv_disable(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("HINDSIGHT_TEST_MANAGED=wrong-parent\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HINDSIGHT_TEST_MANAGED", "injected")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    from hindsight_api.config import load_dotenv_for_entrypoint

    load_dotenv_for_entrypoint()
    assert os.environ["HINDSIGHT_TEST_MANAGED"] == "injected"
