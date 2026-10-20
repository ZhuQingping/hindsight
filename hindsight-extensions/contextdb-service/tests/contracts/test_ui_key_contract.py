"""Node-enabled CI contract gate; Node/dependencies are required, never optional skips."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


def test_ui_key_projections_match_openapi() -> None:
    # Place this test and its CJS sibling under the plugin's tests tree.
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "hindsight-control-plane/src/lib/contextdb-api.ts").is_file()
    )
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("extract-ui-key-contract.cjs")), str(root)],
        check=True,
        capture_output=True,
        text=True,
    )
    consumed = json.loads(result.stdout)
    schemas = yaml.safe_load(
        (root / "hindsight-extensions/contextdb-service/schemas/contextdb-control-plane.openapi.yaml").read_text()
    )["components"]["schemas"]
    assert consumed["permissions"] == sorted(schemas["Permission"]["enum"])
    for name, fields in consumed["projections"].items():
        schema = schemas[name.removeprefix("ContextDB")]
        assert set(fields) == set(schema["properties"]), name
        required = schema.get("required", [])
        for field, actual in fields.items():
            prop = schema["properties"][field]
            nullable = any(branch.get("type") == "null" for branch in prop.get("anyOf", []))
            if actual["type"] == "authorization":
                assert {branch["$ref"] for branch in prop["oneOf"]} == {
                    "#/components/schemas/StoredSelectedAuthorization",
                    "#/components/schemas/AllAuthorization",
                }
                wire_type = "authorization"
            else:
                value = next((branch for branch in prop.get("anyOf", []) if branch.get("type") != "null"), prop)
                wire_type = "number" if value["type"] == "integer" else value["type"]
            assert actual == {"type": wire_type, "nullable": nullable, "required": field in required}, (name, field)
