BEGIN;
ALTER TABLE lavlah.https_observations ADD COLUMN scheduler_run_id uuid UNIQUE REFERENCES lavlah.https_scheduler_runs(id);
-- Deliberately conservative shared bucket: all subdomains under an approved
-- administrative suffix can be grouped. Unmapped hosts use the global bucket.
CREATE TABLE lavlah.https_domain_groups (
 host text PRIMARY KEY CHECK(host=lower(host) AND host ~ '^[a-z0-9.-]+$'),
 group_key text NOT NULL CHECK(group_key ~ '^[a-z0-9.-]+$')
);
REVOKE ALL ON lavlah.https_domain_groups FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT ON lavlah.https_domain_groups TO lavlah_ingestion;
CREATE VIEW lavlah.scheduler_alerts WITH (security_barrier=true) AS
SELECT 'expired_lease'::text AS code,count(*) AS affected FROM lavlah.https_scheduler_runs
WHERE outcome='running' AND lease_until<=clock_timestamp() HAVING count(*)>0
UNION ALL SELECT 'repeated_failure',count(*) FROM lavlah.collection_jobs
WHERE enabled AND failures>=3 HAVING count(*)>0
UNION ALL SELECT 'interrupted_recently',count(*) FROM lavlah.https_scheduler_runs
WHERE outcome='interrupted' AND finished_at>clock_timestamp()-interval '1 day' HAVING count(*)>0;
REVOKE ALL ON lavlah.scheduler_alerts FROM PUBLIC;
GRANT SELECT ON lavlah.scheduler_alerts TO lavlah_ingestion,lavlah_ingestion_reviewer;
COMMIT;
