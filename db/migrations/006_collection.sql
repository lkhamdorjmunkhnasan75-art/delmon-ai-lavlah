BEGIN;
ALTER TABLE lavlah.ingestion_candidates ADD COLUMN observation_day date NOT NULL DEFAULT (timezone('UTC',now())::date);
ALTER TABLE lavlah.ingestion_candidates DROP CONSTRAINT ingestion_candidates_permission_id_digest_key;
ALTER TABLE lavlah.ingestion_candidates ADD UNIQUE(permission_id,digest,observation_day);
CREATE TABLE lavlah.collection_jobs (
 permission_id uuid PRIMARY KEY REFERENCES lavlah.ingestion_permissions(id),
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 interval_minutes integer NOT NULL CHECK(interval_minutes BETWEEN 1440 AND 10080),
 next_run timestamptz NOT NULL DEFAULT now(),
 enabled boolean NOT NULL DEFAULT false,
 failures integer NOT NULL DEFAULT 0 CHECK(failures>=0)
);
CREATE TABLE lavlah.collection_runs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 permission_id uuid NOT NULL REFERENCES lavlah.collection_jobs(permission_id),
 started_at timestamptz NOT NULL DEFAULT now(),
 outcome text NOT NULL CHECK(outcome IN ('success','failed','blocked')),
 record_count integer NOT NULL CHECK(record_count BETWEEN 0 AND 100),
 error_code text CHECK(error_code IN ('adapter_error','permission_invalid','record_invalid','database_error'))
);
REVOKE ALL ON lavlah.collection_jobs,lavlah.collection_runs FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,UPDATE(next_run,failures) ON lavlah.collection_jobs TO lavlah_ingestion;
GRANT SELECT,INSERT ON lavlah.collection_runs TO lavlah_ingestion;
GRANT USAGE ON SEQUENCE lavlah.collection_runs_id_seq TO lavlah_ingestion;
COMMIT;
