BEGIN;
DROP FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text);
ALTER FUNCTION lavlah.atomic_review_internal(uuid,uuid,boolean,text) RENAME TO atomic_review;
GRANT EXECUTE ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) TO lavlah_ingestion_reviewer;
DROP TABLE lavlah.reviewer_login_bindings;
COMMIT;
