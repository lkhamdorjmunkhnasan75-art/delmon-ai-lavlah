BEGIN;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM lavlah.identity_revocations) THEN RAISE EXCEPTION 'Revocation history exists'; END IF; END $$;
DROP TABLE lavlah.identity_revocations;
DROP POLICY identity_subject_lookup ON lavlah.users;
REVOKE SELECT(id,auth_subject) ON lavlah.users FROM lavlah_identity;
REVOKE lavlah_request FROM lavlah_identity;
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_identity;
DROP ROLE lavlah_identity;
COMMIT;
