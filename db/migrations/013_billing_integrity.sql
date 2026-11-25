BEGIN;
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
COMMIT;
