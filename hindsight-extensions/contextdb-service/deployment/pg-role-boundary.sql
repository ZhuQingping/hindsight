-- EXAMPLE ONLY: never run this against an existing customer database unchecked.
-- Run as the platform provisioning principal in the ContextDB service database.
-- owner/customer roles and the protected schema must already exist. Repeat for
-- ctxdb_meta and each workspace schema, including every newly created workspace.
-- Supply identifiers using session settings (no password is embedded here):
--   SET contextdb.boundary_owner = 'platform_service';
--   SET contextdb.boundary_customer = 'customer_sql';
--   SET contextdb.boundary_schema = 'ctxdb_meta';
--   \i pg-role-boundary.sql
-- The protected database must also be platform-owned; give customers their own
-- schema for SQL work, not ownership of this database or the protected schemas.
-- This example does NOT implement cloud-provider privileged-account restrictions.
-- True PG SUPERUSER, host OS root, and cloud roles able to assume the owner or
-- override ACLs cannot be contained by this SQL. Verify provider semantics first.
-- Merely checking rolsuper=false is insufficient (e.g. Tencent cloud's restricted
-- superuser role has BYPASSRLS and extra object privileges).
-- References: https://www.postgresql.org/docs/18/role-attributes.html
-- https://www.postgresql.org/docs/18/ddl-schemas.html
-- https://www.postgresql.org/docs/18/sql-alterdefaultprivileges.html

DO $boundary$
DECLARE
    owner_name text := current_setting('contextdb.boundary_owner', true);
    customer_name text := current_setting('contextdb.boundary_customer', true);
    schema_name text := current_setting('contextdb.boundary_schema', true);
    owner_id oid;
    customer_id oid;
    schema_id oid;
    dangerous_role text;
BEGIN
    IF COALESCE(owner_name, '') = '' OR COALESCE(customer_name, '') = ''
       OR COALESCE(schema_name, '') = '' OR owner_name = customer_name
       OR schema_name IN ('public', 'information_schema') OR schema_name LIKE 'pg\_%' ESCAPE '\' THEN
        RAISE EXCEPTION 'Supply distinct pre-created owner/customer roles and a protected non-system schema'
            USING ERRCODE = '22023';
    END IF;
    SELECT oid INTO owner_id FROM pg_roles WHERE rolname = owner_name;
    SELECT oid INTO customer_id FROM pg_roles WHERE rolname = customer_name;
    IF owner_id IS NULL OR customer_id IS NULL THEN
        RAISE EXCEPTION 'Both roles must already exist' USING ERRCODE = '22023';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE oid = customer_id
               AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Customer must be NOSUPERUSER NOCREATEROLE NOCREATEDB NOREPLICATION NOBYPASSRLS'
            USING ERRCODE = '42501';
    END IF;
    -- MEMBER catches indirect grants too, even if INHERIT/SET are disabled.
    IF pg_has_role(customer_id, owner_id, 'MEMBER') OR EXISTS
       (SELECT 1 FROM pg_database WHERE datname = current_database() AND datdba = customer_id) THEN
        RAISE EXCEPTION 'Customer cannot own this database or belong to the service owner role'
            USING ERRCODE = '42501';
    END IF;
    -- Hindsight resolves shared extension functions/types in public. Customer
    -- CREATE there would make public an untrusted search_path entry. Provisioning
    -- may separately REVOKE CREATE ON SCHEMA public FROM PUBLIC, customer_sql;
    -- keep its USAGE and extension-function permissions intact.
    IF has_schema_privilege(customer_id, 'public', 'CREATE') THEN
        RAISE EXCEPTION 'Customer must not have CREATE on shared public schema'
            USING ERRCODE = '42501';
    END IF;
    FOREACH dangerous_role IN ARRAY ARRAY[
        'pg_read_all_data', 'pg_write_all_data', 'pg_read_server_files',
        'pg_write_server_files', 'pg_execute_server_program', 'pg_checkpoint',
        'pg_maintain', 'pg_signal_backend'
    ] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = dangerous_role)
           AND pg_has_role(customer_id, dangerous_role, 'MEMBER') THEN
            RAISE EXCEPTION 'Customer belongs to privileged role %', dangerous_role USING ERRCODE = '42501';
        END IF;
    END LOOP;
    SELECT oid INTO schema_id FROM pg_namespace WHERE nspname = schema_name AND nspowner = owner_id;
    IF schema_id IS NULL OR EXISTS
       (SELECT 1 FROM pg_class WHERE relnamespace = schema_id AND relowner <> owner_id)
       OR EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace = schema_id AND proowner <> owner_id)
       OR EXISTS (SELECT 1 FROM pg_type WHERE typnamespace = schema_id AND typowner <> owner_id) THEN
        RAISE EXCEPTION 'Protected schema and existing objects must belong to the platform service owner'
            USING ERRCODE = '42501';
    END IF;
    -- Other inherited roles may carry schema privileges; reject rather than
    -- silently weaken those unrelated roles. Cloud-defined override roles need
    -- an additional provider-specific check outside this community-PG example.
    EXECUTE format('REVOKE ALL ON SCHEMA %I FROM PUBLIC, %I', schema_name, customer_name);
    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM PUBLIC, %I', schema_name, customer_name);
    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC, %I', schema_name, customer_name);
    EXECUTE format('REVOKE ALL ON ALL ROUTINES IN SCHEMA %I FROM PUBLIC, %I', schema_name, customer_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON TABLES FROM PUBLIC, %I',
                   owner_name, schema_name, customer_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM PUBLIC, %I',
                   owner_name, schema_name, customer_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA %I REVOKE ALL ON FUNCTIONS FROM PUBLIC, %I',
                   owner_name, schema_name, customer_name);
    IF has_schema_privilege(customer_id, schema_id, 'USAGE')
       OR has_schema_privilege(customer_id, schema_id, 'CREATE') THEN
        RAISE EXCEPTION 'Customer retains inherited access to protected schema; review role memberships'
            USING ERRCODE = '42501';
    END IF;
END
$boundary$;

-- Schema USAGE denial is the boundary for future functions/types too. Per-schema
-- default REVOKE cannot cancel PostgreSQL's global defaults (PUBLIC EXECUTE on
-- functions, PUBLIC USAGE on types), nor owner-wide explicit default grants.
-- Do not globally revoke PUBLIC access to public: vector/PGroonga objects shared
-- there must remain usable. Run migrations as the owner, and reapply this block
-- if object ownership or the customer's memberships change. Customers must not
-- receive service credentials. Catalogs can still disclose object names; this
-- protects contents and modifications, not the existence of schema/table names.
