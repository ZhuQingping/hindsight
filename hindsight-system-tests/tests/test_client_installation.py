"""Blackbox installer story using a local HTTPS artifact origin, without a memory server.

Run directly with Python: this distribution test needs no database or model credentials.
The tiny fixture executables exercise platform selection and integrity, not CLI business APIs.
"""

import hashlib
import os
import shutil
import ssl
import subprocess
import tempfile
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install-contextbase.sh"
VERSION = "1.2.3"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class ClientInstallationStory(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = tempfile.TemporaryDirectory(prefix="contextbase-download-")
        cls.origin = Path(cls.fixture.name)
        cls.cert = cls.origin / "cert.pem"
        key = cls.origin / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=127.0.0.1",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
                "-keyout",
                str(key),
                "-out",
                str(cls.cert),
            ],
            check=True,
            capture_output=True,
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(cls.origin)))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cls.cert, key)
        cls.server.socket = tls.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"https://127.0.0.1:{cls.server.server_port}/downloads"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.fixture.cleanup()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="contextbase-install-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.bin_dir = self.home / "directory with spaces" / "bin"
        tools = self.home / "tools"
        tools.mkdir()
        uname = tools / "uname"
        uname.write_text('#!/bin/sh\ncase "$1" in -s) echo "$FIXTURE_OS";; -m) echo "$FIXTURE_ARCH";; esac\n')
        uname.chmod(0o755)
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("CONTEXTBASE_")}
        self.environment.update(
            HOME=str(self.home),
            PATH=f"{tools}:{os.environ['PATH']}",
            CURL_CA_BUNDLE=str(self.cert),
            NO_PROXY="127.0.0.1",
            no_proxy="127.0.0.1",
            FIXTURE_OS="Linux",
            FIXTURE_ARCH="x86_64",
        )
        for platform in ["linux-amd64", "linux-arm64", "darwin-amd64", "darwin-arm64"]:
            directory = self.origin / "downloads" / "contextbase-cli" / VERSION / platform
            directory.mkdir(parents=True, exist_ok=True)
            binary = directory / "contextbase"
            binary.write_text(f"#!/bin/sh\nprintf 'fixture-{platform}\\n'\n")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            (directory / "SHA256SUMS").write_text(f"{digest}  contextbase\n")

    def install(self, *extra: str, base_url: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--base-url",
                base_url or self.base_url,
                "--version",
                VERSION,
                "--bin-dir",
                str(self.bin_dir),
                *extra,
            ],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=15,
        )

    def checksum_file(self) -> Path:
        return self.origin / "downloads" / "contextbase-cli" / VERSION / "linux-amd64" / "SHA256SUMS"

    def test_first_install_selects_all_four_platforms(self) -> None:
        for system, arch, platform in [
            ("Linux", "x86_64", "linux-amd64"),
            ("Linux", "aarch64", "linux-arm64"),
            ("Darwin", "x86_64", "darwin-amd64"),
            ("Darwin", "arm64", "darwin-arm64"),
        ]:
            with self.subTest(platform=platform):
                self.environment.update(FIXTURE_OS=system, FIXTURE_ARCH=arch)
                result = self.install()
                self.assertEqual(result.returncode, 0, result.stderr)
                installed = subprocess.check_output([str(self.bin_dir / "contextbase")], text=True)
                self.assertEqual(installed.strip(), f"fixture-{platform}")
        self.assertFalse((self.home / ".contextbase").exists())

    def test_hash_failure_preserves_existing_install(self) -> None:
        self.bin_dir.mkdir(parents=True)
        target = self.bin_dir / "contextbase"
        target.write_text("existing CLI")
        self.checksum_file().write_text(f"{'0' * 64}  contextbase\n")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assertEqual(target.read_text(), "existing CLI")
        self.assertEqual(list(self.bin_dir.glob(".contextbase.*")), [])

    def test_invalid_or_duplicate_checksum_cannot_install(self) -> None:
        valid = self.checksum_file().read_text()
        for content in [
            "",
            "not-a-digest  contextbase\n",
            valid + valid,
            valid.replace("contextbase", "../other"),
        ]:
            with self.subTest(content=content):
                self.checksum_file().write_text(content)
                result = self.install()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.bin_dir / "contextbase").exists())

    def test_plain_http_and_embedded_credentials_are_rejected(self) -> None:
        for url in [
            self.base_url.replace("https:", "http:"),
            "https://user:secret@example.invalid",
            self.base_url + "?key=x",
        ]:
            with self.subTest(url=url):
                result = self.install(base_url=url)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.bin_dir.exists())

    def test_unpublished_version_and_unsupported_platform_do_not_install(self) -> None:
        self.assertNotEqual(self.install("--version", "9.9.9").returncode, 0)
        self.environment["FIXTURE_OS"] = "Unsupported"
        self.assertIn("supported CLI platforms", self.install().stderr)
        self.assertFalse(self.bin_dir.exists())

    def test_no_implicit_download_host_or_latest_version(self) -> None:
        for args in [[], ["--base-url", self.base_url]]:
            result = subprocess.run(
                ["bash", str(INSTALLER), *args],
                env=self.environment,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)

    def test_environment_configuration_and_v_prefix(self) -> None:
        self.environment.update(
            CONTEXTBASE_DOWNLOAD_BASE_URL=self.base_url + "/",
            CONTEXTBASE_VERSION="v" + VERSION,
            CONTEXTBASE_BIN_DIR=str(self.bin_dir),
        )
        result = subprocess.run(
            ["bash", str(INSTALLER)],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.bin_dir / "contextbase").is_file())

    @unittest.skipUnless(
        os.environ.get("CONTEXTBASE_TEST_NPM_TARBALL"),
        "provide the built Coding Agents tarball",
    )
    def test_npm_installs_actual_tarball_by_https_url(self) -> None:
        artifact = Path(os.environ["CONTEXTBASE_TEST_NPM_TARBALL"]).resolve()
        destination = self.origin / "downloads" / "coding-agents.tgz"
        shutil.copyfile(artifact, destination)
        prefix = self.home / "npm"
        self.environment.update(
            npm_config_cafile=str(self.cert),
            npm_config_registry="https://registry.invalid",
        )
        result = subprocess.run(
            [
                "npm",
                "install",
                "--global",
                "--prefix",
                str(prefix),
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                self.base_url + "/coding-agents.tgz",
            ],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        # Exercise the installed package exactly as the two OpenCode loaders
        # resolve it: v1 follows main, v2 imports the root index.js directly.
        package_root = prefix / "lib" / "node_modules" / "contextbase-coding-agents"
        probe = subprocess.run(
            [
                "node",
                "--input-type=module",
                "-e",
                """
                import assert from 'node:assert/strict';
                import { readFileSync } from 'node:fs';
                import { pathToFileURL } from 'node:url';
                const root = process.argv[1];
                const pkg = JSON.parse(readFileSync(root + '/package.json', 'utf8'));
                const v1 = await import(pathToFileURL(root + '/' + pkg.main));
                assert.equal(typeof v1.default, 'function');
                const v2 = await import(pathToFileURL(root + '/index.js'));
                assert.equal(v2.default, v2.ContextBaseOpencode2Plugin);
                assert.equal(v2.default.id, 'contextbase-opencode2');
                assert.equal(typeof v2.default.setup, 'function');
                """,
                str(package_root),
            ],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(probe.returncode, 0, probe.stdout + probe.stderr)
        executable = prefix / "bin" / "contextbase-coding-agents"
        register = subprocess.run(
            [
                str(executable),
                "install",
                "codex",
                "--api-url",
                "https://tenant.example.invalid",
            ],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(register.returncode, 0, register.stdout + register.stderr)
        config = self.home / ".codex" / "config.toml"
        self.assertIn("[mcp_servers.contextbase]", config.read_text())
        uninstall = subprocess.run(
            [str(executable), "uninstall", "codex"],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
        self.assertNotIn("[mcp_servers.contextbase]", config.read_text())


if __name__ == "__main__":
    unittest.main()
