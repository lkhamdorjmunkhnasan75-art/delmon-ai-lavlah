BEGIN;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM lavlah.chat_usage) THEN RAISE EXCEPTION 'Usage history exists'; END IF; END $$;
DROP TABLE lavlah.chat_feedback;
DROP TABLE lavlah.chat_usage;
COMMIT;
