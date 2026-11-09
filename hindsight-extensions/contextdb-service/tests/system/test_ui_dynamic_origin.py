"""A real production UI keeps serving after an external HTTP authority changes."""

import os
import secrets
import shutil
from pathlib import Path

import httpx
import pytest
from hindsight_system_tests.server import free_port

from ..paths import ROOT
from .support.deployment import ContextDBDeployment
from .support.ui import ui_owner


def test_optional_origin_with_real_backend_and_durable_sessions(
    contextdb_deployment: ContextDBDeployment, tmp_path: Path
) -> None:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "contextbase-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the matching production UI before running this story")
    with ui_owner(contextdb_deployment, server, node, tmp_path, fixed_origin=False) as ui:
        with httpx.Client(base_url=ui.url, timeout=60, trust_env=False) as client:
            assert client.get("/api/health").status_code == 200
            cookies: list[str] = []
            for authority in ("192.0.2.10:3306", "192.0.2.11:3306", "192.0.2.11:3307"):
                headers = {"Host": authority, "Origin": "http://" + authority}
                # Request the same socket with a different external Host. This
                # checks server behavior, not browser cookie transfer across IPs.
                redirect = client.get("/", headers={"Host": authority, "Cookie": ""})
                assert redirect.status_code == 307
                assert redirect.headers["location"].startswith("http://" + authority + "/login")
                assert client.get("/api/contextdb/users", headers={"Host": authority, "Cookie": ""}).status_code == 401
                login = client.post("/api/auth/login", headers=headers, json={"key": ui.password})
                assert login.status_code == 200, login.text
                assert "HttpOnly" in login.headers["set-cookie"]
                cookie = login.headers["set-cookie"].split(";", 1)[0]
                cookies.append(cookie)
                authenticated = {**headers, "Cookie": cookie}
                assert client.get("/api/contextdb/users", headers=authenticated).status_code == 200
                cross_origin = {**authenticated, "Origin": "http://evil.example"}
                assert client.post("/api/auth/logout", headers=cross_origin).status_code == 403
                spoofed = {**authenticated, "X-Forwarded-Proto": "https", "X-Forwarded-Host": "evil.example"}
                assert client.post("/api/auth/login", headers=spoofed, json={"key": ui.password}).status_code == 200
                assert client.post("/api/auth/logout", headers=authenticated).status_code == 200
                assert client.get("/api/contextdb/users", headers=authenticated).status_code == 401
            # One deployed UI has a stable internal identity across all its
            # external aliases; browser domains still isolate host-only cookies.
            assert len({cookie.split("=", 1)[0] for cookie in cookies}) == 1
            for host in ("", "user@evil.example", "evil.example/path", "evil.example,other.example"):
                assert client.get("/api/health", headers={"Host": host}).status_code == 421

    other = tmp_path / "other-instance"
    other.mkdir()
    with ui_owner(contextdb_deployment, server, node, other, fixed_origin=False) as ui:
        login = httpx.post(ui.url + "/api/auth/login", headers={"Origin": ui.url}, json={"key": ui.password})
        assert login.status_code == 200
        assert login.headers["set-cookie"].split("=", 1)[0] != cookies[0].split("=", 1)[0]


@pytest.mark.parametrize("fixed_origin", [True, False])
def test_disabled_plugin_keeps_unmodified_ui_origin_contract(
    contextdb_deployment: ContextDBDeployment, tmp_path: Path, fixed_origin: bool
) -> None:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "contextbase-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the matching production UI before running this story")
    expected = 200 if fixed_origin else 503
    with ui_owner(
        contextdb_deployment,
        server,
        node,
        tmp_path,
        fixed_origin=fixed_origin,
        plugin_enabled=False,
        ready_status=expected,
    ) as ui:
        with httpx.Client(base_url=ui.url, timeout=60, trust_env=False) as client:
            # The exact same native artifact is used in both modes. No gateway
            # runs when the plugin is disabled: missing origin stays invalid.
            assert client.get("/login").status_code == expected
            if not fixed_origin:
                assert (
                    client.post("/api/auth/login", headers={"Origin": ui.url}, json={"key": ui.password}).status_code
                    == 503
                )
                return
            assert client.get("/login", headers={"Host": "other.example"}).status_code == 421
            assert (
                client.post(
                    "/api/auth/login", headers={"Origin": "http://other.example"}, json={"key": ui.password}
                ).status_code
                == 403
            )
            login = client.post("/api/auth/login", headers={"Origin": ui.url}, json={"key": ui.password})
            assert login.status_code == 200
            assert client.get("/api/contextdb/users").status_code == 404
            assert client.post("/api/auth/logout", headers={"Origin": ui.url}).status_code == 200


