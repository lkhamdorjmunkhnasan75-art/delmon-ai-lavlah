BEGIN;
DROP TABLE lavlah.api_budgets;
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_rate;
DROP ROLE lavlah_rate;
COMMIT;
