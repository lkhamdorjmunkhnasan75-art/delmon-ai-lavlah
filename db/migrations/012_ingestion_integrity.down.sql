BEGIN;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM lavlah.publication_audit) OR EXISTS(SELECT 1 FROM lavlah.ingestion_actor_grants)
 THEN RAISE EXCEPTION 'Ingestion integrity history exists'; END IF;
END $$;
DROP TABLE lavlah.publication_audit;
DROP TABLE lavlah.ingestion_actor_grants;
COMMIT;
