BEGIN;
CREATE ROLE lavlah_rate NOLOGIN;
GRANT USAGE ON SCHEMA lavlah TO lavlah_rate;
CREATE TABLE lavlah.api_budgets (
 bucket text PRIMARY KEY CHECK(length(bucket) BETWEEN 1 AND 100),
 window_start bigint NOT NULL,
 hits integer NOT NULL CHECK(hits BETWEEN 1 AND 10000)
);
REVOKE ALL ON lavlah.api_budgets FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE,DELETE ON lavlah.api_budgets TO lavlah_rate;
COMMIT;
