"""Provision native shared discovery functions during offline initialization only."""

from io import StringIO
from pathlib import Path

import asyncpg
import hindsight_api
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from hindsight_api.config import get_config

# This revision contains all four current definitions, including the native
# bounded DDL-lock wait. Do not copy its SQL or replay the public table migrations.
_ROUTINE_REVISION = "c8b4e2a71f95"
_RESULTS = {
    "banks_needing_consolidation()": "TABLE(schema_name text, bank_id text)",
    "mental_models_with_cron()": (
        "TABLE(schema_name text, bank_id text, mental_model_id text, refresh_cron text, "
        "last_refreshed_at timestamp with time zone)"
    ),
    "schemas_with_expired_rows(text,text,integer)": "SETOF text",
    "schemas_with_expired_operations(integer)": "SETOF text",
}


async def initialize_maintenance(conn: asyncpg.Connection) -> None:
    """Reuse native definitions in the metadata transaction after CLI config normalization."""
    schema = get_config().database_schema or "public"
    # The native migration quotes identifiers, but does not escape embedded quotes.
    # Reject those explicitly instead of rendering malformed/injected offline SQL.
    if '"' in schema or "\x00" in schema:
        raise ValueError("Invalid ContextDB maintenance schema")
    config = Config()
    config.set_main_option("target_schema", schema.replace("%", "%%"))
    script = ScriptDirectory(str(Path(hindsight_api.__file__).parent / "alembic"))
    revision = script.get_revision(_ROUTINE_REVISION)
    if revision is None:
        raise RuntimeError("Native maintenance migration is unavailable")
    output = StringIO()
    # No env.py, version-table stamping, new connection, or full schema migration.
    # Generation contains no await: Alembic's module-local contexts are released
    # before another coroutine runs. This entrypoint is offline, not API startup.
    with EnvironmentContext(config, script) as environment:
        environment.configure(
            dialect_name="postgresql",
            dialect_opts={"paramstyle": "named"},
            as_sql=True,
            literal_binds=True,
            output_buffer=output,
        )
        with Operations.context(environment.get_context()):
            revision.module.upgrade()
    # An existing deployment's row lock also serializes repair/repeated init.
    # Fresh-instance metadata creation retains its existing offline-only contract.
    sql = output.getvalue()
    if sql.strip():  # All four functions may be externally owned: no DDL to run.
        await conn.execute(sql)
    for signature, result in _RESULTS.items():
        qualified = f'"{schema}".{signature}'
        if not await conn.fetchval(
            "SELECT prokind='f' AND proretset AND pg_get_function_result(oid)=$2 "
            "AND has_function_privilege(oid, 'EXECUTE') FROM pg_proc WHERE oid=to_regprocedure($1)",
            qualified,
            result,
        ):
            # Externally owned definitions are never replaced by the native
            # migration; the operator must provide the required callable signature.
            raise RuntimeError(f"Required maintenance function is unavailable: {qualified}")
