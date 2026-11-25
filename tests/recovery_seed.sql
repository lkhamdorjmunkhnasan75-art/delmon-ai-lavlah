BEGIN;
INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES
 ('e0000000-0000-4000-8000-000000000001','recovery-fixture-1','Synthetic recovery'),
 ('e0000000-0000-4000-8000-000000000002','recovery-fixture-2','Synthetic recovery');
INSERT INTO lavlah.organizations(id,name,category_slug) VALUES ('e0000000-0000-4000-8000-000000000003','Synthetic recovery','services');
INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days) VALUES
 ('e0000000-0000-4000-8000-000000000004','e0000000-0000-4000-8000-000000000003','https://recovery.example.test/feed','SYNTHETIC ONLY','e0000000-0000-4000-8000-000000000002',now()+interval '1 day',1);
INSERT INTO lavlah.ingestion_actor_grants VALUES
 ('e0000000-0000-4000-8000-000000000004','e0000000-0000-4000-8000-000000000001','collect'),
 ('e0000000-0000-4000-8000-000000000004','e0000000-0000-4000-8000-000000000002','review');
INSERT INTO lavlah.ingestion_candidates(id,permission_id,submitted_by,name,category_slug,description,digest) VALUES
 ('e0000000-0000-4000-8000-000000000005','e0000000-0000-4000-8000-000000000004','e0000000-0000-4000-8000-000000000001','Synthetic recovery','services','Offline fixture',repeat('a',64));
INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence) VALUES
 ('e0000000-0000-4000-8000-000000000005','e0000000-0000-4000-8000-000000000002','rejected','Synthetic review');
INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision)
 SELECT id,permission_id,'e0000000-0000-4000-8000-000000000003','e0000000-0000-4000-8000-000000000002',digest,observed_at,'rejected' FROM lavlah.ingestion_candidates WHERE id='e0000000-0000-4000-8000-000000000005';
INSERT INTO lavlah.mock_inquiries VALUES ('e0000000-0000-4000-8000-000000000006','e0000000-0000-4000-8000-000000000007','e0000000-0000-4000-8000-000000000001','personal','resolved',NULL);
INSERT INTO lavlah.mock_payments(id,actor_id,subject_id,kind,amount_mnt,state) VALUES ('e0000000-0000-4000-8000-000000000008','e0000000-0000-4000-8000-000000000001','e0000000-0000-4000-8000-000000000006','inquiry',1000,'authorized');
INSERT INTO lavlah.mock_ledger(payment_id,event,amount_mnt) VALUES ('e0000000-0000-4000-8000-000000000008','authorize',1000);
UPDATE lavlah.mock_payments SET state='captured' WHERE id='e0000000-0000-4000-8000-000000000008';
INSERT INTO lavlah.mock_ledger(payment_id,event,amount_mnt) VALUES ('e0000000-0000-4000-8000-000000000008','capture',1000);
INSERT INTO lavlah.mock_callbacks(id,actor_id,operation,payload_sha256) VALUES ('e0000000-0000-4000-8000-000000000009','e0000000-0000-4000-8000-000000000001','finish',repeat('b',64));
INSERT INTO lavlah.mock_commands VALUES ('e0000000-0000-4000-8000-000000000009','e0000000-0000-4000-8000-000000000001','{"op":"finish"}','{"charged_mnt":1000}');
INSERT INTO lavlah.chat_usage(id,user_id,outcome,estimated_micro_mnt) VALUES ('e0000000-0000-4000-8000-000000000010','e0000000-0000-4000-8000-000000000001','matched',500);
INSERT INTO lavlah.chat_feedback VALUES ('e0000000-0000-4000-8000-000000000010','e0000000-0000-4000-8000-000000000001',1);
COMMIT;
