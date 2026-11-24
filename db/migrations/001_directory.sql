BEGIN;

CREATE ROLE lavlah_request NOLOGIN;
CREATE SCHEMA lavlah;
REVOKE ALL ON SCHEMA lavlah FROM PUBLIC;
GRANT USAGE ON SCHEMA lavlah TO lavlah_request;

CREATE TABLE lavlah.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject text NOT NULL UNIQUE CHECK (btrim(auth_subject) <> ''),
    display_name text NOT NULL CHECK (btrim(display_name) <> '')
);

CREATE TABLE lavlah.categories (
    slug text PRIMARY KEY CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    name text NOT NULL CHECK (btrim(name) <> '')
);

CREATE TABLE lavlah.organizations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL CHECK (btrim(name) <> ''),
    category_slug text NOT NULL REFERENCES lavlah.categories(slug),
    description text NOT NULL DEFAULT ''
);
CREATE INDEX organizations_category_idx ON lavlah.organizations (category_slug);

CREATE TYPE lavlah.organization_role AS ENUM ('owner', 'editor', 'viewer');

CREATE TABLE lavlah.memberships (
    user_id uuid NOT NULL REFERENCES lavlah.users(id) ON DELETE CASCADE,
    organization_id uuid NOT NULL REFERENCES lavlah.organizations(id) ON DELETE CASCADE,
    role lavlah.organization_role NOT NULL,
    PRIMARY KEY (user_id, organization_id)
);
CREATE INDEX memberships_organization_idx ON lavlah.memberships (organization_id);

CREATE TABLE lavlah.sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NOT NULL REFERENCES lavlah.organizations(id),
    submitted_by uuid NOT NULL REFERENCES lavlah.users(id),
    source_url text NOT NULL CHECK (source_url ~ '^https?://[^[:space:]]+$'),
    authorization_reference text NOT NULL CHECK (btrim(authorization_reference) <> ''),
    observed_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified_by uuid REFERENCES lavlah.users(id),
    verified_at timestamptz,
    expires_at timestamptz,
    CHECK (
        (verified_by IS NULL AND verified_at IS NULL AND expires_at IS NULL)
        OR (
            verified_by IS NOT NULL AND verified_at IS NOT NULL AND expires_at IS NOT NULL
            AND verified_at >= observed_at AND expires_at > verified_at
        )
    )
);
CREATE INDEX sources_organization_idx ON lavlah.sources (organization_id);
CREATE INDEX sources_submitter_idx ON lavlah.sources (submitted_by);
CREATE INDEX sources_verifier_idx ON lavlah.sources (verified_by) WHERE verified_by IS NOT NULL;

CREATE FUNCTION lavlah.request_user_id() RETURNS uuid
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = pg_catalog
AS $$
    SELECT nullif(current_setting('lavlah.user_id', true), '')::uuid
$$;

REVOKE ALL ON FUNCTION lavlah.request_user_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.request_user_id() TO lavlah_request;

ALTER TABLE lavlah.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE lavlah.memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE lavlah.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE lavlah.sources ENABLE ROW LEVEL SECURITY;

GRANT SELECT (id, display_name), UPDATE (display_name) ON lavlah.users TO lavlah_request;
GRANT SELECT ON lavlah.categories, lavlah.memberships, lavlah.organizations, lavlah.sources
    TO lavlah_request;
GRANT UPDATE (name, category_slug, description) ON lavlah.organizations TO lavlah_request;
GRANT INSERT (organization_id, submitted_by, source_url, authorization_reference)
    ON lavlah.sources TO lavlah_request;

CREATE POLICY users_own_profile ON lavlah.users TO lavlah_request
    USING (id = (SELECT lavlah.request_user_id()));

CREATE POLICY memberships_own ON lavlah.memberships FOR SELECT TO lavlah_request
    USING (user_id = (SELECT lavlah.request_user_id()));

CREATE POLICY organizations_read ON lavlah.organizations FOR SELECT TO lavlah_request
    USING (id IN (SELECT organization_id FROM lavlah.memberships));

CREATE POLICY organizations_edit ON lavlah.organizations FOR UPDATE TO lavlah_request
    USING (id IN (SELECT organization_id FROM lavlah.memberships WHERE role IN ('owner', 'editor')));

CREATE POLICY sources_read ON lavlah.sources FOR SELECT TO lavlah_request
    USING (organization_id IN (SELECT organization_id FROM lavlah.memberships));

CREATE POLICY sources_submit ON lavlah.sources FOR INSERT TO lavlah_request
    WITH CHECK (
        submitted_by = (SELECT lavlah.request_user_id())
        AND organization_id IN (
            SELECT organization_id FROM lavlah.memberships WHERE role IN ('owner', 'editor')
        )
    );

COMMIT;
