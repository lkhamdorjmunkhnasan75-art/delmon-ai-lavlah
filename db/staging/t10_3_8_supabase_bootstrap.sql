-- STAGING ONLY. Source commit daa08bd4b16919c6148134f82cc09897f7e461e8.
-- Single transactional bootstrap; never use on a nonempty Lavlah database.
-- The managed PostgreSQL administrator receives temporary ownership access only.
DO $$ BEGIN
 IF current_user <> 'postgres' OR session_user <> 'postgres' OR current_database() <> 'postgres' OR current_setting('server_version_num')::int NOT BETWEEN 170000 AND 179999 THEN RAISE EXCEPTION 'unexpected staging identity or version'; END IF;
 IF EXISTS (SELECT FROM pg_namespace WHERE nspname='lavlah') OR EXISTS (SELECT FROM pg_roles WHERE left(rolname,7)='lavlah_') THEN RAISE EXCEPTION 'Lavlah already exists'; END IF;
 IF current_setting('max_prepared_transactions')::int <> 0 THEN RAISE EXCEPTION 'prepared transactions enabled'; END IF;
END $$;

-- db/migrations/001_directory.sql blob a5d229f2f0083824c34947bad4edc8dd64841dcb
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

-- db/migrations/002_public_directory.sql blob 32cfea462a11c5d3caca7ed8559e6ce7a3e580f2
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

-- db/migrations/003_public_category_names.sql blob 34189d70cecea578f31cbb1541d4e0677163f8af
CREATE VIEW lavlah.public_category_names WITH (security_barrier=true) AS
SELECT DISTINCT c.slug, c.name FROM lavlah.categories c JOIN lavlah.public_directory d ON d.category_slug=c.slug;
REVOKE ALL ON lavlah.public_category_names FROM PUBLIC;
GRANT SELECT ON lavlah.public_category_names TO lavlah_public_reader;

-- db/migrations/004_mock_payments.sql blob fa24510f018f8d375c0a6816e57cba9a07624af7
CREATE ROLE lavlah_mock_billing NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_mock_billing;
CREATE TABLE lavlah.mock_payments (
 id uuid PRIMARY KEY,
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 subject_id uuid NOT NULL,
 kind text NOT NULL CHECK(kind IN ('inquiry','subscription')),
 amount_mnt integer NOT NULL,
 state text NOT NULL CHECK(state IN ('authorized','captured','released','refunded')),
 consent_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(kind,subject_id),
 CHECK((kind='inquiry' AND amount_mnt=1000) OR (kind='subscription' AND amount_mnt=300000))
);
CREATE TABLE lavlah.mock_ledger (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 payment_id uuid NOT NULL REFERENCES lavlah.mock_payments(id),
 event text NOT NULL CHECK(event IN ('authorize','capture','release','refund')),
 amount_mnt integer NOT NULL CHECK(amount_mnt IN (1000,300000)),
 created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(payment_id,event)
);
CREATE TABLE lavlah.mock_commands (
 key uuid PRIMARY KEY,
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 payload jsonb NOT NULL,
 result jsonb NOT NULL
);
CREATE TABLE lavlah.mock_terms (
 payment_id uuid PRIMARY KEY REFERENCES lavlah.mock_payments(id),
 organization_id uuid NOT NULL REFERENCES lavlah.organizations(id),
 starts_on date NOT NULL,
 expires_on date NOT NULL CHECK(expires_on>starts_on)
);
CREATE TABLE lavlah.mock_inquiries (
 id uuid PRIMARY KEY,
 case_id uuid NOT NULL,
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 kind text NOT NULL CHECK(kind IN ('personal','emergency','clarification')),
 state text NOT NULL CHECK(state IN ('open','resolved','failed')),
 prior_id uuid REFERENCES lavlah.mock_inquiries(id),
 CHECK((kind='clarification')=(prior_id IS NOT NULL))
);
REVOKE ALL ON lavlah.mock_payments,lavlah.mock_ledger,lavlah.mock_commands,lavlah.mock_terms,lavlah.mock_inquiries FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,INSERT ON lavlah.mock_payments,lavlah.mock_ledger,lavlah.mock_commands,lavlah.mock_terms,lavlah.mock_inquiries TO lavlah_mock_billing;
GRANT UPDATE(state) ON lavlah.mock_payments,lavlah.mock_inquiries TO lavlah_mock_billing;
GRANT SELECT ON lavlah.memberships TO lavlah_mock_billing;
CREATE POLICY mock_billing_membership ON lavlah.memberships FOR SELECT TO lavlah_mock_billing USING (true);
GRANT USAGE ON SEQUENCE lavlah.mock_ledger_id_seq TO lavlah_mock_billing;

