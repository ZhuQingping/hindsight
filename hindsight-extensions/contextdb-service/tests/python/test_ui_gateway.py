"""Real HTTP transports verify the opt-in gateway's trust/byte boundaries."""

from __future__ import annotations

import asyncio
import gzip
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import web
from multidict import CIMultiDict
from yarl import URL

from hindsight_ext_contextdb import launch, ui_gateway

INTERNAL = "http://contextdb-ui.internal:9999"
EXTERNAL = "http://192.0.2.10:3306"


@asynccontextmanager
async def running(app: web.Application) -> AsyncIterator[str]:
    runner = web.AppRunner(app, auto_decompress=False, handler_cancellation=True, shutdown_timeout=2)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("flag", [None, "", "false", "1", "TRUE", "true"])
@pytest.mark.parametrize("origin", [None, "", "https://fixed.example", "invalid"])
def test_gateway_requires_explicit_plugin_enablement_and_no_origin(
    monkeypatch: pytest.MonkeyPatch, flag: str | None, origin: str | None
) -> None:
    for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
        for name in ("CONTEXTDB_ENABLED", "PUBLIC_ORIGIN"):
            monkeypatch.delenv(prefix + name, raising=False)
    if flag is not None:
        monkeypatch.setenv("HINDSIGHT_CP_CONTEXTDB_ENABLED", flag)
    if origin is not None:
        monkeypatch.setenv("HINDSIGHT_CP_PUBLIC_ORIGIN", origin)
    assert ui_gateway.enabled() == (flag == "true" and not origin)
    monkeypatch.setenv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "false")
    assert not ui_gateway.enabled()


def test_empty_public_alias_clears_old_internal_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "true")
    monkeypatch.setenv("HINDSIGHT_CP_PUBLIC_ORIGIN", "https://stale.example")
    monkeypatch.setenv("CONTEXTBASE_CP_PUBLIC_ORIGIN", "")
    assert ui_gateway.enabled()


@pytest.mark.parametrize("flag", [None, "false", "true"])
@pytest.mark.parametrize("origin", [None, "", "http://fixed.example", "invalid"])
def test_launcher_keeps_native_node_path_unless_dynamic_plugin_is_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str | None, origin: str | None
) -> None:
    environment = {"PATH": os.environ.get("PATH", "")}
    if flag is not None:
        environment["CONTEXTBASE_CP_CONTEXTDB_ENABLED"] = flag
    if origin is not None:
        environment["CONTEXTBASE_CP_PUBLIC_ORIGIN"] = origin
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(launch, "verify_ui_build", Mock())
    monkeypatch.setattr(launch, "load_deployment_secrets", Mock())
    server = tmp_path / "contextbase-control-plane/standalone/server.js"
    server.parent.mkdir(parents=True)
    server.touch()
    native = Mock(side_effect=RuntimeError("native"))
    gateway = Mock(side_effect=RuntimeError("gateway"))
    monkeypatch.setattr(os, "execvp", native)
    monkeypatch.setattr(launch, "run_ui_gateway", gateway)
    dynamic = flag == "true" and not origin
    with pytest.raises(RuntimeError, match="gateway" if dynamic else "native"):
        launch.launch("ui", tmp_path, tmp_path)
    assert gateway.call_count == int(dynamic)
    assert native.call_count == int(not dynamic)
    assert os.environ.get("CONTEXTBASE_CP_PUBLIC_ORIGIN") == origin


@pytest.mark.parametrize(
    "host", ["", "evil/path", "user@evil", "evil?x", "evil#x", "evil,other", "evil:0", "evil:99999", "evil\\path"]
)
def test_malformed_hosts_fail_closed(host: str) -> None:
    with pytest.raises(web.HTTPMisdirectedRequest):
        ui_gateway.external_origin(CIMultiDict({"Host": host}))


def test_duplicate_hosts_fail_closed() -> None:
    with pytest.raises(web.HTTPMisdirectedRequest):
        ui_gateway.external_origin(CIMultiDict([("Host", "a"), ("Host", "b")]))


def test_direct_gateway_entry_rejects_disabled_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "false")
    with pytest.raises(ValueError, match="enabled ContextDB"):
        ui_gateway.run(tmp_path)


