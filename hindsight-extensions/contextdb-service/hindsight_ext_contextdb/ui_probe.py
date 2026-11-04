"""Probe local UI readiness while preserving its configured public Host guard."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

import aiohttp
from yarl import URL

from .environment import service_env


async def healthy() -> bool:
    origin = service_env("CP_PUBLIC_ORIGIN", "")
    port = service_env("CP_PORT", "9999")
    try:
        local_port = int(port)
        if not 1 <= local_port <= 65535:
            return False
        canonical_host = f"127.0.0.1:{local_port}"
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                return False
            if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
                return False
            canonical_host = URL(origin).host_port_subcomponent
            if not canonical_host:
                return False
        # Connect locally even behind a TLS gateway; only the configured public
        # Host is supplied (canonical case, default port, IDNA and IPv6). Never weaken the proxy's Host check for health paths.
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3), trust_env=False) as session:
            async with session.get(
                f"http://127.0.0.1:{local_port}/api/health",
                headers={"Host": canonical_host},
                allow_redirects=False,
            ) as response:
                return response.status == 200
    except (ValueError, aiohttp.ClientError, TimeoutError):
        return False


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(healthy()) else 1)