-- db/migrations/005_ingestion.sql blob 9989b9e4c804f5c62dffb36ee93868607bce1d48
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

-- db/migrations/006_collection.sql blob 8e29f9189f71ccaf1af188fc42da661a18d6e6e4
ALTER TABLE lavlah.ingestion_candidates ADD COLUMN observation_day date NOT NULL DEFAULT (timezone('UTC',now())::date);
ALTER TABLE lavlah.ingestion_candidates DROP CONSTRAINT ingestion_candidates_permission_id_digest_key;
ALTER TABLE lavlah.ingestion_candidates ADD UNIQUE(permission_id,digest,observation_day);
CREATE TABLE lavlah.collection_jobs (
 permission_id uuid PRIMARY KEY REFERENCES lavlah.ingestion_permissions(id),
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 interval_minutes integer NOT NULL CHECK(interval_minutes BETWEEN 1440 AND 10080),
 next_run timestamptz NOT NULL DEFAULT now(),
 enabled boolean NOT NULL DEFAULT false,
 failures integer NOT NULL DEFAULT 0 CHECK(failures>=0)
);
CREATE TABLE lavlah.collection_runs (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 permission_id uuid NOT NULL REFERENCES lavlah.collection_jobs(permission_id),
 started_at timestamptz NOT NULL DEFAULT now(),
 outcome text NOT NULL CHECK(outcome IN ('success','failed','blocked')),
 record_count integer NOT NULL CHECK(record_count BETWEEN 0 AND 100),
 error_code text CHECK(error_code IN ('adapter_error','permission_invalid','record_invalid','database_error'))
);
REVOKE ALL ON lavlah.collection_jobs,lavlah.collection_runs FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,UPDATE(next_run,failures) ON lavlah.collection_jobs TO lavlah_ingestion;
GRANT SELECT,INSERT ON lavlah.collection_runs TO lavlah_ingestion;
GRANT USAGE ON SEQUENCE lavlah.collection_runs_id_seq TO lavlah_ingestion;
-- Match only administrator-assigned organization identity; never merge by name alone.
CREATE VIEW lavlah.collection_duplicate_groups WITH (security_barrier=true) AS
SELECT p.organization_id,c.digest,count(DISTINCT c.permission_id) AS source_count
FROM lavlah.ingestion_candidates c JOIN lavlah.ingestion_permissions p ON p.id=c.permission_id
WHERE NOT p.revoked AND p.valid_until>now()
AND c.observed_at+p.freshness_days*interval '1 day'>now()
GROUP BY p.organization_id,c.digest HAVING count(DISTINCT c.permission_id)>1;
REVOKE ALL ON lavlah.collection_duplicate_groups FROM PUBLIC;
GRANT SELECT ON lavlah.collection_duplicate_groups TO lavlah_ingestion_reviewer;

-- db/migrations/007_https_sources.sql blob 8d7c092176afc03ca4834ebe61f21344a0f4e87b
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

