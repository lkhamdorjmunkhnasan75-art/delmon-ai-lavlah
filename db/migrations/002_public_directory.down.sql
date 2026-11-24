BEGIN;
DROP VIEW lavlah.public_directory;
DROP TABLE lavlah.public_listings;
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_public_reader;
DROP ROLE lavlah_public_reader;
COMMIT;
