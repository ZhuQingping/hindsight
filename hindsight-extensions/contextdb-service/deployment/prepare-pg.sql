-- Run as the PG provisioning administrator against the maintenance database.
-- This creates NEW objects and deliberately fails rather than adopting an old DB.
-- Input: psql -v service_role=contextdb_service -v service_db=contextdb -f prepare-pg.sql
-- Secret: exported CONTEXTDB_NEW_DB_PASSWORD; never put the password in -v arguments.
\set ON_ERROR_STOP on
\getenv service_password CONTEXTDB_NEW_DB_PASSWORD
CREATE ROLE :"service_role" LOGIN PASSWORD :'service_password'
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE DATABASE :"service_db" OWNER :"service_role" TEMPLATE template0 ENCODING 'UTF8';
REVOKE ALL ON DATABASE :"service_db" FROM PUBLIC;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE :"service_db" TO :"service_role";
\connect :service_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"service_role";
CREATE EXTENSION vector WITH SCHEMA public;
CREATE EXTENSION pg_trgm WITH SCHEMA public;
CREATE EXTENSION btree_gin WITH SCHEMA public;
-- Install the selected full-text extension separately after confirming provider
-- support and licensing; this script never silently chooses a fallback backend.
SELECT extname, extversion FROM pg_extension ORDER BY extname;