-- db/migrations/008_scheduler.sql blob acb2a751ae409d2e063322b6fcb080275a7543fc
CREATE TABLE lavlah.https_domain_slots (
 host text PRIMARY KEY,
 next_at timestamptz NOT NULL
);
CREATE TABLE lavlah.https_scheduler_runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 permission_id uuid NOT NULL REFERENCES lavlah.collection_jobs(permission_id),
 started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 lease_until timestamptz NOT NULL,
 finished_at timestamptz,
 outcome text NOT NULL DEFAULT 'running' CHECK(outcome IN ('running','success','failed','blocked','deferred','interrupted')),
 record_count integer NOT NULL DEFAULT 0 CHECK(record_count BETWEEN 0 AND 100),
 error_code text CHECK(error_code IN ('collection_failed','permission_invalid','rate_limited','timeout','lease_expired','database_error','endpoint_not_authorized')),
 CHECK((outcome='running')=(finished_at IS NULL))
);
CREATE UNIQUE INDEX https_scheduler_active ON lavlah.https_scheduler_runs(permission_id) WHERE outcome='running';
REVOKE ALL ON lavlah.https_domain_slots,lavlah.https_scheduler_runs FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT,INSERT,UPDATE ON lavlah.https_domain_slots,lavlah.https_scheduler_runs TO lavlah_ingestion;
CREATE VIEW lavlah.https_scheduler_stats WITH (security_barrier=true) AS
SELECT outcome,count(*) AS run_count,sum(record_count) AS record_count
FROM lavlah.https_scheduler_runs GROUP BY outcome;
REVOKE ALL ON lavlah.https_scheduler_stats FROM PUBLIC;
GRANT SELECT ON lavlah.https_scheduler_stats TO lavlah_ingestion,lavlah_ingestion_reviewer;

-- db/migrations/009_reliability.sql blob 8513da7031fa0b51228de52eeb93b6ec098aba94
ALTER TABLE lavlah.https_observations ADD COLUMN scheduler_run_id uuid UNIQUE REFERENCES lavlah.https_scheduler_runs(id);
-- Deliberately conservative shared bucket: all subdomains under an approved
-- administrative suffix can be grouped. Unmapped hosts use the global bucket.
CREATE TABLE lavlah.https_domain_groups (
 host text PRIMARY KEY CHECK(host=lower(host) AND host ~ '^[a-z0-9.-]+$'),
 group_key text NOT NULL CHECK(group_key ~ '^[a-z0-9.-]+$')
);
REVOKE ALL ON lavlah.https_domain_groups FROM PUBLIC,lavlah_request,lavlah_public_reader;
GRANT SELECT ON lavlah.https_domain_groups TO lavlah_ingestion;
CREATE VIEW lavlah.scheduler_alerts WITH (security_barrier=true) AS
SELECT 'expired_lease'::text AS code,count(*) AS affected FROM lavlah.https_scheduler_runs
WHERE outcome='running' AND lease_until<=clock_timestamp() HAVING count(*)>0
UNION ALL SELECT 'repeated_failure',count(*) FROM lavlah.collection_jobs
WHERE enabled AND failures>=3 HAVING count(*)>0
UNION ALL SELECT 'interrupted_recently',count(*) FROM lavlah.https_scheduler_runs
WHERE outcome='interrupted' AND finished_at>clock_timestamp()-interval '1 day' HAVING count(*)>0;
REVOKE ALL ON lavlah.scheduler_alerts FROM PUBLIC;
GRANT SELECT ON lavlah.scheduler_alerts TO lavlah_ingestion,lavlah_ingestion_reviewer;

-- db/migrations/010_identity.sql blob 8c38c6eaaadbe798109450cd233d67d6bdbefe94
CREATE ROLE lavlah_identity NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_identity;
CREATE TABLE lavlah.identity_revocations(jti uuid PRIMARY KEY, expires_at timestamptz NOT NULL);
REVOKE ALL ON lavlah.identity_revocations FROM PUBLIC;
GRANT SELECT,INSERT ON lavlah.identity_revocations TO lavlah_identity;
GRANT SELECT(id,auth_subject) ON lavlah.users TO lavlah_identity;
CREATE POLICY identity_subject_lookup ON lavlah.users FOR SELECT TO lavlah_identity USING (true);
GRANT lavlah_request TO lavlah_identity;

-- db/migrations/011_api_limits.sql blob 1ccd6255806c6a73b9730a39322549d5160a9bca
CREATE ROLE lavlah_rate NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_rate;
CREATE TABLE lavlah.api_budgets (
 bucket text PRIMARY KEY CHECK(length(bucket) BETWEEN 1 AND 100),
 window_start bigint NOT NULL,
 hits integer NOT NULL CHECK(hits BETWEEN 1 AND 10000)
);
REVOKE ALL ON lavlah.api_budgets FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON lavlah.api_budgets TO lavlah_rate;

-- db/migrations/012_ingestion_integrity.sql blob 04f7bffefed569160bb57f05740d3d2a1b97d7cb
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

