BEGIN;
-- Refuse to discard collected provenance.
DO $$ BEGIN IF EXISTS (SELECT 1 FROM lavlah.https_observations) THEN
 RAISE EXCEPTION 'HTTPS observations exist; archive before rollback';
END IF; END $$;
ALTER TABLE lavlah.ingestion_candidates DROP COLUMN https_observation_id;
DROP TABLE lavlah.https_observations,lavlah.https_sources;
COMMIT;
