BEGIN;
CREATE ROLE lavlah_ingestion NOLOGIN;
CREATE ROLE lavlah_ingestion_reviewer NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_ingestion,lavlah_ingestion_reviewer;
CREATE TABLE lavlah.ingestion_permissions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 organization_id uuid NOT NULL REFERENCES lavlah.organizations(id),
 source_url text NOT NULL CHECK(source_url ~ '^https://[^[:space:]]+$'),
 evidence text NOT NULL CHECK(btrim(evidence)<>''),
 granted_by uuid NOT NULL REFERENCES lavlah.users(id),
 valid_until timestamptz NOT NULL,
 freshness_days integer NOT NULL CHECK(freshness_days BETWEEN 1 AND 365),
 revoked boolean NOT NULL DEFAULT false
);
CREATE TABLE lavlah.ingestion_candidates (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 permission_id uuid NOT NULL REFERENCES lavlah.ingestion_permissions(id),
 submitted_by uuid NOT NULL REFERENCES lavlah.users(id),
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 300),
 category_slug text NOT NULL REFERENCES lavlah.categories(slug),
 description text NOT NULL CHECK(length(description)<=4000),
 digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
 observed_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(permission_id,digest),
 UNIQUE(id,permission_id)
);
CREATE TABLE lavlah.ingestion_reviews (
 candidate_id uuid PRIMARY KEY REFERENCES lavlah.ingestion_candidates(id),
 reviewer_id uuid NOT NULL REFERENCES lavlah.users(id),
 decision text NOT NULL CHECK(decision IN ('approved','rejected')),
 evidence text NOT NULL CHECK(btrim(evidence)<>''),
 reviewed_at timestamptz NOT NULL DEFAULT now(),
 source_id uuid UNIQUE REFERENCES lavlah.sources(id),
 CHECK((decision='approved')=(source_id IS NOT NULL))
);
REVOKE ALL ON lavlah.ingestion_permissions,lavlah.ingestion_candidates,lavlah.ingestion_reviews FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT ON lavlah.ingestion_permissions,lavlah.ingestion_candidates,lavlah.ingestion_reviews TO lavlah_ingestion,lavlah_ingestion_reviewer;
GRANT INSERT ON lavlah.ingestion_candidates TO lavlah_ingestion;
GRANT INSERT ON lavlah.ingestion_reviews TO lavlah_ingestion_reviewer;
GRANT SELECT,INSERT ON lavlah.sources TO lavlah_ingestion_reviewer;
CREATE POLICY ingestion_review_sources ON lavlah.sources TO lavlah_ingestion_reviewer USING (true) WITH CHECK (true);
GRANT SELECT,INSERT,UPDATE ON lavlah.public_listings TO lavlah_ingestion_reviewer;
-- Existing public records remain compatible; new ingestion records require live permission.
CREATE OR REPLACE VIEW lavlah.public_directory WITH (security_barrier=true) AS
SELECT p.organization_id,p.name,p.category_slug,p.description,p.public_source_url AS source_url,s.verified_at,s.expires_at
FROM lavlah.public_listings p JOIN lavlah.sources s ON s.id=p.source_id AND s.organization_id=p.organization_id
WHERE s.verified_at<=CURRENT_TIMESTAMP AND s.expires_at>CURRENT_TIMESTAMP
 AND p.approved_at>=s.verified_at AND p.approved_at<=CURRENT_TIMESTAMP AND p.public_source_url=s.source_url
 AND NOT EXISTS (
 SELECT 1 FROM lavlah.ingestion_reviews r JOIN lavlah.ingestion_candidates c ON c.id=r.candidate_id
 JOIN lavlah.ingestion_permissions a ON a.id=c.permission_id
 WHERE r.source_id=s.id AND (a.revoked OR a.valid_until<=CURRENT_TIMESTAMP)
 );
COMMIT;
