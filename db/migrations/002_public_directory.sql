BEGIN;
CREATE ROLE lavlah_public_reader NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_public_reader;
-- Trusted reviewers explicitly approve a snapshot, not mutable tenant fields.
CREATE TABLE lavlah.public_listings (
    organization_id uuid PRIMARY KEY REFERENCES lavlah.organizations(id) ON DELETE CASCADE,
    source_id uuid NOT NULL REFERENCES lavlah.sources(id) ON DELETE CASCADE,
    name text NOT NULL CHECK (btrim(name) <> ''),
    category_slug text NOT NULL REFERENCES lavlah.categories(slug),
    description text NOT NULL DEFAULT '',
    public_source_url text NOT NULL CHECK (public_source_url ~ '^https?://[^[:space:]]+$'),
    approved_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
REVOKE ALL ON lavlah.public_listings FROM PUBLIC, lavlah_request;
CREATE VIEW lavlah.public_directory WITH (security_barrier=true) AS
SELECT p.organization_id, p.name, p.category_slug, p.description,
       p.public_source_url AS source_url, s.verified_at, s.expires_at
FROM lavlah.public_listings p JOIN lavlah.sources s
 ON s.id=p.source_id AND s.organization_id=p.organization_id
WHERE s.verified_at <= CURRENT_TIMESTAMP AND s.expires_at > CURRENT_TIMESTAMP
 AND p.approved_at >= s.verified_at AND p.approved_at <= CURRENT_TIMESTAMP
 AND p.public_source_url = s.source_url;
REVOKE ALL ON lavlah.public_directory FROM PUBLIC;
GRANT SELECT ON lavlah.public_directory TO lavlah_public_reader;
COMMIT;
