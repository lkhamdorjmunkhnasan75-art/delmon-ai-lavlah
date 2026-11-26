BEGIN;
REVOKE INSERT(candidate_id,reviewer_id,decision,evidence,source_id) ON lavlah.ingestion_reviews FROM lavlah_ingestion_reviewer;
REVOKE INSERT(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id) ON lavlah.publication_audit FROM lavlah_ingestion_reviewer;
GRANT INSERT ON lavlah.ingestion_reviews,lavlah.publication_audit TO lavlah_ingestion_reviewer;
DROP FUNCTION lavlah.lock_actor_grant(uuid,uuid,text);
DROP FUNCTION lavlah.lock_active_permission(uuid);
COMMIT;