async def test_origin_checked_before_rewrite_and_forwarded_identity_removed() -> None:
    calls: list[str] = []

    async def backend(request: web.Request) -> web.Response:
        calls.append(request.raw_path)
        assert request.headers["Host"] == "contextdb-ui.internal:9999"
        assert request.headers["Origin"] == INTERNAL
        assert request.headers["Referer"] == INTERNAL + "/login"
        assert not any(key.lower().startswith("x-forwarded-") for key in request.headers)
        assert "Forwarded" not in request.headers
        assert await request.read() == b"login-body"
        return web.Response(status=200)

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                headers = {
                    "Host": "192.0.2.10:3306",
                    "Origin": EXTERNAL,
                    "Referer": EXTERNAL + "/login",
                    "X-Forwarded-Proto": "https",
                    "X-Forwarded-Host": "evil",
                    "Forwarded": "host=evil",
                }
                for origin in ("http://evil", "https://192.0.2.10:3306", "null", ""):
                    async with client.post(url + "/login", headers={**headers, "Origin": origin}) as response:
                        assert response.status == 403
                assert not calls
                async with client.post(
                    URL(url + "/login?q=a%2Fb&q=c+d", encoded=True), headers=headers, data=b"login-body"
                ) as response:
                    assert response.status == 200
                assert calls == ["/login?q=a%2Fb&q=c+d"]


async def test_redirects_cookies_and_compressed_uploads_preserve_browser_boundaries() -> None:
    payload = gzip.compress(b"binary upload\x00" * 100)

    async def backend(request: web.Request) -> web.Response:
        if request.path == "/upload":
            assert request.headers["Content-Encoding"] == "gzip"
            assert await request.read() == payload
            return web.Response(body=payload, headers={"Content-Encoding": "gzip"})
        if request.path == "/cookies":
            assert request.headers.get("Cookie") == "browser=explicit"
            return web.Response(text="separate-browser")
        response = web.Response(status=307, headers={"Location": INTERNAL + "/login?returnTo=%2F"})
        response.headers.add("Set-Cookie", "one=1; Path=/; HttpOnly; SameSite=Lax")
        response.headers.add("Set-Cookie", "two=2; Path=/; HttpOnly")
        return response

    app = web.Application()
    app.router.add_route("*", "/{path:.*}", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False) as client:
                headers = {"Host": "192.0.2.10:3306", "Origin": EXTERNAL}
                async with client.get(url + "/", headers=headers, allow_redirects=False) as response:
                    assert response.status == 307
                    assert response.headers["Location"] == EXTERNAL + "/login?returnTo=%2F"
                    assert len(response.headers.getall("Set-Cookie")) == 2
                async with client.get(url + "/cookies", headers={**headers, "Cookie": "browser=explicit"}) as response:
                    assert response.status == 200
                async with client.post(
                    url + "/upload", headers={**headers, "Content-Encoding": "gzip"}, data=payload
                ) as response:
                    assert response.status == 200
                    assert response.headers["Content-Encoding"] == "gzip"
                    assert await response.read() == payload


