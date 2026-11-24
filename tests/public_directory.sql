BEGIN;
INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES ('00000000-0000-0000-0000-000000000001','reviewer','Reviewer');
INSERT INTO lavlah.categories VALUES ('services','Services');
INSERT INTO lavlah.organizations(id,name,category_slug) VALUES
('10000000-0000-0000-0000-000000000001','Private changed name','services'),
('10000000-0000-0000-0000-000000000002','Expired','services'),
('10000000-0000-0000-0000-000000000003','Unapproved','services');
INSERT INTO lavlah.sources(id,organization_id,submitted_by,source_url,authorization_reference,observed_at,verified_by,verified_at,expires_at)
SELECT ('20000000-0000-0000-0000-00000000000'||n)::uuid,
 ('10000000-0000-0000-0000-00000000000'||n)::uuid,
 '00000000-0000-0000-0000-000000000001','https://example.test/'||n,'private',
 CURRENT_TIMESTAMP-interval '3 days','00000000-0000-0000-0000-000000000001',
 CURRENT_TIMESTAMP-interval '2 days',CURRENT_TIMESTAMP+CASE WHEN n=2 THEN interval '-1 day' ELSE interval '1 day' END
FROM generate_series(1,3) n;
INSERT INTO lavlah.public_listings(organization_id,source_id,name,category_slug,public_source_url)
SELECT organization_id,id,'Approved '||right(source_url,1),'services',source_url FROM lavlah.sources WHERE right(source_url,1) IN ('1','2');
SET LOCAL ROLE lavlah_public_reader;
DO $$ BEGIN
 IF (SELECT array_agg(name) FROM lavlah.public_directory) IS DISTINCT FROM ARRAY['Approved 1'] THEN
 RAISE EXCEPTION 'Public projection or expiry failed'; END IF;
 BEGIN
 PERFORM authorization_reference FROM lavlah.sources;
 RAISE EXCEPTION 'Private source access allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
 BEGIN
 PERFORM name FROM lavlah.organizations;
 RAISE EXCEPTION 'Tenant access allowed';
 EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END $$;
RESET ROLE;
ROLLBACK;
