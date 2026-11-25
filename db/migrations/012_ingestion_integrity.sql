BEGIN;
CREATE TABLE lavlah.ingestion_actor_grants (
 permission_id uuid NOT NULL REFERENCES lavlah.ingestion_permissions(id),
 user_id uuid NOT NULL REFERENCES lavlah.users(id),
 capability text NOT NULL CHECK(capability IN ('collect','review')),
 PRIMARY KEY(permission_id,user_id)
);
REVOKE ALL ON lavlah.ingestion_actor_grants FROM PUBLIC;
GRANT SELECT ON lavlah.ingestion_actor_grants TO lavlah_ingestion,lavlah_ingestion_reviewer;
CREATE TABLE lavlah.publication_audit (
 candidate_id uuid PRIMARY KEY REFERENCES lavlah.ingestion_candidates(id),
 permission_id uuid NOT NULL REFERENCES lavlah.ingestion_permissions(id),
 organization_id uuid NOT NULL REFERENCES lavlah.organizations(id),
 reviewer_id uuid NOT NULL REFERENCES lavlah.users(id),
 digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
 observed_at timestamptz NOT NULL,
 decision text NOT NULL CHECK(decision IN ('approved','rejected')),
 source_id uuid REFERENCES lavlah.sources(id),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK((decision='approved')=(source_id IS NOT NULL))
);
REVOKE ALL ON lavlah.publication_audit FROM PUBLIC;
GRANT SELECT,INSERT ON lavlah.publication_audit TO lavlah_ingestion_reviewer;
COMMIT;