async def test_sse_is_forwarded_before_upstream_finishes() -> None:
    release = asyncio.Event()

    async def backend(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await response.write(b"data: first\n\n")
        await release.wait()
        await response.write(b"data: last\n\n")
        return response

    app = web.Application()
    app.router.add_get("/events", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.get(url + "/events", headers={"Host": "192.0.2.10:3306"}) as response:
                    try:
                        assert await asyncio.wait_for(response.content.readexactly(13), timeout=2) == b"data: first\n\n"
                    finally:
                        release.set()
                    assert await response.read() == b"data: last\n\n"


async def test_browser_disconnect_releases_streaming_upstream() -> None:
    released = asyncio.Event()

    async def backend(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        try:
            await response.write(b"data: first\n\n")
            await asyncio.Event().wait()
        finally:
            released.set()
        return response

    app = web.Application()
    app.router.add_get("/events", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                response = await client.get(url + "/events", headers={"Host": "192.0.2.10:3306"})
                await response.content.readexactly(13)
                response.close()
                await asyncio.wait_for(released.wait(), timeout=2)


async def test_websocket_requires_same_origin_and_forwards_frames() -> None:
    async def backend(request: web.Request) -> web.WebSocketResponse:
        assert request.headers["Origin"] == INTERNAL
        response = web.WebSocketResponse()
        await response.prepare(request)
        async for message in response:
            if message.type == aiohttp.WSMsgType.TEXT:
                await response.send_str(message.data)
        return response

    app = web.Application()
    app.router.add_get("/socket", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                with pytest.raises(aiohttp.WSServerHandshakeError) as failure:
                    await client.ws_connect(
                        url + "/socket", headers={"Host": "192.0.2.10:3306", "Origin": "http://evil"}
                    )
                assert failure.value.status == 403
                async with client.ws_connect(
                    url + "/socket", headers={"Host": "192.0.2.10:3306", "Origin": EXTERNAL}
                ) as socket:
                    await socket.send_str("native-ui-hmr")
                    assert (await socket.receive(timeout=2)).data == "native-ui-hmr"


@pytest.mark.parametrize("status", [401, 403, 429, 503])
async def test_websocket_upgrade_rejection_keeps_upstream_status(status: int) -> None:
    async def backend(request: web.Request) -> web.Response:
        return web.Response(status=status, body=b"denied", headers={"Retry-After": "7"})

    app = web.Application()
    app.router.add_get("/socket", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                with pytest.raises(aiohttp.WSServerHandshakeError) as failure:
                    await client.ws_connect(url + "/socket", headers={"Host": "192.0.2.10:3306", "Origin": EXTERNAL})
                assert failure.value.status == status
                assert failure.value.headers is not None
                assert failure.value.headers["Retry-After"] == "7"


async def test_duplicate_connection_fields_strip_all_nominated_headers() -> None:
    async def backend(request: web.Request) -> web.Response:
        assert "X-First-Hop" not in request.headers
        assert "X-Second-Hop" not in request.headers
        assert "Proxy-Connection" not in request.headers
        return web.Response(
            headers=CIMultiDict(
                [
                    ("Connection", "X-First-Response"),
                    ("Connection", "X-Second-Response"),
                    ("X-First-Response", "private"),
                    ("X-Second-Response", "private"),
                ]
            )
        )

    app = web.Application()
    app.router.add_get("/headers", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                headers = CIMultiDict(
                    [
                        ("Host", "192.0.2.10:3306"),
                        ("Connection", "X-First-Hop"),
                        ("Connection", "X-Second-Hop"),
                        ("X-First-Hop", "private"),
                        ("X-Second-Hop", "private"),
                        ("Proxy-Connection", "keep-alive"),
                    ]
                )
                async with client.get(url + "/headers", headers=headers) as response:
                    assert response.status == 200
                    assert "X-First-Response" not in response.headers
                    assert "X-Second-Response" not in response.headers


async def test_truncated_upstream_does_not_append_a_second_http_response() -> None:
    async def backend(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={"Content-Length": "100"})
        await response.prepare(request)
        await response.write(b"partial")
        assert request.transport is not None
        request.transport.abort()
        return response

    app = web.Application()
    app.router.add_get("/stream", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            address = URL(url)
            reader, writer = await asyncio.open_connection(address.host, address.port)
            try:
                writer.write(b"GET /stream HTTP/1.1\r\nHost: 192.0.2.10:3306\r\nConnection: close\r\n\r\n")
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(), timeout=2)
                assert raw.startswith(b"HTTP/1.1 200")
                assert raw.count(b"HTTP/1.1") == 1
                assert raw.endswith(b"partial")
            finally:
                writer.close()
                await writer.wait_closed()


async def test_websocket_binary_protocol_and_server_close_code_survive_proxy() -> None:
    async def backend(request: web.Request) -> web.WebSocketResponse:
        response = web.WebSocketResponse(protocols=("contextbase",))
        await response.prepare(request)
        message = await response.receive()
        assert message.type == aiohttp.WSMsgType.BINARY
        await response.send_bytes(message.data)
        await response.close(code=4001)
        return response

    app = web.Application()
    app.router.add_get("/socket", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.ws_connect(
                    url + "/socket", headers={"Host": "192.0.2.10:3306", "Origin": EXTERNAL}, protocols=("contextbase",)
                ) as socket:
                    assert socket.protocol == "contextbase"
                    await socket.send_bytes(b"binary\x00payload")
                    assert (await socket.receive(timeout=2)).data == b"binary\x00payload"
                    await socket.receive(timeout=2)
                    assert socket.close_code == 4001


@pytest.mark.parametrize(
    "host,origin",
    [
        ("EXAMPLE.test:80", "http://example.test"),
        ("[::1]:3306", "http://[::1]:3306"),
        ("xn--bcher-kva.test:3306", "http://xn--bcher-kva.test:3306"),
    ],
)
def test_legal_authorities_have_canonical_http_origins(host: str, origin: str) -> None:
    assert ui_gateway.external_origin(CIMultiDict({"Host": host})) == origin


@pytest.mark.parametrize("case", ["missing", "duplicate", "cross-site", "same-site"])
async def test_untrusted_mutation_metadata_never_reaches_backend(case: str) -> None:
    calls: list[str] = []

    async def backend(request: web.Request) -> web.Response:
        calls.append(request.path)
        return web.Response()

    app = web.Application()
    app.router.add_post("/login", backend)
    headers = CIMultiDict({"Host": "192.0.2.10:3306"})
    if case != "missing":
        headers["Origin"] = EXTERNAL
    if case == "duplicate":
        headers.add("Origin", EXTERNAL)
    elif case in {"cross-site", "same-site"}:
        headers["Sec-Fetch-Site"] = case
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.post(url + "/login", headers=headers) as response:
                    assert response.status == 403
                assert not calls


async def test_malformed_upstream_http_is_a_controlled_gateway_error() -> None:
    async def malformed(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"not-http\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(malformed, "127.0.0.1", 0)
    async with server:
        upstream = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.get(url + "/", headers={"Host": "192.0.2.10:3306"}) as response:
                    assert response.status == 502
                    assert await response.text() == "UI service is unavailable"


@pytest.mark.parametrize("method,status", [("HEAD", 200), ("GET", 204), ("GET", 304)])
async def test_bodyless_responses_keep_status(method: str, status: int) -> None:
    async def backend(request: web.Request) -> web.Response:
        return web.Response(status=status)

    app = web.Application()
    app.router.add_route("*", "/", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.request(method, url + "/", headers={"Host": "192.0.2.10:3306"}) as response:
                    assert response.status == status
                    assert await response.read() == b""


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("cross_origin", [False, True])
async def test_websocket_redirect_is_returned_without_any_followup_request(status: int, cross_origin: bool) -> None:
    seen: list[str] = []

    async def landing(request: web.Request) -> web.Response:
        seen.append(request.path)
        return web.Response(status=403)

    collector = web.Application()
    collector.router.add_get("/landing", landing)
    async with running(collector) as destination:

        async def redirect(request: web.Request) -> web.Response:
            location = destination + "/landing" if cross_origin else upstream + "/landing"
            return web.Response(status=status, headers={"Location": location})

        app = web.Application()
        app.router.add_get("/redirect", redirect)
        app.router.add_get("/landing", landing)
        async with running(app) as upstream:
            async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
                async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as client:
                    # Send the upgrade explicitly: a front-end ws_connect()
                    # would itself follow redirects and obscure which hop did so.
                    headers = {
                        "Host": "192.0.2.10:3306",
                        "Origin": EXTERNAL,
                        "Upgrade": "websocket",
                        "Connection": "Upgrade",
                        "Sec-WebSocket-Version": "13",
                        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                        "Cookie": "synthetic=opaque",
                    }
                    async with client.get(url + "/redirect", headers=headers, allow_redirects=False) as response:
                        assert not seen, "The gateway followed an upstream redirect"
                        assert response.status == status
                        assert response.headers["Location"] == (destination if cross_origin else EXTERNAL) + "/landing"


@pytest.mark.parametrize("bad_accept", [False, True])
async def test_invalid_101_handshake_becomes_502(bad_accept: bool) -> None:
    async def backend(request: web.Request) -> web.Response:
        headers = (
            {"Upgrade": "websocket", "Connection": "Upgrade", "Sec-WebSocket-Accept": "invalid"} if bad_accept else {}
        )
        return web.Response(status=101, headers=headers)

    app = web.Application()
    app.router.add_get("/socket", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                with pytest.raises(aiohttp.WSServerHandshakeError) as failure:
                    await client.ws_connect(url + "/socket", headers={"Host": "192.0.2.10:3306", "Origin": EXTERNAL})
                assert failure.value.status == 502


@pytest.mark.parametrize(
    "name,suffix",
    [
        ("Location", "?q=a%2Fb"),
        ("Location", "#section"),
        ("X-Action-Redirect", ";push"),
        ("X-Action-Redirect", ";replace"),
        ("X-Action-Redirect", "?q=a%2Fb;push"),
        ("Location", "/path?q=a%2Fb#section"),
    ],
)
async def test_internal_root_redirect_delimiters_keep_external_browser_origin(name: str, suffix: str) -> None:
    async def backend(request: web.Request) -> web.Response:
        return web.Response(status=307, headers={name: INTERNAL + suffix})

    app = web.Application()
    app.router.add_get("/redirect", backend)
    async with running(app) as upstream:
        async with running(ui_gateway.create_app(upstream, INTERNAL)) as url:
            async with aiohttp.ClientSession() as client:
                async with client.get(
                    url + "/redirect", headers={"Host": "192.0.2.10:3306"}, allow_redirects=False
                ) as response:
                    assert response.headers[name] == EXTERNAL + suffix


@pytest.mark.parametrize(
    "value",
    [
        INTERNAL + "@external.test/path",
        INTERNAL + ".external.test/path",
        "http://contextdb-ui.internal.external.test:9999/path",
        INTERNAL + ";push-more",
    ],
)
def test_similar_external_authority_and_unknown_action_suffix_are_not_rewritten(value: str) -> None:
    gateway = ui_gateway.Gateway("http://127.0.0.1:12345", INTERNAL)
    for name in ("Location", "X-Action-Redirect"):
        assert gateway.response_headers({name: value}, EXTERNAL)[name] == value
