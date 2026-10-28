"""Offline deployment must provision shared routines without public business tables."""

from pathlib import Path

import pytest

from hindsight_ext_contextdb.migrations import migrate_connection
from hindsight_ext_contextdb.repository import Repository

from .support.identities import ADMIN_SECRET


async def initialize(repository: Repository) -> None:
    async with repository.pool.acquire() as conn:
        await migrate_connection(
            conn,
            repository.instance_id,
            repository.cloud_tenant_id,
            pepper=repository.pepper,
            admin_secret=ADMIN_SECRET,
        )


ROUTINES = (
    "public.banks_needing_consolidation()",
    "public.mental_models_with_cron()",
    "public.schemas_with_expired_rows(text,text,integer)",
    "public.schemas_with_expired_operations(integer)",
)


async def test_offline_init_installs_four_native_routines_without_public_tables(repository: Repository) -> None:
    await initialize(repository)
    for signature in ROUTINES:
        assert await repository.pool.fetchval("SELECT to_regprocedure($1)::text", signature), signature
    assert await repository.pool.fetchval("SELECT count(*) FROM pg_tables WHERE schemaname='public'") == 0
    definitions = [
        await repository.pool.fetchval("SELECT pg_get_functiondef(to_regprocedure($1))", signature)
        for signature in ROUTINES
    ]
    # Keep the latest native migration's DDL-race protection, not the older
    # pre-lock-timeout versions that happen to have the same names/signatures.
    assert all("250ms" in definition and "prev_lock_timeout" in definition for definition in definitions)
    await initialize(repository)
    assert [
        await repository.pool.fetchval("SELECT pg_get_functiondef(to_regprocedure($1))", signature)
        for signature in ROUTINES
    ] == definitions


