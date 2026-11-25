BEGIN;
CREATE TABLE lavlah.https_domain_slots (
 host text PRIMARY KEY,
 next_at timestamptz NOT NULL
);
CREATE TABLE lavlah.https_scheduler_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 permission_id uuid NOT NULL REFERENCES lavlah.collection_jobs(permission_id),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_until timestamptz NOT NULL,
 finished_at timestamptz,
 outcome text NOT NULL DEFAULT 'running' CHECK(outcome IN ('running','success','failed','blocked','deferred','interrupted')),
 record_count integer NOT NULL DEFAULT 0 CHECK(record_count BETWEEN 0 AND 100),
 error_code text CHECK(error_code IN ('collection_failed','permission_invalid','rate_limited','timeout','lease_expired','database_error','endpoint_not_authorized')),
 CHECK((outcome='running')=(finished_at IS NULL))
);
CREATE UNIQUE INDEX https_scheduler_active ON lavlah.https_scheduler_runs(permission_id) WHERE outcome='running';
REVOKE ALL ON lavlah.https_domain_slots,lavlah.https_scheduler_runs FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,INSERT,UPDATE ON lavlah.https_domain_slots,lavlah.https_scheduler_runs TO lavlah_ingestion;
CREATE VIEW lavlah.https_scheduler_stats WITH (security_barrier=true) AS
SELECT outcome,count(*) AS run_count,sum(record_count) AS record_count
FROM lavlah.https_scheduler_runs GROUP BY outcome;
REVOKE ALL ON lavlah.https_scheduler_stats FROM PUBLIC;
GRANT SELECT ON lavlah.https_scheduler_stats TO lavlah_ingestion,lavlah_ingestion_reviewer;
COMMIT;
