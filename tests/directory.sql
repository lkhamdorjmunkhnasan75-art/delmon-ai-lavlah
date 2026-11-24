BEGIN;

INSERT INTO lavlah.users (id, auth_subject, display_name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'fixture-owner', 'Owner'),
    ('00000000-0000-0000-0000-000000000002', 'fixture-viewer', 'Viewer'),
    ('00000000-0000-0000-0000-000000000003', 'fixture-editor', 'Editor');

INSERT INTO lavlah.categories VALUES ('services', 'Services');
INSERT INTO lavlah.organizations (id, name, category_slug) VALUES
    ('10000000-0000-0000-0000-000000000001', 'First', 'services'),
    ('10000000-0000-0000-0000-000000000002', 'Second', 'services');
INSERT INTO lavlah.memberships VALUES
    ('00000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', 'owner'),
    ('00000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000001', 'viewer'),
    ('00000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000002', 'editor');

SET LOCAL ROLE lavlah_request;
DO $$
DECLARE
    owner_id constant uuid := '00000000-0000-0000-0000-000000000001';
    viewer_id constant uuid := '00000000-0000-0000-0000-000000000002';
    editor_id constant uuid := '00000000-0000-0000-0000-000000000003';
    first_org constant uuid := '10000000-0000-0000-0000-000000000001';
    second_org constant uuid := '10000000-0000-0000-0000-000000000002';
BEGIN
    IF EXISTS (SELECT FROM lavlah.organizations) OR EXISTS (SELECT FROM lavlah.memberships)
       OR EXISTS (SELECT id FROM lavlah.users) OR EXISTS (SELECT FROM lavlah.sources) THEN
        RAISE EXCEPTION 'Missing identity exposed protected data';
    END IF;

    PERFORM set_config('lavlah.user_id', owner_id::text, true);
    IF (SELECT array_agg(id) FROM lavlah.organizations) IS DISTINCT FROM ARRAY[first_org]
       OR (SELECT array_agg(id) FROM lavlah.users) IS DISTINCT FROM ARRAY[owner_id]
       OR (SELECT count(*) FROM lavlah.memberships) <> 1 THEN
        RAISE EXCEPTION 'Owner visibility does not match their profile and membership';
    END IF;
    UPDATE lavlah.organizations SET description = 'updated' WHERE id = first_org;
    IF NOT FOUND THEN RAISE EXCEPTION 'Owner could not update their organization'; END IF;
    UPDATE lavlah.organizations SET description = 'invalid' WHERE id = second_org;
    IF FOUND THEN RAISE EXCEPTION 'Owner modified another organization'; END IF;
    INSERT INTO lavlah.sources (organization_id, submitted_by, source_url, authorization_reference)
        VALUES (first_org, owner_id, 'https://example.test/first', 'fixture-permission');

    BEGIN
        INSERT INTO lavlah.sources (organization_id, submitted_by, source_url, authorization_reference)
            VALUES (first_org, viewer_id, 'https://example.test/invalid', 'fixture-permission');
        RAISE EXCEPTION 'Owner submitted as another user';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;

    BEGIN
        UPDATE lavlah.sources SET verified_at = CURRENT_TIMESTAMP;
        RAISE EXCEPTION 'Owner wrote verification metadata';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;

    BEGIN
        UPDATE lavlah.memberships SET role = 'owner' WHERE user_id = viewer_id;
        RAISE EXCEPTION 'Request role changed membership roles';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;

    PERFORM set_config('lavlah.user_id', viewer_id::text, true);
    IF (SELECT count(*) FROM lavlah.sources) <> 1 THEN
        RAISE EXCEPTION 'Viewer could not read own organization source';
    END IF;
    UPDATE lavlah.organizations SET description = 'invalid' WHERE id = first_org;
    IF FOUND THEN RAISE EXCEPTION 'Viewer modified an organization'; END IF;

    BEGIN
        INSERT INTO lavlah.sources (organization_id, submitted_by, source_url, authorization_reference)
            VALUES (first_org, viewer_id, 'https://example.test/viewer', 'fixture-permission');
        RAISE EXCEPTION 'Viewer submitted a source';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;

    PERFORM set_config('lavlah.user_id', editor_id::text, true);
    IF EXISTS (SELECT FROM lavlah.sources) THEN
        RAISE EXCEPTION 'Editor saw another organization source';
    END IF;
    UPDATE lavlah.organizations SET description = 'updated by editor' WHERE id = second_org;
    IF NOT FOUND THEN RAISE EXCEPTION 'Editor could not update own organization'; END IF;
    INSERT INTO lavlah.sources (organization_id, submitted_by, source_url, authorization_reference)
        VALUES (second_org, editor_id, 'https://example.test/second', 'fixture-permission');

    BEGIN
        INSERT INTO lavlah.sources (organization_id, submitted_by, source_url, authorization_reference)
            VALUES (first_org, editor_id, 'https://example.test/invalid', 'fixture-permission');
        RAISE EXCEPTION 'Editor submitted for another organization';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END
$$;

RESET ROLE;

DO $$
BEGIN
    BEGIN
        UPDATE lavlah.sources SET expires_at = CURRENT_TIMESTAMP;
        RAISE EXCEPTION 'Incomplete verification record was accepted';
    EXCEPTION WHEN check_violation THEN NULL;
    END;
END
$$;

UPDATE lavlah.sources SET
    verified_by = '00000000-0000-0000-0000-000000000003',
    verified_at = CURRENT_TIMESTAMP,
    expires_at = CURRENT_TIMESTAMP + INTERVAL '30 days'
WHERE source_url = 'https://example.test/first';

ROLLBACK;
