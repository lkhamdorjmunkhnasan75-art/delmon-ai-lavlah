-- Delmon Lavlah Staging only: disabled reviewer identity placeholder.
-- No password, LOGIN, role grants or identity binding until an approved
-- isolated worker host and its credential storage/network boundary exist.
DO $$ BEGIN
 IF current_database() <> 'postgres' OR current_user <> 'postgres'
 OR to_regclass('lavlah.reviewer_login_bindings') IS NULL
 OR current_setting('server_version_num')::int NOT BETWEEN 170000 AND 179999
 OR current_setting('max_prepared_transactions')::int <> 0
 THEN RAISE EXCEPTION 'unexpected staging database'; END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='lavlah_staging_reviewer_worker')
 THEN RAISE EXCEPTION 'worker role already exists'; END IF;
END $$;
CREATE ROLE lavlah_staging_reviewer_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 1;
ALTER ROLE lavlah_staging_reviewer_worker IN DATABASE postgres SET statement_timeout='5s';
ALTER ROLE lavlah_staging_reviewer_worker IN DATABASE postgres SET lock_timeout='2s';
ALTER ROLE lavlah_staging_reviewer_worker IN DATABASE postgres SET idle_in_transaction_session_timeout='5s';
ALTER ROLE lavlah_staging_reviewer_worker IN DATABASE postgres SET transaction_timeout='15s';
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='lavlah_staging_reviewer_worker' AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreaterole AND NOT rolcreatedb AND NOT rolreplication AND NOT rolinherit AND rolconnlimit=1)
 OR pg_has_role('lavlah_staging_reviewer_worker','lavlah_ingestion_reviewer','MEMBER')
 OR pg_has_role('lavlah_staging_reviewer_worker','lavlah_publication_owner','MEMBER')
 OR has_schema_privilege('lavlah_staging_reviewer_worker','lavlah','USAGE')
 OR has_function_privilege('lavlah_staging_reviewer_worker','lavlah.atomic_review(uuid,uuid,boolean,text)','EXECUTE')
 OR EXISTS (SELECT FROM lavlah.reviewer_login_bindings WHERE login_name='lavlah_staging_reviewer_worker')
 THEN RAISE EXCEPTION 'unsafe worker placeholder'; END IF;
END $$;
