\set ON_ERROR_STOP on

DO $roles$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_migrate') THEN
        CREATE ROLE melloa_migrate NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_core') THEN
        CREATE ROLE melloa_core NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_worker') THEN
        CREATE ROLE melloa_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_readonly') THEN
        CREATE ROLE melloa_readonly NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_backup') THEN
        CREATE ROLE melloa_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_change_planner') THEN
        CREATE ROLE melloa_change_planner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'melloa_change_applier') THEN
        CREATE ROLE melloa_change_applier NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$roles$;

ALTER ROLE melloa_core SET search_path = melloa, public;
ALTER ROLE melloa_worker SET search_path = melloa, public;
ALTER ROLE melloa_readonly SET search_path = melloa, public;
ALTER ROLE melloa_change_planner SET search_path = melloa, public;
ALTER ROLE melloa_change_applier SET search_path = melloa, public;