async def test_offline_init_fails_if_an_externally_owned_routine_is_missing(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    await repository.pool.execute("DROP FUNCTION IF EXISTS public.banks_needing_consolidation()")
    monkeypatch.setenv("HINDSIGHT_API_EXTERNALLY_OWNED_ROUTINES", "banks_needing_consolidation")
    with pytest.raises(RuntimeError, match="maintenance"):
        await initialize(repository)


async def test_routines_discover_real_candidates_and_preserve_timeout(repository: Repository) -> None:
    """Mechanism fixture: SQL controls timestamps/statuses unavailable via public API.

    These minimal tenant tables exercise native PL/pgSQL format() with nonempty
    candidates. Full schemas/SDK/Worker execution are covered by system stories.
    """
    await initialize(repository)
    async with repository.pool.acquire() as conn:
        await conn.execute("""CREATE SCHEMA "ctxdb_ws_probe%quoted";
            CREATE TABLE "ctxdb_ws_probe%quoted".banks(bank_id text, config jsonb);
            CREATE TABLE "ctxdb_ws_probe%quoted".memory_units(
                bank_id text, consolidated_at timestamptz, consolidation_failed_at timestamptz, fact_type text);
            CREATE TABLE "ctxdb_ws_probe%quoted".async_operations(
                bank_id text, operation_type text, status text, task_payload jsonb, updated_at timestamptz);
            CREATE TABLE "ctxdb_ws_probe%quoted".mental_models(
                bank_id text, id text, trigger jsonb, last_refreshed_at timestamptz);
            CREATE TABLE "ctxdb_ws_probe%quoted".audit_log(started_at timestamptz);
            INSERT INTO "ctxdb_ws_probe%quoted".banks VALUES ('candidate','{}');
            INSERT INTO "ctxdb_ws_probe%quoted".memory_units VALUES ('candidate',NULL,NULL,'world');
            INSERT INTO "ctxdb_ws_probe%quoted".mental_models VALUES
                ('candidate','model','{"refresh_cron":"* * * * *"}',NULL);
            INSERT INTO "ctxdb_ws_probe%quoted".audit_log VALUES (now()-interval '10 days');
            INSERT INTO "ctxdb_ws_probe%quoted".async_operations VALUES
                ('active','retain','processing','{}',now()-interval '10 days');""")
        await conn.execute("SET lock_timeout='3s'")
        banks = await conn.fetch("SELECT * FROM public.banks_needing_consolidation()")
        assert any(dict(row) == {"schema_name": "ctxdb_ws_probe%quoted", "bank_id": "candidate"} for row in banks)
        models = await conn.fetch("SELECT * FROM public.mental_models_with_cron()")
        assert any(
            row["schema_name"] == "ctxdb_ws_probe%quoted" and row["mental_model_id"] == "model" for row in models
        )
        assert "ctxdb_ws_probe%quoted" in await conn.fetchval(
            "SELECT array_agg(s) FROM public.schemas_with_expired_rows('audit_log','started_at',7) AS s"
        )
        assert not await conn.fetchval("SELECT EXISTS(SELECT FROM public.schemas_with_expired_operations(7))")
        await conn.execute("""INSERT INTO "ctxdb_ws_probe%quoted".async_operations VALUES
            ('done','retain','completed','{}',now()-interval '10 days')""")
        assert "ctxdb_ws_probe%quoted" in await conn.fetchval(
            "SELECT array_agg(s) FROM public.schemas_with_expired_operations(7) AS s"
        )
        assert not await conn.fetchval("SELECT EXISTS(SELECT FROM public.schemas_with_expired_operations(0))")
        assert await conn.fetchval("SHOW lock_timeout") == "3s"
        await conn.execute("RESET lock_timeout")


@pytest.mark.parametrize("compatible", [True, False])
async def test_external_ownership_preserves_definition_and_validates_contract(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, compatible: bool
) -> None:
    await repository.pool.execute("DROP FUNCTION IF EXISTS public.banks_needing_consolidation()")
    result = "TABLE(schema_name text, bank_id text)" if compatible else "SETOF integer"
    body = "SELECT 'external'::text, 'sentinel'::text" if compatible else "SELECT 42"
    await repository.pool.execute(
        f"CREATE FUNCTION public.banks_needing_consolidation() RETURNS {result} LANGUAGE sql AS $$ {body} $$"
    )
    before = await repository.pool.fetchval(
        "SELECT pg_get_functiondef('public.banks_needing_consolidation()'::regprocedure)"
    )
    monkeypatch.setenv("HINDSIGHT_API_EXTERNALLY_OWNED_ROUTINES", "banks_needing_consolidation")
    try:
        if compatible:
            await initialize(repository)
        else:
            with pytest.raises(RuntimeError, match="maintenance"):
                await initialize(repository)
        assert before == await repository.pool.fetchval(
            "SELECT pg_get_functiondef('public.banks_needing_consolidation()'::regprocedure)"
        )
    finally:
        await repository.pool.execute("DROP FUNCTION public.banks_needing_consolidation()")


async def test_configured_maintenance_schema_and_search_path(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    import hindsight_api.config as config

    monkeypatch.setattr(
        config, "_config_cache", replace(config._get_raw_config(), database_schema="maintenance%custom")
    )
    await repository.pool.execute('CREATE SCHEMA "maintenance%custom"')
    try:
        async with repository.pool.acquire() as conn:
            await conn.execute("SET search_path=ctxdb_meta")
            try:
                await migrate_connection(
                    conn,
                    repository.instance_id,
                    repository.cloud_tenant_id,
                    pepper=repository.pepper,
                    admin_secret=ADMIN_SECRET,
                )
            finally:
                await conn.execute("RESET search_path")
        for signature in ROUTINES:
            assert await repository.pool.fetchval(
                "SELECT to_regprocedure($1) IS NOT NULL", '"maintenance%custom".' + signature.removeprefix("public.")
            )
        assert not await repository.pool.fetchval("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public')")
    finally:
        await repository.pool.execute('DROP SCHEMA "maintenance%custom" CASCADE')


@pytest.mark.parametrize(
    "schema_env,owned_env,target,preserved",
    [
        ({"HINDSIGHT_API_DATABASE_SCHEMA": "maintenance_cli"}, {}, "maintenance_cli", False),
        ({"CONTEXTBASE_API_DATABASE_SCHEMA": "maintenance_cli"}, {}, "maintenance_cli", False),
        (
            {"CONTEXTBASE_API_DATABASE_SCHEMA": "maintenance_cli", "HINDSIGHT_API_DATABASE_SCHEMA": "public"},
            {
                "CONTEXTBASE_API_EXTERNALLY_OWNED_ROUTINES": "banks_needing_consolidation",
                "HINDSIGHT_API_EXTERNALLY_OWNED_ROUTINES": "",
            },
            "maintenance_cli",
            True,
        ),
        (
            {"CONTEXTBASE_API_DATABASE_SCHEMA": "", "HINDSIGHT_API_DATABASE_SCHEMA": "maintenance_cli"},
            {
                "CONTEXTBASE_API_EXTERNALLY_OWNED_ROUTINES": "",
                "HINDSIGHT_API_EXTERNALLY_OWNED_ROUTINES": "banks_needing_consolidation",
            },
            "public",
            False,
        ),
    ],
)
async def test_real_cli_honors_alias_precedence_and_ignores_parent_dotenv(
    repository: Repository,
    database_url: str,
    tmp_path: Path,
    schema_env: dict[str, str],
    owned_env: dict[str, str],
    target: str,
    preserved: bool,
) -> None:
    import hashlib
    import os
    import subprocess
    import sys

    from hindsight_ext_contextdb.bootstrap import AdministratorCredential, save_credential

    from ..paths import EXTENSION

    await repository.pool.execute("CREATE SCHEMA maintenance_cli")
    try:
        # This external implementation has the native result contract, but an
        # observable body. Only the selected ownership policy may preserve it.
        await repository.pool.execute(f'DROP FUNCTION IF EXISTS "{target}".banks_needing_consolidation()')
        await repository.pool.execute(f'''CREATE FUNCTION "{target}".banks_needing_consolidation()
            RETURNS TABLE(schema_name text, bank_id text) LANGUAGE sql AS $$ SELECT 'owned'::text, 'sentinel'::text $$''')
        before = await repository.pool.fetchval(
            "SELECT pg_get_functiondef(to_regprocedure($1))", target + ".banks_needing_consolidation()"
        )
        credential = tmp_path / "admin.json"
        save_credential(
            credential,
            AdministratorCredential(
                key_id="a" * 32, secret=ADMIN_SECRET, sha256=hashlib.sha256(ADMIN_SECRET.encode()).hexdigest()
            ),
        )
        (tmp_path / ".env").write_text("CONTEXTBASE_API_DATABASE_URL=postgresql://invalid.invalid/never_connect\n")
        environment = {
            k: v for k, v in os.environ.items() if not k.startswith(("HINDSIGHT_", "CONTEXTBASE_", "CONTEXTDB_"))
        }
        environment.update(
            {
                "PYTHONPATH": str(EXTENSION),
                "PYTHON_DOTENV_DISABLED": "0",
                "CONTEXTBASE_API_DATABASE_URL": database_url,
                "CONTEXTBASE_API_LLM_TRACE_ENABLED": "false",
                "CONTEXTBASE_API_AUDIT_LOG_ENABLED": "false",
                "CONTEXTDB_INSTANCE_ID": repository.instance_id,
                "CONTEXTDB_CLOUD_TENANT_ID": repository.cloud_tenant_id,
                "CONTEXTDB_KEY_PEPPER": repository.pepper,
                **schema_env,
                **owned_env,
            }
        )
        result = subprocess.run(
            [sys.executable, "-m", "hindsight_ext_contextdb", "migrate", "--admin-key-file", str(credential)],
            env=environment,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert ADMIN_SECRET not in result.stdout + result.stderr
        for signature in ROUTINES:
            assert await repository.pool.fetchval(
                "SELECT to_regprocedure($1) IS NOT NULL", target + "." + signature.removeprefix("public.")
            )
        after = await repository.pool.fetchval(
            "SELECT pg_get_functiondef(to_regprocedure($1))", target + ".banks_needing_consolidation()"
        )
        assert (before == after) is preserved
        assert not await repository.pool.fetchval("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public')")
    finally:
        await repository.pool.execute("DROP SCHEMA maintenance_cli CASCADE")


async def test_concurrent_repeat_init_preserves_existing_function_definitions(repository: Repository) -> None:
    import asyncio

    await initialize(repository)
    before = [
        await repository.pool.fetchval("SELECT pg_get_functiondef(to_regprocedure($1))", name) for name in ROUTINES
    ]
    await asyncio.gather(*(initialize(repository) for _ in range(3)))
    assert before == [
        await repository.pool.fetchval("SELECT pg_get_functiondef(to_regprocedure($1))", name) for name in ROUTINES
    ]
    assert not await repository.pool.fetchval("SELECT EXISTS(SELECT FROM pg_tables WHERE schemaname='public')")


@pytest.mark.parametrize("can_execute", [False, True])
async def test_external_functions_require_execute_permission(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, can_execute: bool
) -> None:
    import secrets

    from hindsight_ext_contextdb.maintenance import initialize_maintenance

    await initialize(repository)
    monkeypatch.setenv(
        "HINDSIGHT_API_EXTERNALLY_OWNED_ROUTINES", ",".join(name.split(".")[1].split("(")[0] for name in ROUTINES)
    )
    role = "ctxdb_execute_probe_" + secrets.token_hex(6)
    async with repository.pool.acquire() as conn:
        await conn.execute(f'CREATE ROLE "{role}" NOSUPERUSER NOCREATEDB NOCREATEROLE')
        try:
            if not can_execute:
                await conn.execute("REVOKE EXECUTE ON FUNCTION public.banks_needing_consolidation() FROM PUBLIC")
            await conn.execute(f'SET ROLE "{role}"')
            try:
                if can_execute:
                    await initialize_maintenance(conn)
                else:
                    with pytest.raises(RuntimeError, match="maintenance"):
                        await initialize_maintenance(conn)
            finally:
                await conn.execute("RESET ROLE")
        finally:
            await conn.execute("GRANT EXECUTE ON FUNCTION public.banks_needing_consolidation() TO PUBLIC")
            await conn.execute(f'DROP ROLE "{role}"')