def test_dynamic_session_survives_restart_but_requires_its_private_session_directory(
    contextdb_deployment: ContextDBDeployment, tmp_path: Path
) -> None:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "contextbase-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the matching production UI before running this story")
    port = free_port()
    password = "synthetic-ui-" + secrets.token_urlsafe(24)
    with ui_owner(contextdb_deployment, server, node, tmp_path, fixed_origin=False, port=port, password=password) as ui:
        login = httpx.post(ui.url + "/api/auth/login", headers={"Origin": ui.url}, json={"key": password})
        assert login.status_code == 200
        cookie = login.headers["set-cookie"].split(";", 1)[0]

    other = tmp_path / "different-session-directory"
    other.mkdir()
    # Even with the same password and internal origin, another deployment's
    # empty session storage must not authorize this signed token.
    with ui_owner(contextdb_deployment, server, node, other, fixed_origin=False, port=port, password=password) as ui:
        assert httpx.get(ui.url + "/api/contextdb/users", headers={"Cookie": cookie}).status_code == 401

    with ui_owner(contextdb_deployment, server, node, tmp_path, fixed_origin=False, port=port, password=password) as ui:
        # Manually replay the token to test server persistence across restart /
        # Host changes. This does not claim browsers transfer host-only cookies.
        headers = {"Host": "192.0.2.12:3306", "Origin": "http://192.0.2.12:3306", "Cookie": cookie}
        assert httpx.get(ui.url + "/api/contextdb/users", headers=headers).status_code == 200
        assert httpx.post(ui.url + "/api/auth/logout", headers=headers).status_code == 200

    with ui_owner(contextdb_deployment, server, node, tmp_path, fixed_origin=False, port=port, password=password) as ui:
        assert httpx.get(ui.url + "/api/contextdb/users", headers={"Cookie": cookie}).status_code == 401


def test_connect_page_derives_the_external_api_endpoint(
    contextdb_deployment: ContextDBDeployment, tmp_path: Path
) -> None:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "contextbase-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the matching production UI before running this story")
    with ui_owner(
        contextdb_deployment,
        server,
        node,
        tmp_path,
        fixed_origin=False,
        extra_env={"CONTEXTBASE_CP_PUBLIC_API_PORT": "9999"},
    ) as ui:
        with httpx.Client(base_url=ui.url, timeout=60, trust_env=False) as client:
            for host in ("192.0.2.10:3306", "192.0.2.11:3306"):
                headers = {
                    "Host": host,
                    "Origin": "http://" + host,
                    "X-ContextDB-External-Origin": "http://evil.example",
                }
                login = client.post("/api/auth/login", headers=headers, json={"key": ui.password})
                assert login.status_code == 200
                cookie = login.headers["set-cookie"].split(";", 1)[0]
                page = client.get("/connect?bank_id=team", headers={**headers, "Cookie": cookie})
                assert page.status_code == 200
                assert "http://" + host.split(":")[0] + ":9999" in page.text
                assert "API_ENDPOINT" not in page.text
                assert "evil.example" not in page.text
                assert contextdb_deployment.server.url not in page.text
                assert ui.admin_key not in page.text


def test_fixed_origin_ignores_a_client_supplied_external_origin(
    contextdb_deployment: ContextDBDeployment, tmp_path: Path
) -> None:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "contextbase-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the matching production UI before running this story")
    with ui_owner(
        contextdb_deployment,
        server,
        node,
        tmp_path,
        extra_env={"CONTEXTBASE_CP_PUBLIC_API_PORT": "9999"},
    ) as ui:
        with httpx.Client(base_url=ui.url, timeout=60, trust_env=False) as client:
            headers = {"Origin": ui.url, "X-ContextDB-External-Origin": "http://evil.example"}
            assert client.post("/api/auth/login", headers=headers, json={"key": ui.password}).status_code == 200
            page = client.get("/connect?bank_id=team", headers=headers)
            assert page.status_code == 200
            assert "http://127.0.0.1:9999" in page.text
            assert "evil.example" not in page.text
            assert ui.admin_key not in page.text
