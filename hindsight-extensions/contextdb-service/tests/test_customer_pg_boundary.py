"""Community-PG role boundary tests; not API/MCP or cloud-root verification.

All SQL targets a unique disposable pg0 instance. No Repository/model fixture or
environment database URL is used, and representative tables avoid core migrations.
"""

from __future__ import annotations

import secrets
import socket
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
import pytest
import pytest_asyncio
from pg0 import Pg0


@dataclass(frozen=True)
class Boundary:
    provisioner: asyncpg.Connection
    customer: asyncpg.Connection
    owner_name: str
    customer_name: str
    metadata_schema: str
    bank_schema: str
    customer_schema: str
    public_function: str


@pytest.fixture(scope="session")
def pg_boundary_uri(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    name = f"ctxdb-pg-boundary-{secrets.token_hex(8)}"
    data_dir = tmp_path_factory.mktemp(name)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    assert port != 5432
    instance = Pg0(name=name, port=port, data_dir=str(data_dir), database="boundary_test")
    try:
        info = instance.start()
        assert info.uri is not None
        assert info.data_dir is not None and Path(info.data_dir).resolve() == data_dir.resolve()
        assert info.port == port
        yield info.uri
    finally:
        # Unique name and explicitly owned data_dir: never stop/drop any existing
        # developer instance, even if startup, setup, or a permission test fails.
        instance.stop()
        assert not instance.running, "Disposable pg0 failed to stop; do not delete its files"
        instance.drop()
        assert not data_dir.exists(), "Disposable pg0 data directory was not removed"


async def apply_boundary(conn: asyncpg.Connection, owner: str, customer: str, schema: str) -> None:
    await conn.execute("SELECT set_config('contextdb.boundary_owner', $1, false)", owner)
    await conn.execute("SELECT set_config('contextdb.boundary_customer', $1, false)", customer)
    await conn.execute("SELECT set_config('contextdb.boundary_schema', $1, false)", schema)
    script = Path(__file__).parents[1] / "deployment" / "pg-role-boundary.sql"
    await conn.execute(script.read_text())


@pytest_asyncio.fixture
async def boundary(pg_boundary_uri: str) -> AsyncIterator[Boundary]:
    conn = await asyncpg.connect(pg_boundary_uri)
    customer: asyncpg.Connection | None = None
    suffix = secrets.token_hex(6)
    owner = f"service_{suffix}"
    user = f"customer_{suffix}"
    meta = f"meta_{suffix}"
    bank = f"bank_{suffix}"
    own = f"own_{suffix}"
    public_function = f"extension_probe_{suffix}"
    password = secrets.token_hex(16)
    try:
        # Identifiers/password are generated hex-derived values, never user input.
        await conn.execute(f'CREATE ROLE "{owner}" NOLOGIN NOSUPERUSER NOCREATEROLE NOBYPASSRLS')
        await conn.execute(
            f"CREATE ROLE \"{user}\" LOGIN PASSWORD '{password}' "
            "NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS"
        )
        await conn.execute(f'CREATE SCHEMA "{own}" AUTHORIZATION "{user}"')
        # Provisioning creates schemas with elevated credentials, but representative
        # core objects are owner-created; customer never receives the owner role.
        for schema in (meta, bank):
            await conn.execute(f'CREATE SCHEMA "{schema}" AUTHORIZATION "{owner}"')
        await conn.execute(f'SET ROLE "{owner}"')
        await conn.execute(f'CREATE TABLE "{meta}".users (id int PRIMARY KEY, name text)')
        await conn.execute(f"INSERT INTO \"{meta}\".users VALUES (1, 'protected')")
        await conn.execute(f'CREATE TABLE "{bank}".banks (id int PRIMARY KEY, content text)')
        await conn.execute(f"INSERT INTO \"{bank}\".banks VALUES (1, 'memory')")
        await conn.execute(f'CREATE SEQUENCE "{bank}".seq')
        # Deliberately start with permissive grants: deployment SQL must remove them.
        for schema in (meta, bank):
            await conn.execute(f'GRANT ALL ON SCHEMA "{schema}" TO PUBLIC, "{user}"')
            await conn.execute(f'GRANT ALL ON ALL TABLES IN SCHEMA "{schema}" TO PUBLIC, "{user}"')
            await conn.execute(f'GRANT ALL ON ALL SEQUENCES IN SCHEMA "{schema}" TO PUBLIC, "{user}"')
            await conn.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT ALL ON TABLES TO "{user}"')
        await conn.execute("RESET ROLE")
        # Stand-in for a public shared-extension function; no extension downloads.
        await conn.execute(
            f"CREATE FUNCTION public.\"{public_function}\"() RETURNS text LANGUAGE sql AS $$SELECT 'shared'$$"
        )
        for schema in (meta, bank):
            await apply_boundary(conn, owner, user, schema)
        await conn.execute(f'SET ROLE "{owner}"')
        await conn.execute(f'CREATE TABLE "{bank}".future (id int)')
        await conn.execute(f"CREATE TYPE \"{bank}\".future_type AS ENUM ('protected')")
        await conn.execute(
            f"CREATE FUNCTION \"{bank}\".future_fn() RETURNS text LANGUAGE sql AS $$SELECT 'protected'$$"
        )
        await conn.execute("RESET ROLE")
        parts = urlsplit(pg_boundary_uri)
        assert parts.hostname == "127.0.0.1" and parts.port != 5432
        customer_uri = parts._replace(netloc=f"{user}:{password}@{parts.hostname}:{parts.port}").geturl()
        customer = await asyncpg.connect(customer_uri)
        yield Boundary(conn, customer, owner, user, meta, bank, own, public_function)
    finally:
        if customer is not None:
            await customer.close()
        # PG instance teardown owns all remaining schemas/roles, including partially
        # created fixture state; no cleanup touches the machine's other databases.
        await conn.close()


@pytest.mark.parametrize(
    "statement",
    [
        'SELECT * FROM "{metadata_schema}".users',
        "UPDATE \"{metadata_schema}\".users SET name = 'tampered'",
        'SELECT * FROM "{bank_schema}".banks',
        "INSERT INTO \"{bank_schema}\".banks VALUES (2, 'tampered')",
        "UPDATE \"{bank_schema}\".banks SET content = 'tampered'",
        'DELETE FROM "{bank_schema}".banks',
        'TRUNCATE "{bank_schema}".banks',
        'ALTER TABLE "{bank_schema}".banks ADD COLUMN injected text',
        'ALTER TABLE "{bank_schema}".banks OWNER TO "{customer_name}"',
        'DROP TABLE "{bank_schema}".banks',
        'CREATE TABLE "{bank_schema}".injected (id int)',
        'DROP SCHEMA "{bank_schema}" CASCADE',
        'ALTER SCHEMA "{bank_schema}" RENAME TO injected',
        'ALTER SCHEMA "{bank_schema}" OWNER TO "{customer_name}"',
        'SET ROLE "{owner_name}"',
        'GRANT "{owner_name}" TO "{customer_name}"',
        'GRANT USAGE ON SCHEMA "{bank_schema}" TO "{customer_name}"',
        'GRANT SELECT ON "{bank_schema}".banks TO "{customer_name}"',
        "SELECT nextval('\"{bank_schema}\".seq')",
        'SELECT * FROM "{bank_schema}".future',
        'INSERT INTO "{bank_schema}".future VALUES (1)',
        'SELECT "{bank_schema}".future_fn()',
        "SELECT 'protected'::\"{bank_schema}\".future_type",
        'ALTER ROLE "{customer_name}" SUPERUSER',
        'ALTER ROLE "{customer_name}" BYPASSRLS',
        'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner_name}" IN SCHEMA "{bank_schema}" '
        'GRANT SELECT ON TABLES TO "{customer_name}"',
    ],
)
async def test_customer_denied(boundary: Boundary, statement: str) -> None:
    sql = statement.format(
        metadata_schema=boundary.metadata_schema,
        bank_schema=boundary.bank_schema,
        owner_name=boundary.owner_name,
        customer_name=boundary.customer_name,
    )
    async with boundary.customer.transaction():
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
            await boundary.customer.execute(sql)
        assert denied.value.sqlstate == "42501"


async def test_customer_own_schema_and_public_extensions_work(boundary: Boundary) -> None:
    await boundary.customer.execute(f'CREATE TABLE "{boundary.customer_schema}".notes (body text)')
    await boundary.customer.execute(f"INSERT INTO \"{boundary.customer_schema}\".notes VALUES ('mine')")
    assert await boundary.customer.fetchval(f'SELECT body FROM "{boundary.customer_schema}".notes') == "mine"
    assert await boundary.customer.fetchval(f'SELECT public."{boundary.public_function}"()') == "shared"
    # Object-name visibility is not content visibility; schema ACL is not secrecy
    # for PostgreSQL catalogs. Do not promise to hide Bank/schema existence.
    assert (
        await boundary.customer.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname = $1", boundary.bank_schema)
        == 1
    )


async def test_superuser_is_explicit_unprotected_counterexample(boundary: Boundary) -> None:
    assert await boundary.provisioner.fetchval("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    # FORCE RLS with a false policy still cannot contain a true superuser.
    await boundary.provisioner.execute(f'ALTER TABLE "{boundary.metadata_schema}".users ENABLE ROW LEVEL SECURITY')
    await boundary.provisioner.execute(f'ALTER TABLE "{boundary.metadata_schema}".users FORCE ROW LEVEL SECURITY')
    await boundary.provisioner.execute(
        f'CREATE POLICY nobody ON "{boundary.metadata_schema}".users USING (false) WITH CHECK (false)'
    )
    assert await boundary.provisioner.fetchval(f'SELECT name FROM "{boundary.metadata_schema}".users') == "protected"
    await boundary.provisioner.execute(f"UPDATE \"{boundary.bank_schema}\".banks SET content = 'root can change'")
    assert (
        await boundary.provisioner.fetchval(f'SELECT content FROM "{boundary.bank_schema}".banks') == "root can change"
    )


@pytest.mark.parametrize("attribute", ["SUPERUSER", "CREATEROLE", "CREATEDB", "REPLICATION", "BYPASSRLS"])
async def test_deployment_rejects_privileged_customer(boundary: Boundary, attribute: str) -> None:
    async with boundary.provisioner.transaction():
        await boundary.provisioner.execute(f'ALTER ROLE "{boundary.customer_name}" {attribute}')
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
            await apply_boundary(
                boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema
            )
        assert denied.value.sqlstate == "42501"


async def test_deployment_rejects_owner_membership(boundary: Boundary) -> None:
    await boundary.provisioner.execute(f'GRANT "{boundary.owner_name}" TO "{boundary.customer_name}"')
    with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
        await apply_boundary(boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema)
    assert denied.value.sqlstate == "42501"


async def test_deployment_rejects_database_owner(boundary: Boundary) -> None:
    database = await boundary.provisioner.fetchval("SELECT current_database()")
    # Transaction rollback restores the platform database owner even on failure.
    async with boundary.provisioner.transaction():
        await boundary.provisioner.execute(f'ALTER DATABASE "{database}" OWNER TO "{boundary.customer_name}"')
        with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
            await apply_boundary(
                boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema
            )
        assert denied.value.sqlstate == "42501"


@pytest.mark.parametrize("role", ["pg_read_all_data", "pg_write_all_data", "pg_execute_server_program"])
async def test_deployment_rejects_privileged_membership(boundary: Boundary, role: str) -> None:
    await boundary.provisioner.execute(f'GRANT "{role}" TO "{boundary.customer_name}"')
    with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
        await apply_boundary(boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema)
    assert denied.value.sqlstate == "42501"


async def test_deployment_rejects_inherited_schema_access(boundary: Boundary) -> None:
    role = f"inherited_{secrets.token_hex(6)}"
    await boundary.provisioner.execute(f'CREATE ROLE "{role}" NOLOGIN')
    await boundary.provisioner.execute(f'GRANT USAGE ON SCHEMA "{boundary.bank_schema}" TO "{role}"')
    await boundary.provisioner.execute(f'GRANT "{role}" TO "{boundary.customer_name}"')
    with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
        await apply_boundary(boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema)
    assert denied.value.sqlstate == "42501"


async def test_deployment_rejects_public_as_protected_schema(boundary: Boundary) -> None:
    with pytest.raises(asyncpg.InvalidParameterValueError) as denied:
        await apply_boundary(boundary.provisioner, boundary.owner_name, boundary.customer_name, "public")
    assert denied.value.sqlstate == "22023"


async def test_deployment_rejects_untrusted_shared_public_schema(boundary: Boundary) -> None:
    await boundary.provisioner.execute(f'GRANT CREATE ON SCHEMA public TO "{boundary.customer_name}"')
    with pytest.raises(asyncpg.InsufficientPrivilegeError) as denied:
        await apply_boundary(boundary.provisioner, boundary.owner_name, boundary.customer_name, boundary.bank_schema)
    assert denied.value.sqlstate == "42501"
