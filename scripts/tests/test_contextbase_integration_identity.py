"""Cross-integration guards for public package identity and deployment boundaries."""

import ast
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS = ROOT / "hindsight-integrations"


def test_every_owned_integration_manifest_uses_contextbase():
    manifests = sorted(INTEGRATIONS.glob("*/package.json")) + sorted(INTEGRATIONS.glob("*/pyproject.toml"))
    assert manifests
    for path in manifests:
        data = json.loads(path.read_text()) if path.suffix == ".json" else tomllib.loads(path.read_text())
        name = data.get("name") if path.suffix == ".json" else data.get("project", {}).get("name")
        if name:
            assert "hindsight" not in name.lower(), (path, name)
            assert "contextbase" in name.lower(), (path, name)


def test_python_package_paths_match_their_manifests():
    for path in INTEGRATIONS.glob("*/pyproject.toml"):
        data = tomllib.loads(path.read_text())
        packages = (
            data.get("tool", {})
            .get("hatch", {})
            .get("build", {})
            .get("targets", {})
            .get("wheel", {})
            .get("packages", [])
        )
        for package in packages:
            assert (path.parent / package).is_dir(), (path, package)
        for script in data.get("project", {}).get("scripts", {}).values():
            module = script.split(":")[0].split(".")[0]
            assert (path.parent / module).is_dir() or (path.parent / "src" / module).is_dir(), (path, script)


def test_all_console_locales_offer_public_api_settings():
    locales = list((ROOT / "hindsight-control-plane/src/messages").glob("*.json"))
    assert len(locales) >= 10
    for path in locales:
        text = path.read_text()
        assert "HINDSIGHT_API_" not in text, path
        assert "CONTEXTBASE_API_" in text, path


def test_framework_client_factories_refuse_an_implicit_endpoint():
    """Exercise the actual factory with its unchanged SDK and a minimal config module.

    Frameworks are optional dependencies. Loading their small factory module in
    isolation checks the outbound boundary without importing an entire framework.
    """
    import importlib.util
    import sys
    import types

    paths = list(INTEGRATIONS.glob("*/contextbase_*/_client.py"))
    checked = 0
    for path in paths:
        tree = ast.parse(path.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "resolve_client"]
        if not functions or [arg.arg for arg in functions[0].args.args] != ["client", "contextbase_api_url", "api_key"]:
            continue
        package_name = "_contextbase_identity_" + path.parent.name
        package = types.ModuleType(package_name)
        package.__path__ = [str(path.parent)]
        config_spec = importlib.util.spec_from_file_location(package_name + ".config", path.with_name("config.py"))
        config = importlib.util.module_from_spec(config_spec)
        sys.modules[package_name] = package
        sys.modules[config.__name__] = config
        config_spec.loader.exec_module(config)
        if hasattr(config, "reset_config"):
            config.reset_config()
        spec = importlib.util.spec_from_file_location(package_name + "._client", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            supplied_client = object()
            assert module.resolve_client(supplied_client, None, None) is supplied_client
            try:
                module.resolve_client(None, None, None)
            except Exception as exc:
                assert re.search("API URL|URL configured", str(exc)), (path, str(exc))
            else:
                raise AssertionError(f"{path} constructed a client without an endpoint")
            checked += 1
        finally:
            sys.modules.pop(package_name, None)
            sys.modules.pop(config.__name__, None)
    assert checked >= 8
