BEGIN;
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
COMMIT;
