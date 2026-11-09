"""Connection stories cannot accidentally override the deployment they exercise."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from ..system.support.ui import ui_owner


@pytest.mark.parametrize(
    "key", ["PATH", "PYTHONPATH", "CONTEXTBASE_CP_PUBLIC_ORIGIN", "HINDSIGHT_CP_TRUST_EXTERNAL_ORIGIN"]
)
def test_ui_extra_environment_cannot_override_owned_settings(tmp_path: Path, key: str) -> None:
    # Validation must happen before build/process access. The deliberately absent
    # deployment is never consumed when an invalid extra setting is supplied.
    with pytest.raises(ValueError, match="cannot override"):
        with ui_owner(Mock(), tmp_path / "missing.js", "node", tmp_path, extra_env={key: "spoofed"}):
            pytest.fail("An owned setting reached UI startup")
