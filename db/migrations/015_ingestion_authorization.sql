BEGIN;
-- Owner-defined, narrow lock helpers: callers receive only a boolean.
CREATE FUNCTION lavlah.lock_active_permission(pid uuid) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM lavlah.ingestion_permissions
 WHERE id=pid AND NOT revoked AND valid_until>clock_timestamp() FOR SHARE;
 RETURN FOUND;
END;
$$;
CREATE FUNCTION lavlah.lock_actor_grant(pid uuid, actor uuid, required_capability text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF required_capability NOT IN ('collect','review') OR required_capability IS NULL THEN RETURN false; END IF;
 PERFORM 1 FROM lavlah.ingestion_actor_grants
 WHERE permission_id=pid AND user_id=actor AND capability=required_capability FOR SHARE;
 RETURN FOUND;
END;
$$;
REVOKE ALL ON FUNCTION lavlah.lock_active_permission(uuid),lavlah.lock_actor_grant(uuid,uuid,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.lock_active_permission(uuid),lavlah.lock_actor_grant(uuid,uuid,text) TO lavlah_ingestion,lavlah_ingestion_reviewer;
-- Remove ability to supply server-owned review timestamps directly.
REVOKE INSERT ON lavlah.ingestion_reviews,lavlah.publication_audit FROM lavlah_ingestion_reviewer;
GRANT INSERT(candidate_id,reviewer_id,decision,evidence,source_id) ON lavlah.ingestion_reviews TO lavlah_ingestion_reviewer;
GRANT INSERT(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id) ON lavlah.publication_audit TO lavlah_ingestion_reviewer;
COMMIT;