-- db/migrations/013_billing_integrity.sql blob 16daca576a9d4627b007a55430d1d566db301655
CREATE TABLE lavlah.mock_callbacks (
 id uuid PRIMARY KEY,
 actor_id uuid NOT NULL REFERENCES lavlah.users(id),
 operation text NOT NULL CHECK(operation IN ('finish','refund','subscribe')),
 payload_sha256 text NOT NULL CHECK(payload_sha256 ~ '^[0-9a-f]{64}$'),
 received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
REVOKE ALL ON lavlah.mock_callbacks FROM PUBLIC;
GRANT SELECT,INSERT ON lavlah.mock_callbacks TO lavlah_mock_billing;
ALTER TABLE lavlah.mock_payments ADD UNIQUE(id,amount_mnt);
ALTER TABLE lavlah.mock_ledger ADD CONSTRAINT ledger_payment_amount_fk FOREIGN KEY(payment_id,amount_mnt) REFERENCES lavlah.mock_payments(id,amount_mnt);
CREATE FUNCTION lavlah.check_mock_transition() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.state<>'authorized' THEN RAISE EXCEPTION 'Initial payment must be authorized' USING ERRCODE='23514'; END IF;
 ELSIF NOT ((OLD.state='authorized' AND NEW.state IN ('captured','released')) OR (OLD.state='captured' AND NEW.state='refunded') OR OLD.state=NEW.state) THEN
   RAISE EXCEPTION 'Invalid payment transition' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER mock_payment_transition BEFORE INSERT OR UPDATE OF state ON lavlah.mock_payments FOR EACH ROW EXECUTE FUNCTION lavlah.check_mock_transition();

-- db/migrations/014_chat_quality.sql blob c4a2b3d23382c5fe2bf22375019bdae3b58d766f
CREATE TABLE lavlah.chat_usage (
 id uuid PRIMARY KEY,
 user_id uuid NOT NULL REFERENCES lavlah.users(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 outcome text NOT NULL CHECK(outcome IN ('matched','clarify','no_result')),
 estimated_micro_mnt integer NOT NULL CHECK(estimated_micro_mnt BETWEEN 0 AND 70000),
 UNIQUE(id,user_id)
);
CREATE INDEX chat_usage_actor_time ON lavlah.chat_usage(user_id,created_at);
CREATE TABLE lavlah.chat_feedback (
 usage_id uuid PRIMARY KEY,
 user_id uuid NOT NULL,
 rating smallint NOT NULL CHECK(rating IN (-1,1)),
 FOREIGN KEY(usage_id,user_id) REFERENCES lavlah.chat_usage(id,user_id)
);
ALTER TABLE lavlah.chat_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE lavlah.chat_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY chat_usage_own ON lavlah.chat_usage TO lavlah_request USING (user_id=lavlah.request_user_id()) WITH CHECK(user_id=lavlah.request_user_id());
CREATE POLICY chat_feedback_own ON lavlah.chat_feedback TO lavlah_request USING (user_id=lavlah.request_user_id()) WITH CHECK(user_id=lavlah.request_user_id());
REVOKE ALL ON lavlah.chat_usage,lavlah.chat_feedback FROM PUBLIC;
GRANT SELECT,INSERT ON lavlah.chat_usage,lavlah.chat_feedback TO lavlah_request;
GRANT UPDATE(rating) ON lavlah.chat_feedback TO lavlah_request;

-- db/migrations/015_ingestion_authorization.sql blob 69b4db22b8f9fd12700ea4b02309891ac51d6454
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

-- db/migrations/016_db_boundary.sql blob 9779c896a09310ef4bb06d488f19a33ecd377e79
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

-- db/migrations/017_atomic_review.sql blob f71bbf4521a9f430b9f02e813737b463e50ed62b
CREATE ROLE lavlah_publication_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
-- Temporary access for managed administrator; revoked after 019.
GRANT lavlah_publication_owner TO postgres WITH SET TRUE, INHERIT TRUE;
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

-- db/migrations/018_reviewer_identity.sql blob 8dd150fb1809d41aca676fdc7c91ce185d214017
-- Provision one dedicated database login per reviewer. Store the catalog OID
-- alongside the name so a dropped and recreated login requires re-provisioning.
CREATE TABLE lavlah.reviewer_login_bindings (
    login_oid oid PRIMARY KEY,
    login_name name NOT NULL UNIQUE,
    user_id uuid NOT NULL UNIQUE REFERENCES lavlah.users(id) ON DELETE CASCADE
);
REVOKE ALL ON lavlah.reviewer_login_bindings FROM PUBLIC, lavlah_ingestion_reviewer;
GRANT SELECT ON lavlah.reviewer_login_bindings TO lavlah_publication_owner;

ALTER FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) RENAME TO atomic_review_internal;
REVOKE EXECUTE ON FUNCTION lavlah.atomic_review_internal(uuid,uuid,boolean,text)
    FROM PUBLIC, lavlah_ingestion_reviewer;

CREATE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    bound_actor uuid;
BEGIN
    SELECT binding.user_id INTO bound_actor
    FROM lavlah.reviewer_login_bindings AS binding
    JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
    WHERE login.rolname=session_user AND login.rolcanlogin;

    IF bound_actor IS NULL OR bound_actor IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'Reviewer identity binding required' USING ERRCODE='42501';
    END IF;

    RETURN lavlah.atomic_review_internal(cid,bound_actor,approve,evidence_text);
END;
$$;

GRANT CREATE ON SCHEMA lavlah TO lavlah_publication_owner;
ALTER FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) OWNER TO lavlah_publication_owner;
REVOKE CREATE ON SCHEMA lavlah FROM lavlah_publication_owner;
REVOKE ALL ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION lavlah.atomic_review(uuid,uuid,boolean,text) TO lavlah_ingestion_reviewer;

