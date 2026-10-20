"""Keep each pytest environment confined to its own test suite."""

from pathlib import Path

import pytest


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    # Explicitly selecting tests/ must not combine PG metadata tests, the native
    # system runner and Node-only contracts in one interpreter configuration.
    if collection_path.parent == Path(__file__).parent:
        selected = "system" if config.inipath and config.inipath.name == "pytest-system.ini" else "python"
        if collection_path.name in {"python", "system", "contracts"} and collection_path.name != selected:
            return True
    return None
