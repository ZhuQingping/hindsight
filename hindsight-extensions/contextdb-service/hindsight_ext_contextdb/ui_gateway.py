"""Opt-in direct-HTTP UI ingress; the community Next server stays unchanged."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import socket
import sys
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from multidict import CIMultiDict
from yarl import URL

from .environment import service_env

_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


def enabled() -> bool:
    """Never adapt an absent/disabled plugin or an explicitly configured origin."""
    return service_env("CP_CONTEXTDB_ENABLED") == "true" and not service_env("CP_PUBLIC_ORIGIN")


def external_origin(headers: CIMultiDict[str]) -> str:
    hosts = headers.getall("Host", [])
    if len(hosts) != 1 or not hosts[0] or re.search(r"[\s\\/@?#%,]", hosts[0]):
        raise web.HTTPMisdirectedRequest(text="Unexpected request host")
    try:
        url = URL("http://" + hosts[0])
        if not url.host or not url.port or url.port > 65535:
            raise ValueError("Invalid HTTP authority")
        return str(url.origin())
    except ValueError as exc:
        raise web.HTTPMisdirectedRequest(text="Unexpected request host") from exc


def clean_headers(headers: Mapping[str, str]) -> CIMultiDict[str]:
    # Connection is a repeatable comma-list; every field nominates hop-only
    # headers. Reading only the first lets later nominations leak across hops.
    nominated = {
        name.strip().lower() for value in CIMultiDict(headers).getall("Connection", []) for name in value.split(",")
    }
    return CIMultiDict((key, value) for key, value in headers.items() if key.lower() not in _HOP_HEADERS | nominated)


async def reject_redirect(
    _session: aiohttp.ClientSession, _context: SimpleNamespace, params: aiohttp.TraceRequestRedirectParams
) -> None:
    # ws_connect has no allow_redirects switch in pinned aiohttp. Stop its
    # redirect before any follow-up connection, including same-origin targets;
    # HTTP forwarding already uses allow_redirects=False. Close the unconsumed
    # response so a redirect body cannot retain an upstream connection.
    response = params.response
    error = aiohttp.WSServerHandshakeError(
        response.request_info, response.history, status=response.status, headers=response.headers
    )
    response.close()
    raise error


class Gateway:
    def __init__(self, upstream: str, internal_origin: str) -> None:
        self.upstream = upstream
        self.internal_origin = str(URL(internal_origin).origin())
        authority = URL(internal_origin).host_port_subcomponent
        if not authority:
            raise ValueError("A valid internal UI origin is required")
        self.internal_authority = authority

    async def session(self, app: web.Application) -> AsyncIterator[None]:
        # This single-loop ingress owns its session through aiohttp's cleanup
        # context. It needs a DummyCookieJar and byte-preserving transport:
        # default cookie retention would mix different browsers' credentials.
        trace = aiohttp.TraceConfig()
        trace.on_request_redirect.append(reject_redirect)
        async with aiohttp.ClientSession(
            cookie_jar=aiohttp.DummyCookieJar(),
            auto_decompress=False,
            skip_auto_headers={"Accept-Encoding"},
            trust_env=False,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=None),
            trace_configs=[trace],
        ) as session:
            app[_SESSION] = session
            yield

    def request_headers(self, request: web.Request, origin: str) -> CIMultiDict[str]:
        writes = request.method not in {"GET", "HEAD", "OPTIONS"}
        websocket = request.headers.get("Upgrade", "").lower() == "websocket"
        # Check the browser's external authority BEFORE translating Origin.
        # Blind rewriting would turn cross-site requests into trusted writes.
        if writes or websocket:
            if request.headers.getall("Origin", []) != [origin] or request.headers.get("Sec-Fetch-Site") not in {
                None,
                "same-origin",
            }:
                raise web.HTTPForbidden(text="A same-origin request is required")
        headers = clean_headers(request.headers)
        for name in tuple(headers):
            if name.lower() == "forwarded" or name.lower().startswith("x-forwarded-"):
                headers.popall(name, None)
        headers["Host"] = self.internal_authority
        if request.headers.get("Origin") == origin:
            headers["Origin"] = self.internal_origin
        # These headers are used by Next's routing and server-action checks.
        for name in ("Referer", "Next-Url"):
            value = headers.get(name)
            if value and (value == origin or value.startswith(origin + "/")):
                headers[name] = self.internal_origin + value[len(origin) :]
        return headers

    def response_headers(self, headers: Mapping[str, str], origin: str) -> CIMultiDict[str]:
        result = clean_headers(headers)
        for name in ("Location", "X-Action-Redirect"):
            value = result.get(name)
            if value:
                # A root URL may start its query/fragment without a slash.
                # Next action headers additionally allow an exact ;push/replace
                # suffix. Match delimiters, never a similar external authority.
                for internal in (self.internal_origin, self.upstream):
                    if (
                        value == internal
                        or value.startswith(tuple(internal + delimiter for delimiter in ("/", "?", "#")))
                        or (name == "X-Action-Redirect" and value in {internal + ";push", internal + ";replace"})
                    ):
                        result[name] = origin + value[len(internal) :]
                        break
        # Session cookies remain host-only. Their native namespace/signature use
        # a stable, port-scoped internal origin; no Cookie rewriting is needed.
        return result

    async def handle(self, request: web.Request) -> web.StreamResponse:
        origin = external_origin(CIMultiDict(request.headers))
        headers = self.request_headers(request, origin)
        if not request.raw_path.startswith("/"):
            raise web.HTTPBadRequest(text="An origin-form request target is required")
        target = URL(self.upstream + request.raw_path, encoded=True)
        session = request.app[_SESSION]
        response: web.StreamResponse | None = None
        try:
            if request.headers.get("Upgrade", "").lower() == "websocket":
                return await self.websocket(request, session, target, headers)
            async with session.request(
                request.method,
                target,
                headers=headers,
                data=request.content if request.can_read_body else None,
                allow_redirects=False,
            ) as upstream:
                response = web.StreamResponse(
                    status=upstream.status, headers=self.response_headers(upstream.headers, origin)
                )
                await response.prepare(request)
                async for chunk in upstream.content.iter_any():
                    await response.write(chunk)
                await response.write_eof()
                return response
        except aiohttp.WSServerHandshakeError as exc:
            if 100 <= exc.status < 200:
                # An invalid 101 lacks a verified WebSocket handshake. Never
                # claim a protocol switch to the browser after validation failed.
                raise web.HTTPBadGateway(text="UI WebSocket upgrade failed") from exc
            # Preserve native authorization/rate-limit failures, not an ingress
            # 500. aiohttp has consumed the failed upgrade; don't forward its
            # entity length/encoding while returning an empty HTTP response.
            headers = self.response_headers(exc.headers or {}, origin)
            for name in ("Content-Length", "Content-Encoding"):
                headers.popall(name, None)
            headers["Cache-Control"] = "no-store"
            return web.Response(status=exc.status, headers=headers)
        except (aiohttp.ClientError, TimeoutError, ConnectionError) as exc:
            if response is not None and response.prepared:
                # Once headers are sent, terminate the truncated stream. A new
                # HTTP error response would corrupt the body/status contract.
                response.force_close()
                if request.transport is not None:
                    request.transport.abort()
                return response
            raise web.HTTPBadGateway(text="UI service is unavailable") from exc

    async def websocket(
        self, request: web.Request, session: aiohttp.ClientSession, target: URL, headers: CIMultiDict[str]
    ) -> web.WebSocketResponse:
        protocols = tuple(
            value.strip() for value in headers.get("Sec-WebSocket-Protocol", "").split(",") if value.strip()
        )
        for name in tuple(headers):
            if name.lower().startswith("sec-websocket-"):
                headers.popall(name, None)
        async with session.ws_connect(target, headers=headers, protocols=protocols) as upstream:
            response = web.WebSocketResponse(protocols=(upstream.protocol,) if upstream.protocol else ())
            await response.prepare(request)

            async def forward(
                source: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
                destination: aiohttp.ClientWebSocketResponse | web.WebSocketResponse,
            ) -> None:
                async for message in source:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type == aiohttp.WSMsgType.BINARY:
                        await destination.send_bytes(message.data)

            tasks = [asyncio.create_task(forward(response, upstream)), asyncio.create_task(forward(upstream, response))]
            close_code = 1000
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                close_code = upstream.close_code or response.close_code or 1000
                if close_code in {1005, 1006, 1015} or any(task.exception() is not None for task in done):
                    close_code = 1011
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.gather(upstream.close(code=close_code), response.close(code=close_code))
            return response


_SESSION = web.AppKey("ui_gateway_session", aiohttp.ClientSession)


def create_app(upstream: str, internal_origin: str) -> web.Application:
    gateway = Gateway(upstream, internal_origin)
    app = web.Application(client_max_size=0)
    app.cleanup_ctx.append(gateway.session)
    app.router.add_route("*", "/{path:.*}", gateway.handle)
    return app


async def serve(source_root: Path, *, development: bool = False) -> int:
    port = int(service_env("CP_PORT", "9999"))
    if not 1 <= port <= 65535:
        raise ValueError("UI port must be within 1..65535")
    # Reserve an ephemeral backend address. Its socket is private; the stable
    # logical origin depends on the external port, never EIP or ephemeral port.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        internal_port = reservation.getsockname()[1]
    # A loopback hostname also satisfies Next dev's HMR origin allowlist; only
    # the stable external port enters native cookie/signature identity.
    internal_origin = str(URL(f"http://127.0.0.1:{port}").origin())
    environment = dict(os.environ)
    for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
        environment[prefix + "PUBLIC_ORIGIN"] = internal_origin
        environment[prefix + "HOST"] = "127.0.0.1"
        environment[prefix + "PORT"] = str(internal_port)
    environment.update(HOSTNAME="127.0.0.1", PORT=str(internal_port))
    if development:
        environment["NODE_ENV"] = "development"
        command = [
            "node",
            str(source_root / "node_modules/next/dist/bin/next"),
            "dev",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(internal_port),
        ]
        directory = source_root / "contextbase-control-plane"
    else:
        directory = source_root / "contextbase-control-plane/standalone"
        command = ["node", str(directory / "server.js")]
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM) + ((signal.SIGBREAK,) if sys.platform == "win32" else ())
    previous = {sig: signal.getsignal(sig) for sig in signals}
    for sig in signals:
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stopped.set))
    child = None
    runner = None
    try:
        # Keep Node (and Next dev workers) in the caller's supervised process
        # group/Windows Job Object so its forced-stop fallback still owns them.
        child = await asyncio.create_subprocess_exec(*command, cwd=directory, env=environment)
        runner = web.AppRunner(
            create_app(f"http://127.0.0.1:{internal_port}", internal_origin),
            auto_decompress=False,
            handler_cancellation=True,
            shutdown_timeout=5,
        )
        await runner.setup()
        await web.TCPSite(runner, service_env("CP_HOST", "0.0.0.0"), port).start()
        tasks = [asyncio.create_task(child.wait()), asyncio.create_task(stopped.wait())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            return child.returncode if child.returncode is not None else 0
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        try:
            if runner:
                await runner.cleanup()
        finally:
            try:
                if child:
                    if child.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), timeout=5)
                    except TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            child.kill()
                        await child.wait()
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)


def run(source_root: Path, *, development: bool = False) -> None:
    if not enabled():
        raise ValueError("UI gateway requires enabled ContextDB and an absent public origin")
    if sys.platform == "win32":
        from .windows import own_process_tree

        own_process_tree()
    raise SystemExit(asyncio.run(serve(source_root, development=development)))