-- db/migrations/019_review_transaction_guard.sql blob c6d0e476b689cf26bd9506faad5459d6b75cdff4
-- PostgreSQL requires UPDATE privilege on at least one column for FOR SHARE.
-- The NOLOGIN publication owner has no service-role members.
GRANT UPDATE (user_id) ON lavlah.reviewer_login_bindings TO lavlah_publication_owner;

CREATE OR REPLACE FUNCTION lavlah.atomic_review(cid uuid, actor uuid, approve boolean, evidence_text text)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    bound_actor uuid;
BEGIN
    -- The publication ordering checks need fresh snapshots after lock waits.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'Review requires READ COMMITTED' USING ERRCODE='42501';
    END IF;

    SELECT binding.user_id INTO bound_actor
    FROM lavlah.reviewer_login_bindings AS binding
    JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
    WHERE login.rolname=session_user AND login.rolcanlogin
      AND pg_has_role(login.oid, 'lavlah_ingestion_reviewer', 'MEMBER')
    FOR SHARE OF binding;

    IF bound_actor IS NULL OR bound_actor IS DISTINCT FROM actor THEN
        RAISE EXCEPTION 'Reviewer identity binding required' USING ERRCODE='42501';
    END IF;

    RETURN lavlah.atomic_review_internal(cid,bound_actor,approve,evidence_text);
END;
$$;

-- Queue checks for the atomic publication path only. Administrative imports
-- and restoration of historical rows have their own trust boundary.
CREATE FUNCTION lavlah.check_review_at_commit()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE
    pid uuid;
    source_expiry timestamptz;
BEGIN
    SELECT permission_id INTO STRICT pid
    FROM lavlah.ingestion_candidates WHERE id=NEW.candidate_id;

    IF NOT EXISTS (
        SELECT 1
        FROM lavlah.reviewer_login_bindings AS binding
        JOIN pg_roles AS login ON login.oid=binding.login_oid AND login.rolname=binding.login_name
        WHERE login.rolname=session_user AND login.rolcanlogin AND binding.user_id=NEW.reviewer_id
          AND pg_has_role(login.oid, 'lavlah_ingestion_reviewer', 'MEMBER')
    ) OR NOT lavlah.lock_active_permission(pid)
      OR NOT lavlah.lock_actor_grant(pid, NEW.reviewer_id, 'review') THEN
        RAISE EXCEPTION 'Review authorization no longer valid' USING ERRCODE='42501';
    END IF;

    IF NEW.source_id IS NOT NULL THEN
        SELECT expires_at INTO STRICT source_expiry
        FROM lavlah.sources WHERE id=NEW.source_id;
        IF source_expiry <= clock_timestamp() THEN
            RAISE EXCEPTION 'Review source expired' USING ERRCODE='42501';
        END IF;
    END IF;
    RETURN NULL;
