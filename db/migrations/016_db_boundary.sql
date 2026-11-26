BEGIN;
CREATE FUNCTION lavlah.lock_memberships(actor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 PERFORM 1 FROM lavlah.memberships WHERE user_id=actor ORDER BY organization_id FOR SHARE;
END;
$$;
REVOKE ALL ON FUNCTION lavlah.lock_memberships(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.lock_memberships(uuid) TO lavlah_identity;
-- Publication must correspond to an approved review and active source permission.
-- Owner maintenance and synthetic fixture seeding remain outside this reviewer policy.
CREATE FUNCTION lavlah.guard_reviewer_publication() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog AS $$
BEGIN
 IF current_user='lavlah_ingestion_reviewer' AND NOT EXISTS (
  SELECT 1 FROM lavlah.ingestion_reviews r
  JOIN lavlah.ingestion_candidates c ON c.id=r.candidate_id
  JOIN lavlah.ingestion_permissions p ON p.id=c.permission_id
  JOIN lavlah.sources s ON s.id=r.source_id
  WHERE r.decision='approved' AND r.source_id=NEW.source_id
    AND p.organization_id=NEW.organization_id AND s.organization_id=NEW.organization_id
    AND s.verified_by=r.reviewer_id AND c.submitted_by<>r.reviewer_id
    AND NOT p.revoked AND p.valid_until>clock_timestamp()
    AND s.expires_at>clock_timestamp()
    AND c.name=NEW.name AND c.category_slug=NEW.category_slug AND c.description=NEW.description
    AND p.source_url=NEW.public_source_url AND s.source_url=NEW.public_source_url
 ) THEN RAISE EXCEPTION 'Publication requires approved active evidence' USING ERRCODE='42501'; END IF;
 RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION lavlah.guard_reviewer_publication() FROM PUBLIC;
CREATE TRIGGER reviewer_publication_guard BEFORE INSERT OR UPDATE ON lavlah.public_listings
FOR EACH ROW EXECUTE FUNCTION lavlah.guard_reviewer_publication();
COMMIT;
