"""ContextBase-embed daemon lifecycle management for Cursor plugin.

Manages three connection modes:
  1. External API -- user provides contextbaseApiUrl (skip daemon entirely)
  2. Existing local server -- user already has contextbase running
  3. Auto-managed daemon -- plugin starts/stops contextbase-embed
"""

import os
import platform
import subprocess
import time
import urllib.error
import urllib.request

from .client import USER_AGENT
from .llm import detect_llm_config, get_llm_env_vars
from .state import write_state

DAEMON_STATE_FILE = "daemon.json"
PROFILE_NAME = "cursor"


def _get_embed_command(config: dict) -> list[str]:
    """Use the configured engine distribution and its ContextBase executable."""
    embed_path = config.get("embedPackagePath")
    if embed_path:
        return ["uv", "run", "--directory", embed_path, "contextbase-embed"]
    package = config.get("embedPackage") or os.environ.get("CONTEXTBASE_EMBED_PACKAGE")
    if not package:
        raise RuntimeError("Set CONTEXTBASE_EMBED_PACKAGE or embedPackagePath for local engine mode.")
    return ["uvx", "--quiet", "--from", package, "contextbase-embed"]


def _run_embed(config: dict, args: list, env: dict = None, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a contextbase-embed command and return the result."""
    cmd = _get_embed_command(config) + args
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )


def _is_embed_available(config: dict) -> bool:
    """Quick check if contextbase-embed is available on PATH."""
    import shutil

    embed_path = config.get("embedPackagePath")
    if embed_path:
        return os.path.isdir(embed_path)
    return shutil.which("uvx") is not None or shutil.which("contextbase-embed") is not None


def _check_health(base_url: str, timeout: int = 2) -> bool:
    """Quick health check against a ContextBase server."""
    try:
        url = f"{base_url.rstrip('/')}/health"
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def get_api_url(config: dict, debug_fn=None, allow_daemon_start: bool = False) -> str:
    """Determine the API URL.

    Resolution order:
      1. ``contextbaseApiUrl`` configured → use it (explicit override wins).
      2. A local server is already healthy on the configured port → use it
         (preserves the "developer already started a daemon" path).
      3. ``useLocalDaemon: True`` (opt-in) AND ``allow_daemon_start=True``
         (recall path does not auto-start daemons) → auto-start the embed
         daemon and use it.
      4. Otherwise require an explicit API URL; never fall back to another service.
    """
    # Mode 1: explicit external API
    external_url = config.get("contextbaseApiUrl")
    if external_url:
        if debug_fn:
            debug_fn(f"Using configured API URL: {external_url}")
        return external_url

    port = config.get("apiPort", 9077)
    base_url = f"http://127.0.0.1:{port}"

    # Mode 2: a server is already running locally
    if _check_health(base_url):
        if debug_fn:
            debug_fn(f"Found running local server on port {port}")
        return base_url

    # Mode 3: opt-in auto-managed daemon
    if config.get("useLocalDaemon", False) and allow_daemon_start:
        if debug_fn:
            debug_fn(f"useLocalDaemon=True, no server on port {port} — starting daemon")
        try:
            _ensure_daemon_running(config, port, debug_fn)
            return base_url
        except Exception as e:
            raise RuntimeError(
                "ContextBase local daemon could not start; configure contextbaseApiUrl to use an external service."
            ) from e

    raise ValueError("Set CONTEXTBASE_API_URL/contextbaseApiUrl or start a local ContextBase server.")


def _ensure_daemon_running(config: dict, port: int, debug_fn=None):
    """Start the contextbase-embed daemon if not already running."""
    if not _is_embed_available(config):
        raise RuntimeError(
            "contextbase-embed not found (uvx not on PATH). "
            "Install with: pip install contextbase-embed, or set contextbaseApiUrl."
        )

    base_url = f"http://127.0.0.1:{port}"

    try:
        llm_config = detect_llm_config(config)
    except RuntimeError as e:
        raise RuntimeError(f"Cannot start daemon: {e}") from e

    llm_env = get_llm_env_vars(llm_config)

    daemon_env = dict(llm_env)
    idle_timeout = config.get("daemonIdleTimeout", 300)
    daemon_env["HINDSIGHT_EMBED_DAEMON_IDLE_TIMEOUT"] = str(idle_timeout)

    if platform.system() == "Darwin":
        daemon_env["HINDSIGHT_API_EMBEDDINGS_LOCAL_FORCE_CPU"] = "1"
        daemon_env["HINDSIGHT_API_RERANKER_LOCAL_FORCE_CPU"] = "1"

    # Step 1: Configure profile
    if debug_fn:
        debug_fn(f'Configuring "{PROFILE_NAME}" profile...')

    profile_args = [
        "profile",
        "create",
        PROFILE_NAME,
        "--merge",
        "--port",
        str(port),
    ]
    for env_name, env_val in daemon_env.items():
        if env_val:
            profile_args.extend(["--env", f"{env_name}={env_val}"])

    try:
        result = _run_embed(config, profile_args, daemon_env, timeout=10)
        if result.returncode != 0:
            if debug_fn:
                debug_fn(f"Profile create stderr: {result.stderr.strip()}")
            raise RuntimeError(f"Profile create failed (exit {result.returncode}): {result.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Profile create timed out")
    except FileNotFoundError:
        raise RuntimeError(
            "contextbase-embed not found. Install with: pip install contextbase-embed "
            "or set contextbaseApiUrl for external API mode."
        )

    # Step 2: Start daemon
    if debug_fn:
        debug_fn("Starting daemon...")

    try:
        result = _run_embed(
            config,
            ["daemon", "--profile", PROFILE_NAME, "start"],
            daemon_env,
            timeout=30,
        )
        if debug_fn:
            debug_fn(f"Daemon start exit={result.returncode} stdout={result.stdout.strip()}")
        if result.returncode != 0 and "already running" not in result.stderr.lower():
            raise RuntimeError(f"Daemon start failed (exit {result.returncode}): {result.stderr}")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Daemon start timed out")

    # Step 3: Wait for ready
    if debug_fn:
        debug_fn("Waiting for daemon to be ready...")

    for attempt in range(30):
        if _check_health(base_url):
            if debug_fn:
                debug_fn(f"Daemon ready after {attempt + 1} attempts")
            write_state(
                DAEMON_STATE_FILE,
                {
                    "port": port,
                    "started_by_plugin": True,
                    "started_at": time.time(),
                    "pid": os.getpid(),
                },
            )
            return
        time.sleep(1)

    raise RuntimeError("Daemon failed to become ready within 30 seconds")
