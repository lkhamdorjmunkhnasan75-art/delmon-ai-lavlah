BEGIN;
CREATE TABLE lavlah.https_sources (
 permission_id uuid PRIMARY KEY REFERENCES lavlah.ingestion_permissions(id),
 endpoint text NOT NULL CHECK(endpoint ~ '^https://[^[:space:]]+$'),
 enabled boolean NOT NULL DEFAULT false,
 min_interval_seconds integer NOT NULL DEFAULT 3600 CHECK(min_interval_seconds BETWEEN 60 AND 604800),
 next_fetch_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE lavlah.https_observations (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 permission_id uuid NOT NULL REFERENCES lavlah.https_sources(permission_id),
 fetched_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 source_updated_at timestamptz NOT NULL,
 body_sha256 text NOT NULL CHECK(body_sha256 ~ '^[a-f0-9]{64}$'),
 record_count integer NOT NULL CHECK(record_count BETWEEN 1 AND 100),
 CHECK(source_updated_at<=fetched_at)
);
ALTER TABLE lavlah.ingestion_candidates ADD COLUMN https_observation_id bigint REFERENCES lavlah.https_observations(id);
REVOKE ALL ON lavlah.https_sources,lavlah.https_observations FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,UPDATE(next_fetch_at) ON lavlah.https_sources TO lavlah_ingestion;
GRANT SELECT,INSERT ON lavlah.https_observations TO lavlah_ingestion;
GRANT SELECT ON lavlah.https_observations TO lavlah_ingestion_reviewer;
GRANT USAGE ON SEQUENCE lavlah.https_observations_id_seq TO lavlah_ingestion;
CREATE TABLE lavlah.https_attempts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 permission_id uuid NOT NULL REFERENCES lavlah.https_sources(permission_id),
 recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 outcome text NOT NULL CHECK(outcome IN ('success','failed'))
);
REVOKE ALL ON lavlah.https_attempts FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT INSERT,SELECT ON lavlah.https_attempts TO lavlah_ingestion;
GRANT USAGE ON SEQUENCE lavlah.https_attempts_id_seq TO lavlah_ingestion;
COMMIT;