END;
$$;

GRANT CREATE ON SCHEMA lavlah TO lavlah_publication_owner;
ALTER FUNCTION lavlah.check_review_at_commit() OWNER TO lavlah_publication_owner;
REVOKE CREATE ON SCHEMA lavlah FROM lavlah_publication_owner;
REVOKE ALL ON FUNCTION lavlah.check_review_at_commit() FROM PUBLIC;

CREATE CONSTRAINT TRIGGER review_authorization_at_commit
AFTER INSERT ON lavlah.ingestion_reviews
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW WHEN (current_user = 'lavlah_publication_owner')
EXECUTE FUNCTION lavlah.check_review_at_commit();

-- Remove only the explicit grant made by the migration administrator. The platform's automatic ADMIN-only creator relationship can remain.
REVOKE lavlah_publication_owner FROM postgres GRANTED BY postgres;
DO $$ BEGIN
 IF EXISTS (SELECT FROM pg_roles WHERE rolname='lavlah_publication_owner' AND (rolcanlogin OR rolbypassrls OR rolsuper OR rolcreaterole OR rolcreatedb OR rolinherit)) THEN RAISE EXCEPTION 'unsafe owner'; END IF;
 IF pg_has_role('postgres','lavlah_publication_owner','USAGE') OR pg_has_role('postgres','lavlah_publication_owner','SET') THEN RAISE EXCEPTION 'residual operational membership'; END IF;
 IF has_schema_privilege('lavlah_publication_owner','lavlah','CREATE') THEN RAISE EXCEPTION 'owner can create'; END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','lavlah_ingestion','lavlah_ingestion_reviewer') AND pg_has_role(oid,'lavlah_publication_owner','MEMBER')) THEN RAISE EXCEPTION 'unexpected owner member'; END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role') AND has_schema_privilege(oid,'lavlah','USAGE')) THEN RAISE EXCEPTION 'API role schema access'; END IF;
 IF has_function_privilege('lavlah_ingestion_reviewer','lavlah.atomic_review_internal(uuid,uuid,boolean,text)','EXECUTE') THEN RAISE EXCEPTION 'internal callable'; END IF;
 IF NOT has_function_privilege('lavlah_ingestion_reviewer','lavlah.atomic_review(uuid,uuid,boolean,text)','EXECUTE') THEN RAISE EXCEPTION 'reviewer missing wrapper'; END IF;
 IF EXISTS (SELECT FROM pg_roles WHERE rolname IN ('anon','authenticated','service_role','lavlah_ingestion') AND has_function_privilege(oid,'lavlah.atomic_review(uuid,uuid,boolean,text)','EXECUTE')) THEN RAISE EXCEPTION 'unexpected wrapper access'; END IF;
 IF (SELECT count(*) FROM pg_proc f JOIN pg_namespace n ON n.oid=f.pronamespace JOIN pg_roles r ON r.oid=f.proowner WHERE n.nspname='lavlah' AND f.proname IN ('atomic_review','atomic_review_internal','check_review_at_commit') AND r.rolname='lavlah_publication_owner' AND f.prosecdef AND f.proconfig @> ARRAY['search_path=pg_catalog']) <> 3 THEN RAISE EXCEPTION 'owner mismatch'; END IF;
 IF has_any_column_privilege('lavlah_ingestion_reviewer','lavlah.public_listings','INSERT') OR has_any_column_privilege('lavlah_ingestion_reviewer','lavlah.public_listings','UPDATE') OR has_any_column_privilege('lavlah_ingestion_reviewer','lavlah.ingestion_reviews','INSERT') OR has_any_column_privilege('lavlah_ingestion_reviewer','lavlah.publication_audit','INSERT') THEN RAISE EXCEPTION 'reviewer direct write'; END IF;
 IF NOT EXISTS (SELECT FROM pg_trigger WHERE tgrelid='lavlah.ingestion_reviews'::regclass AND tgname='review_authorization_at_commit' AND tgdeferrable AND tginitdeferred AND tgenabled='O') THEN RAISE EXCEPTION 'missing commit guard'; END IF;
END $$;
