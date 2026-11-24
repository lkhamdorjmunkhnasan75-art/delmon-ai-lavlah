BEGIN;

DROP TABLE lavlah.sources, lavlah.memberships, lavlah.organizations, lavlah.categories, lavlah.users;
DROP TYPE lavlah.organization_role;
DROP FUNCTION lavlah.request_user_id();
REVOKE USAGE ON SCHEMA lavlah FROM lavlah_request;
DROP SCHEMA lavlah;
DROP ROLE lavlah_request;

COMMIT;
