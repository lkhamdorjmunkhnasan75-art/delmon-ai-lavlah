BEGIN;
CREATE VIEW lavlah.public_category_names WITH (security_barrier=true) AS
SELECT DISTINCT c.slug, c.name FROM lavlah.categories c JOIN lavlah.public_directory d ON d.category_slug=c.slug;
REVOKE ALL ON lavlah.public_category_names FROM PUBLIC;
GRANT SELECT ON lavlah.public_category_names TO lavlah_public_reader;
COMMIT;
