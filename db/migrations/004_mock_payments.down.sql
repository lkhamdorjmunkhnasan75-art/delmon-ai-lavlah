BEGIN;
DROP POLICY mock_billing_membership ON lavlah.memberships;
REVOKE SELECT ON lavlah.memberships FROM lavlah_mock_billing;
DROP TABLE lavlah.mock_inquiries,lavlah.mock_commands,lavlah.mock_terms,lavlah.mock_ledger,lavlah.mock_payments;
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_mock_billing;
DROP ROLE lavlah_mock_billing;
COMMIT;
