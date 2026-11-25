BEGIN;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM lavlah.https_observations WHERE scheduler_run_id IS NOT NULL) THEN
 RAISE EXCEPTION 'Run-linked provenance exists; archive before rollback';
END IF; END $$;
DROP VIEW lavlah.scheduler_alerts;
DROP TABLE lavlah.https_domain_groups;
ALTER TABLE lavlah.https_observations DROP COLUMN scheduler_run_id;
COMMIT;
