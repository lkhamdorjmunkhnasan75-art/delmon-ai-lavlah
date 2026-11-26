BEGIN;
CREATE ROLE lavlah_publication_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
GRANT USAGE,CREATE ON SCHEMA lavlah TO lavlah_publication_owner;
GRANT SELECT ON lavlah.ingestion_candidates,lavlah.ingestion_permissions,lavlah.ingestion_actor_grants,lavlah.ingestion_reviews,lavlah.public_listings,lavlah.sources TO lavlah_publication_owner;
GRANT EXECUTE ON FUNCTION lavlah.lock_active_permission(uuid),lavlah.lock_actor_grant(uuid,uuid,text) TO lavlah_publication_owner;
GRANT INSERT(organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at) ON lavlah.sources TO lavlah_publication_owner;
CREATE POLICY atomic_review_sources ON lavlah.sources TO lavlah_publication_owner USING (true) WITH CHECK (true);
GRANT INSERT(candidate_id,reviewer_id,decision,evidence,source_id) ON lavlah.ingestion_reviews TO lavlah_publication_owner;
GRANT INSERT(organization_id,source_id,name,category_slug,description,public_source_url,approved_at),UPDATE(source_id,name,category_slug,description,public_source_url,approved_at) ON lavlah.public_listings TO lavlah_publication_owner;
GRANT INSERT(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id) ON lavlah.publication_audit TO lavlah_publication_owner;
CREATE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
 candidate lavlah.ingestion_candidates%ROWTYPE;
 permission_row lavlah.ingestion_permissions%ROWTYPE;
 sid uuid;
 previous_observed timestamptz;
 expiry timestamptz;
 stamp timestamptz;
BEGIN
 IF cid IS NULL OR actor IS NULL OR approve IS NULL OR evidence_text IS NULL OR length(btrim(evidence_text)) NOT BETWEEN 1 AND 2000 THEN
  RAISE EXCEPTION 'Invalid review input' USING ERRCODE='42501';
 END IF;
 SELECT * INTO candidate FROM lavlah.ingestion_candidates WHERE id=cid;
 IF NOT FOUND OR candidate.submitted_by=actor THEN RAISE EXCEPTION 'Independent reviewer required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(candidate.permission_id::text,7));
 IF NOT lavlah.lock_active_permission(candidate.permission_id) OR NOT lavlah.lock_actor_grant(candidate.permission_id,actor,'review') THEN
  RAISE EXCEPTION 'Review not authorized' USING ERRCODE='42501';
 END IF;
 SELECT * INTO permission_row FROM lavlah.ingestion_permissions WHERE id=candidate.permission_id;
 PERFORM pg_advisory_xact_lock(hashtextextended(permission_row.organization_id::text,12));
 IF EXISTS(SELECT 1 FROM lavlah.ingestion_reviews WHERE candidate_id=cid) THEN RAISE EXCEPTION 'Already reviewed' USING ERRCODE='42501'; END IF;
 stamp:=clock_timestamp();
 IF permission_row.valid_until<=stamp THEN RAISE EXCEPTION 'Permission expired' USING ERRCODE='42501'; END IF;
 IF approve THEN
  SELECT s.observed_at INTO previous_observed FROM lavlah.public_listings p JOIN lavlah.sources s ON s.id=p.source_id WHERE p.organization_id=permission_row.organization_id;
  expiry:=least(permission_row.valid_until,candidate.observed_at+permission_row.freshness_days*interval '1 day');
  IF expiry<=stamp OR candidate.observed_at>stamp OR previous_observed>=candidate.observed_at THEN RAISE EXCEPTION 'Stale or invalid observation' USING ERRCODE='42501'; END IF;
  INSERT INTO lavlah.sources(organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at)
   VALUES(permission_row.organization_id,candidate.submitted_by,permission_row.source_url,permission_row.evidence,candidate.observed_at,actor,stamp,expiry) RETURNING id INTO sid;
 END IF;
 INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence,source_id)
 VALUES(cid,actor,CASE WHEN approve THEN 'approved' ELSE 'rejected' END,evidence_text,sid);
 IF approve THEN
  INSERT INTO lavlah.public_listings(organization_id,source_id,name,category_slug,description,public_source_url,approved_at)
  VALUES(permission_row.organization_id,sid,candidate.name,candidate.category_slug,candidate.description,permission_row.source_url,stamp)
  ON CONFLICT(organization_id) DO UPDATE SET source_id=excluded.source_id,name=excluded.name,category_slug=excluded.category_slug,description=excluded.description,public_source_url=excluded.public_source_url,approved_at=excluded.approved_at;
 END IF;
 INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id)
 VALUES(cid,candidate.permission_id,permission_row.organization_id,actor,candidate.digest,candidate.observed_at,CASE WHEN approve THEN 'approved' ELSE 'rejected' END,sid);
 IF permission_row.valid_until<=clock_timestamp() THEN RAISE EXCEPTION 'Permission expired' USING ERRCODE='42501'; END IF;
 RETURN sid;
END;
$$;
ALTER FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) OWNER TO lavlah_publication_owner;
REVOKE CREATE ON SCHEMA lavlah FROM lavlah_publication_owner;
REVOKE ALL ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) TO lavlah_ingestion_reviewer;
REVOKE INSERT ON lavlah.sources FROM lavlah_ingestion_reviewer;
REVOKE INSERT,UPDATE ON lavlah.public_listings FROM lavlah_ingestion_reviewer;
REVOKE INSERT(candidate_id,reviewer_id,decision,evidence,source_id) ON lavlah.ingestion_reviews FROM lavlah_ingestion_reviewer;
REVOKE INSERT(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,source_id) ON lavlah.publication_audit FROM lavlah_ingestion_reviewer;
COMMIT;
