BEGIN;
DROP TRIGGER reviewer_publication_guard ON lavlah.public_listings;
DROP FUNCTION lavlah.guard_reviewer_publication();
DROP FUNCTION lavlah.lock_memberships(uuid);
COMMIT;
