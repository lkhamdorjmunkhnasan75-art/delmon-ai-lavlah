BEGIN;
DO $$ BEGIN IF EXISTS(SELECT 1 FROM lavlah.mock_callbacks) THEN RAISE EXCEPTION 'Callback audit history exists'; END IF; END $$;
DROP TRIGGER mock_payment_transition ON lavlah.mock_payments;
DROP FUNCTION lavlah.check_mock_transition();
ALTER TABLE lavlah.mock_ledger DROP CONSTRAINT ledger_payment_amount_fk;
ALTER TABLE lavlah.mock_payments DROP CONSTRAINT mock_payments_id_amount_mnt_key;
DROP TABLE lavlah.mock_callbacks;
COMMIT;
