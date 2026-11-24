BEGIN;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM lavlah.https_scheduler_runs) OR EXISTS (SELECT 1 FROM lavlah.https_domain_slots) THEN
 RAISE EXCEPTION 'Scheduler history exists; archive before rollback';
END IF; END $$;
DROP VIEW lavlah.https_scheduler_stats;
DROP TABLE lavlah.https_scheduler_runs,lavlah.https_domain_slots;
COMMIT;
