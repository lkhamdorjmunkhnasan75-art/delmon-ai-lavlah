BEGIN;
DROP VIEW lavlah.collection_duplicate_groups;
DROP TABLE lavlah.collection_runs,lavlah.collection_jobs;
-- Refuse rollback if repeated observations exist; preserve review history.
ALTER TABLE lavlah.ingestion_candidates ADD UNIQUE(permission_id,digest);
ALTER TABLE lavlah.ingestion_candidates DROP CONSTRAINT ingestion_candidates_permission_id_digest_observation_day_key;
ALTER TABLE lavlah.ingestion_candidates DROP COLUMN observation_day;
COMMIT;
