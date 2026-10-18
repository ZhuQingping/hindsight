"""Read-only deployment checks; never initialize data or print secret settings."""

from __future__ import annotations

import asyncio
import importlib
import os
import platform
import re
import sys
from pathlib import Path
from typing import Literal

import asyncpg
from pydantic import BaseModel


class Check(BaseModel):
    name: str
    status: Literal["pass", "fail", "warning"]
    detail: str


class PreflightReport(BaseModel):
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(item.status != "fail" for item in self.checks)


async def preflight(
    *,
    source_root: Path | None = None,
    ui_build: bool = False,
    embedded: bool = False,
    language: Literal["english", "chinese", "multilingual"] = "english",
) -> PreflightReport:
    checks = [
        Check(
            name="platform",
            status="pass",
            detail=f"{platform.system()} {platform.machine()} Python {platform.python_version()}",
        )
    ]
    if os.environ.get("HINDSIGHT_API_WEBHOOK_URL"):
        checks.append(
            Check(
                name="webhooks",
                status="fail",
                detail="ContextDB first release does not support global webhooks; remove HINDSIGHT_API_WEBHOOK_URL",
            )
        )
    for flag, default in [("HINDSIGHT_API_LLM_TRACE_ENABLED", "true"), ("HINDSIGHT_API_AUDIT_LOG_ENABLED", "false")]:
        if os.environ.get(flag, default).lower() != "false":
            checks.append(
                Check(
                    name=flag,
                    status="fail",
                    detail="Set false: native detached diagnostic writes are not generation-fenced",
                )
            )
    if not (3, 11) <= sys.version_info[:2] <= (3, 14):
        checks.append(Check(name="python", status="fail", detail="Supported Python versions are3.11 through3.14"))
    for name in ["hindsight_api", "hindsight_ext_contextdb"]:
        try:
            module = importlib.import_module(name)
        except ImportError:
            checks.append(Check(name=name, status="fail", detail="Required matching package is not installed"))
            continue
        location = Path(module.__file__ or "").resolve()
        matches = source_root is None or location.is_relative_to(source_root.resolve())
        checks.append(Check(name=name, status="pass" if matches else "fail", detail=str(location)))
    try:
        from hindsight_api.extensions.operation_validator import BankListScope

        assert BankListScope is not None
        checks.append(
            Check(name="extension_contract", status="pass", detail="Required BankListScope contract is available")
        )
    except ImportError:
        checks.append(
            Check(name="extension_contract", status="fail", detail="API and extension artifacts do not match")
        )
    if embedded:
        try:
            importlib.import_module("pg0")
            checks.append(Check(name="embedded_pg", status="pass", detail="pg0-embedded import available"))
        except ImportError:
            checks.append(
                Check(
                    name="embedded_pg",
                    status="fail",
                    detail="Install the API embedded-db extra (distribution: pg0-embedded)",
                )
            )
    if ui_build:
        for program, args in [("node", ["--version"]), ("npm", ["--version"])]:
            try:
                process = await asyncio.create_subprocess_exec(
                    program, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
                )
                output, _ = await process.communicate()
                version = output.decode().strip()
                supported = process.returncode == 0
                if program == "node":
                    match = re.fullmatch(r"v(\d+)\.(\d+)\.\d+", version)
                    supported = bool(match and (int(match[1]) == 24 or (int(match[1]) == 22 and int(match[2]) >= 12)))
                checks.append(
                    Check(
                        name=program,
                        status="pass" if supported else "fail",
                        detail=version if supported else "Use Node22.12+ or24 and its matching npm",
                    )
                )
            except OSError:
                checks.append(Check(name=program, status="fail", detail="Required UI build tool is missing"))
        if source_root:
            try:
                command = "const {createRequire}=require('node:module');const r=createRequire(process.cwd()+'/hindsight-clients/typescript/package.json');r('esbuild').transformSync('const x=1');console.log('esbuild ready')"
                process = await asyncio.create_subprocess_exec(
                    "node",
                    "-e",
                    command,
                    cwd=source_root,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.communicate()
                checks.append(
                    Check(
                        name="ui_native_dependencies",
                        status="pass" if process.returncode == 0 else "fail",
                        detail="esbuild platform executable check; install optional dependencies for this OS/architecture",
                    )
                )
            except OSError:
                checks.append(
                    Check(
                        name="ui_native_dependencies", status="fail", detail="Unable to check UI platform dependencies"
                    )
                )
    url = os.environ.get("HINDSIGHT_API_DATABASE_URL")
    if not url:
        checks.append(
            Check(
                name="database",
                status="fail",
                detail="HINDSIGHT_API_DATABASE_URL is required; no implicit embedded fallback",
            )
        )
        return PreflightReport(checks=checks)
    connection: asyncpg.Connection | None = None
    try:
        connection = await asyncpg.connect(url, timeout=10)
        async with connection.transaction(readonly=True):
            version = await connection.fetchval("SHOW server_version")
            encoding = await connection.fetchval("SHOW server_encoding")
            checks.append(
                Check(
                    name="postgresql",
                    status="pass" if encoding == "UTF8" else "fail",
                    detail=f"PostgreSQL {version}; encoding={encoding}",
                )
            )
            installed = {row["extname"] for row in await connection.fetch("SELECT extname FROM pg_extension")}
            backend = os.environ.get("HINDSIGHT_API_TEXT_SEARCH_EXTENSION", "native").lower()
            required = {"vector", "pg_trgm", "btree_gin"}
            if backend == "vchord":
                required.update({"vchord_bm25", "pg_tokenizer"})
            elif backend != "native":
                required.add(backend)
            vector_backend = os.environ.get("HINDSIGHT_API_VECTOR_EXTENSION", "pgvector").lower()
            if vector_backend == "vchord":
                required.add("vchord")
            elif vector_backend not in {"pgvector", "vector"}:
                checks.append(
                    Check(
                        name="vector_backend",
                        status="fail",
                        detail="Deployment profile supports pgvector or vchord; review other vector backends explicitly",
                    )
                )
            for extension in sorted(required):
                checks.append(
                    Check(
                        name=extension,
                        status="pass" if extension in installed else "fail",
                        detail="Enabled in target database"
                        if extension in installed
                        else "Enable the extension in this database before initialization",
                    )
                )
            if backend not in {"native", "pgroonga", "pg_search", "pg_textsearch", "vchord"}:
                checks.append(
                    Check(name="text_search", status="fail", detail="Unsupported Hindsight full-text backend")
                )
            elif language != "english" and backend not in {"pgroonga", "pg_search"}:
                checks.append(
                    Check(
                        name="chinese_fulltext",
                        status="fail",
                        detail="Chinese acceptance requires an explicitly configured PGroonga or pg_search tokenizer",
                    )
                )
            elif language != "english" and backend == "pg_search" and "pg_search" in installed:
                from hindsight_api._pg_search import normalize_pg_search_tokenizer

                tokenizer = normalize_pg_search_tokenizer(
                    os.environ.get("HINDSIGHT_API_TEXT_SEARCH_EXTENSION_PG_SEARCH_TOKENIZER")
                )
                supported = tokenizer in {"jieba", "chinese_compatible", "lindera(chinese)"}
                available = (
                    bool(
                        await connection.fetchval("SELECT to_regtype($1) IS NOT NULL", "pdb." + tokenizer.split("(")[0])
                    )
                    if supported
                    else False
                )
                checks.append(
                    Check(
                        name="chinese_tokenizer",
                        status="pass" if available else "fail",
                        detail="Configured Chinese tokenizer type is available"
                        if available
                        else "Select and install a supported Chinese tokenizer, for example jieba",
                    )
                )
            elif backend == "pgroonga" and "pgroonga" in installed:
                # PGroonga's variadic options require an explicit argument. Exercise
                # the Chinese tokenizer rather than tokenizing with no options.
                await connection.fetch(
                    "SELECT * FROM pgroonga_tokenize($1, 'tokenizer', 'TokenBigram')", "中文检索验证 English"
                )
                checks.append(
                    Check(
                        name="pgroonga_tokenizer",
                        status="pass",
                        detail="Chinese/English tokenization smoke query succeeded",
                    )
                )
            if language == "english" and backend == "native":
                checks.append(
                    Check(
                        name="chinese_fulltext",
                        status="warning",
                        detail="Native English validation does not establish Chinese full-text capability",
                    )
                )
            # Optional observability must not require pg_read_all_settings.
            # pg_settings returns NULL for restricted settings without aborting
            # the read-only probe transaction like SHOW would.
            preload = (
                await connection.fetchval("SELECT setting FROM pg_settings WHERE name='shared_preload_libraries'") or ""
            )
            observed = "pg_stat_statements" in installed and "pg_stat_statements" in {
                value.strip() for value in preload.split(",")
            }
            checks.append(
                Check(
                    name="pg_stat_statements",
                    status="pass" if observed else "warning",
                    detail="SQL observation is configured"
                    if observed
                    else "Optional SQL observation is not fully configured",
                )
            )
    except (asyncpg.PostgresError, OSError, ValueError, TimeoutError):
        checks.append(
            Check(
                name="database_probe",
                status="fail",
                detail="Database or selected plugin probe failed; inspect private deployment logs and configuration",
            )
        )
    finally:
        if connection is not None:
            await connection.close()
    return PreflightReport(checks=checks)
