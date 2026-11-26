import os
import unittest
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import psycopg
from lavlah.ingestion import IngestionError
from lavlah.authenticated_ingestion import AuthenticatedIngestion
from lavlah.collection import LocalJSONAdapter
from lavlah.https_adapter import public_addresses,collect_registered
from lavlah.pilot_fixtures import apply,identifier
from test_identity_isolation import token,KEY

class IntegrityUnit(unittest.TestCase):
    def test_translation_addresses(self):
        for ip in ("64:ff9b::a00:1","64:ff9b:1::1"):
            with self.assertRaises(IngestionError):
                public_addresses("example.test",lambda *a,**k:[(socket.AF_INET6,socket.SOCK_STREAM,6,"",(ip,443,0,0))])
    def test_symlink_and_fifo(self):
        with TemporaryDirectory() as root:
            pid=uuid4()
            p=Path(root)/(str(pid)+".json")
            other=Path(root)/"other"
            other.write_text("[]")
            p.symlink_to(other)
            with self.assertRaises(IngestionError):LocalJSONAdapter(root).collect({"id":pid})
            p.unlink()
            os.mkfifo(p)
            with self.assertRaises(IngestionError):LocalJSONAdapter(root).collect({"id":pid})
    def test_no_implicit_network(self):
        with self.assertRaises(IngestionError):collect_registered("unused",uuid4(),uuid4())
    def test_explicit_strict_mode(self):
        with patch.dict(os.environ,{"LAVLAH_INGESTION_STRICT":"0"}):
            with self.assertRaises(IngestionError):AuthenticatedIngestion()

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class IntegrityDB(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.pid=uuid4()
        self.org=identifier(102)
        self.actor=identifier(1)
        self.reviewer=identifier(2)
        self.sql("INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days) VALUES (%s,%s,'https://example.test/feed','synthetic',%s,now()+interval '2 days',1)",(self.pid,self.org,self.reviewer))
        self.sql("INSERT INTO lavlah.ingestion_actor_grants VALUES (%s,%s,'collect'),(%s,%s,'review')",(self.pid,self.actor,self.pid,self.reviewer))
        self.addCleanup(self.cleanup)
        flag=patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_INGESTION_STRICT":"1","LAVLAH_SYNTHETIC_KEY":KEY.hex()})
        flag.start()
        self.addCleanup(flag.stop)
        self.s=AuthenticatedIngestion()
    def sql(self,q,args=()):
        with psycopg.connect(self.dsn) as c:
            cur=c.execute(q,args)
            return cur.fetchall() if cur.description else None
    def cleanup(self):
        with psycopg.connect(self.dsn) as c:
            c.execute("DELETE FROM lavlah.publication_audit WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.public_listings WHERE organization_id=%s AND source_id IN (SELECT source_id FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s))",(self.org,self.pid))
            sources=c.execute("SELECT source_id FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s) AND source_id IS NOT NULL",(self.pid,)).fetchall()
            c.execute("DELETE FROM lavlah.ingestion_reviews WHERE candidate_id IN (SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s)",(self.pid,))
            for (source,) in sources:c.execute("DELETE FROM lavlah.sources WHERE id=%s",(source,))
            c.execute("DELETE FROM lavlah.ingestion_candidates WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s",(self.pid,))
            c.execute("DELETE FROM lavlah.ingestion_permissions WHERE id=%s",(self.pid,))
        apply(self.dsn,reset=True)
    def submit(self,name):
        return self.s.submit(token(),self.pid,[{"name":name,"category_slug":"services","description":"synthetic"}])[0]["id"]
    def review(self,candidate):
        return self.s.review(token(sub="synthetic-pilot-2"),candidate,approve=True,evidence="checked")
    def test_actor_permissions(self):
        with self.assertRaises(IngestionError):
            self.s.submit(token(sub="synthetic-pilot-2"),self.pid,[{"name":"fake","category_slug":"services","description":""}])
        candidate=self.submit("fresh")
        with self.assertRaises(IngestionError):
            self.s.review(token(),candidate,approve=True,evidence="self")
        self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[("approved",)])
    def test_newer_wins(self):
        older=self.submit("old")
        self.sql("UPDATE lavlah.ingestion_candidates SET observed_at=now()-interval '1 hour' WHERE id=%s",(older,))
        newer=self.submit("new")
        self.review(newer)
        with self.assertRaises(IngestionError):self.review(older)
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[("new",)])
    def test_concurrent_reviews(self):
        older=self.submit("old")
        self.sql("UPDATE lavlah.ingestion_candidates SET observed_at=now()-interval '1 hour' WHERE id=%s",(older,))
        newer=self.submit("new")
        def run(cid):
            try:self.review(cid)
            except IngestionError:pass
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,[older,newer]))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[("new",)])
    def test_revocation(self):
        candidate=self.submit("new")
        self.review(candidate)
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[])
        with self.assertRaises(IngestionError):self.submit("other")

    def test_reviewer_grant_revoked(self):
        candidate=self.submit("fresh")
        self.sql("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s AND user_id=%s",(self.pid,self.reviewer))
        with self.assertRaises(IngestionError):self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_direct_reviewer_timestamp_denied(self):
        candidate=self.submit("fresh")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("INSERT INTO lavlah.ingestion_reviews(candidate_id,reviewer_id,decision,evidence,reviewed_at) VALUES (%s,%s,'rejected','synthetic',now())",(candidate,self.reviewer))
        self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[("approved",)])

    def test_request_role_cannot_lock_grants(self):
        from lavlah.identity_store import identity_transaction
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with identity_transaction(token()) as c:
                c.execute("SELECT lavlah.lock_actor_grant(%s,%s,'review')",(self.pid,self.reviewer))

    def test_admin_revocation_serializes_with_review(self):
        from threading import Event
        from lavlah.ingestion import require_actor
        candidate=self.submit("fresh")
        authorized=Event()
        release=Event()
        def hold(c,pid,actor,capability):
            require_actor(c,pid,actor,capability)
            if capability=="review":
                authorized.set()
                if not release.wait(4):raise RuntimeError("test synchronization timeout")
        with patch("lavlah.ingestion.require_actor",side_effect=hold):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future=pool.submit(self.review,candidate)
                try:
                    self.assertTrue(authorized.wait(3))
                    for sql,args in (
                        ("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,)),
                        ("DELETE FROM lavlah.ingestion_actor_grants WHERE permission_id=%s AND user_id=%s",(self.pid,self.reviewer)),
                    ):
                        with self.assertRaises(psycopg.errors.LockNotAvailable):
                            with psycopg.connect(self.dsn) as c:
                                c.execute("SET LOCAL lock_timeout='150ms'")
                                c.execute(sql,args)
                finally:
                    release.set()
                self.assertEqual(future.result(timeout=8)["decision"],"approved")
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[])

    def test_admin_first_revocation_blocks_waiting_review(self):
        from threading import Event
        from lavlah.ingestion import permission
        candidate=self.submit("fresh")
        entered=Event()
        def entering(c,pid):
            entered.set()
            return permission(c,pid)
        with patch("lavlah.ingestion.permission",side_effect=entering):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with psycopg.connect(self.dsn) as admin:
                    admin.execute("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
                    future=pool.submit(self.review,candidate)
                    self.assertTrue(entered.wait(3))
                    # Admin commits before the pending lock acquisition may succeed.
                with self.assertRaises(IngestionError):future.result(timeout=8)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_permission_expires_during_review(self):
        from lavlah.ingestion import require_actor
        candidate=self.submit("fresh")
        self.sql("UPDATE lavlah.ingestion_permissions SET valid_until=clock_timestamp()+interval '1 second' WHERE id=%s",(self.pid,))
        def expire(c,pid,actor,capability):
            require_actor(c,pid,actor,capability)
            c.execute("SELECT pg_sleep(1.1)")
        with patch("lavlah.ingestion.require_actor",side_effect=expire):
            with self.assertRaises((IngestionError,psycopg.errors.InsufficientPrivilege)):self.review(candidate)
        self.assertEqual(self.sql("SELECT decision FROM lavlah.ingestion_reviews WHERE candidate_id=%s",(candidate,)),[])
        self.assertEqual(self.sql("SELECT decision FROM lavlah.publication_audit WHERE candidate_id=%s",(candidate,)),[])

    def test_direct_publication_without_review_denied(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("UPDATE lavlah.public_listings SET name='forged' WHERE organization_id=%s",(identifier(100),))
        candidate=self.submit("fresh")
        self.assertEqual(self.review(candidate)["decision"],"approved")

    def test_direct_audit_recorded_at_denied(self):
        candidate=self.submit("fresh")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(os.environ["LAVLAH_REVIEW_DSN"]) as c:
                c.execute("SET LOCAL ROLE lavlah_ingestion_reviewer")
                c.execute("""INSERT INTO lavlah.publication_audit(candidate_id,permission_id,organization_id,reviewer_id,digest,observed_at,decision,recorded_at)
                SELECT id,permission_id,%s,%s,digest,observed_at,'rejected',now() FROM lavlah.ingestion_candidates WHERE id=%s""",(self.org,self.reviewer,candidate))
        self.assertEqual(self.review(candidate)["decision"],"approved")

    def test_definer_catalog_permissions(self):
        rows=self.sql("""SELECT p.proname,p.prosecdef,p.proconfig,
          pg_has_role('lavlah_request',p.proowner,'MEMBER'),
          has_function_privilege('lavlah_request',p.oid,'EXECUTE'),
          EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
          FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
          WHERE n.nspname='lavlah' AND p.proname IN ('lock_memberships','lock_active_permission','lock_actor_grant')""")
        self.assertEqual(len(rows),3)
        for name,definer,config,owner_member,request_exec,public_exec in rows:
            self.assertTrue(definer)
            self.assertIn("search_path=pg_catalog",config)
            self.assertFalse(owner_member or request_exec or public_exec,name)
