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
from tests.test_identity_isolation import token,KEY

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
        self.org=identifier(103)
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
