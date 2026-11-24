BEGIN;
CREATE OR REPLACE VIEW lavlah.public_directory WITH (security_barrier=true) AS
SELECT p.organization_id,p.name,p.category_slug,p.description,p.public_source_url AS source_url,s.verified_at,s.expires_at
FROM lavlah.public_listings p JOIN lavlah.sources s ON s.id=p.source_id AND s.organization_id=p.organization_id
WHERE s.verified_at<=CURRENT_TIMESTAMP AND s.expires_at>CURRENT_TIMESTAMP
 AND p.approved_at>=s.verified_at AND p.approved_at<=CURRENT_TIMESTAMP AND p.public_source_url=s.source_url;
-- Invalidate ingestion-published snapshots before removing permission history.
DELETE FROM lavlah.public_listings WHERE source_id IN (SELECT source_id FROM lavlah.ingestion_reviews);
DROP POLICY ingestion_review_sources ON lavlah.sources;
DROP TABLE lavlah.ingestion_reviews,lavlah.ingestion_candidates,lavlah.ingestion_permissions;
REVOKE ALL ON lavlah.sources,lavlah.public_listings FROM lavlah_ingestion_reviewer;
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_ingestion,lavlah_ingestion_reviewer;
DROP ROLE lavlah_ingestion,lavlah_ingestion_reviewer;
COMMIT;
