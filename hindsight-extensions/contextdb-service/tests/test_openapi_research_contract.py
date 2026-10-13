"""Compare the checked-in design contract when the sibling research repo exists.

CI still runs the standalone sixteen-route assertions in test_http.py. The
separate research repository is intentionally not an extension runtime dependency.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from .test_http import ManagementClient, management


def resolve(document: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in value:
        reference = value["$ref"]
        assert reference.startswith("#/")
        value = document
        for name in reference[2:].split("/"):
            value = value[name]
    return value


def properties(document: dict[str, Any], value: dict[str, Any]) -> dict[str, Any]:
    value = resolve(document, value)
    fields = dict(value.get("properties", {}))
    for fragment in value.get("allOf", []):
        fields.update(properties(document, fragment))
    return fields


def test_research_yaml_matches_generated_management_contract(management: ManagementClient) -> None:
    root = Path(__file__).resolve().parents[3]
    path = root.parent / "ContextDB-Research" / "hindsight" / "api" / "contextdb-control-plane.openapi.yaml"
    if not path.is_file():
        pytest.skip("Sibling research repository is not available; standalone OpenAPI contract checks still run")
    design = yaml.safe_load(path.read_text())
    actual = management.app.openapi()
    prefix = "/ext/contextdb/v1"
    assert design["servers"][0]["url"].endswith("/contextdb/v1")
    assert set(actual["paths"]) == {prefix + item for item in design["paths"]}
    security = design["security"]
    assert (
        actual["components"]["securitySchemes"]["ControlPlaneKey"]["name"]
        == (design["components"]["securitySchemes"]["ControlPlaneKey"]["name"])
    )
    methods = {"get", "post", "patch", "delete"}
    for relative_path, path_item in design["paths"].items():
        assert set(actual["paths"][prefix + relative_path]) & methods == set(path_item) & methods
        for method in set(path_item) & methods:
            expected = path_item[method]
            current = actual["paths"][prefix + relative_path][method]
            assert current["operationId"] == expected["operationId"]
            assert current["security"] == expected.get("security", security)
            expected_parameters = {
                item["name"]: item
                for source in (path_item.get("parameters", []), expected.get("parameters", []))
                for item in [resolve(design, node) for node in source]
            }
            current_parameters = {item["name"]: item for item in current["parameters"]}
            assert set(current_parameters) == set(expected_parameters)
            for name, parameter in expected_parameters.items():
                assert current_parameters[name].get("required", False) == parameter.get("required", False)
                assert current_parameters[name]["in"] == parameter["in"]
            for status, response in expected["responses"].items():
                if status == "default":
                    continue
                current_response = current["responses"][status]
                response = resolve(design, response)
                if status == "204":
                    assert "content" not in current_response
                    continue
                schema = response["content"]["application/json"]["schema"]
                current_schema = current_response["content"]["application/json"]["schema"]
                expected_fields = properties(design, schema)
                current_fields = properties(actual, current_schema)
                assert set(current_fields) == set(expected_fields), current["operationId"]
                if "items" in expected_fields:
                    assert set(properties(actual, current_fields["items"]["items"])) == set(
                        properties(design, expected_fields["items"]["items"])
                    ), current["operationId"]
