import os
import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import uuid4
from contextlib import closing
import psycopg
from lavlah.collection import LocalJSONAdapter, Runner
from lavlah.ingestion import Ingestion, IngestionError

class AdapterTests(unittest.TestCase):
    def test_local_feed(self):
        with TemporaryDirectory() as root:
            pid=uuid4()
            path=Path(root)/(str(pid)+".json")
            path.write_text(json.dumps([{"name":"Test","category_slug":"services","description":""}]))
            self.assertEqual(len(LocalJSONAdapter(root).collect({"id":pid})),1)
            path.write_bytes(b"x"*512001)
            with self.assertRaises(IngestionError): LocalJSONAdapter(root).collect({"id":pid})

@unittest.skipUnless(os.getenv("LAVLAH_COLLECTION_INTEGRATION")=="1","Disposable database required")
class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.admin=os.environ["LAVLAH_TEST_ADMIN_DSN"]
        self.dsn=os.environ["LAVLAH_INGESTION_DSN"]
        self.actor,self.reviewer,self.org,self.pid=[uuid4() for _ in range(4)]
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/(str(self.pid)+".json")
        self.record={"name":"Туршилт","category_slug":"services","description":"Нийтийн"}
        self.path.write_text(json.dumps([self.record]))
        self.runner=Runner(self.dsn,LocalJSONAdapter(self.temp.name))
        self.service=Ingestion(self.dsn,os.environ["LAVLAH_REVIEW_DSN"])
        self.sql("UPDATE lavlah.collection_jobs SET enabled=false")
        for user in (self.actor,self.reviewer):
            self.sql("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,'Fixture')",(user,str(user)))
        self.sql("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,'Fixture','services')",(self.org,))
        self.sql("""INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days)
        VALUES (%s,%s,'https://example.test/feed','fixture',%s,now()+interval '2 days',1)""",(self.pid,self.org,self.reviewer))
        self.sql("INSERT INTO lavlah.collection_jobs(permission_id,actor_id,interval_minutes,enabled) VALUES (%s,%s,1440,true)",(self.pid,self.actor))
    def sql(self,q,args=()):
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                cur=c.execute(q,args)
                return cur.fetchall() if cur.description else None
    def due(self):
        self.sql("UPDATE lavlah.collection_jobs SET next_run=now() WHERE permission_id=%s",(self.pid,))
    def candidates(self):
        return self.sql("SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s",(self.pid,))
    def test_schedule_refresh_and_expiry(self):
        self.assertEqual(self.runner.run_due()[0]["outcome"],"success")
        self.assertEqual(self.runner.run_due(),[])
        self.due()
        self.runner.run_due()
        self.assertEqual(len(self.candidates()),1)
        self.service.review(self.candidates()[0][0],self.reviewer,approve=True,evidence="checked")
        self.sql("UPDATE lavlah.ingestion_candidates SET observation_day=observation_day-1 WHERE permission_id=%s",(self.pid,))
        self.due()
        self.runner.run_due()
        self.assertEqual(len(self.candidates()),2)
        self.sql("UPDATE lavlah.ingestion_permissions SET valid_until=now()-interval '1 second' WHERE id=%s",(self.pid,))
        self.due()
        self.assertEqual(self.runner.run_due()[0]["outcome"],"blocked")
        self.assertEqual(self.sql("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)),[])
    def test_retry_without_partial_batch(self):
        self.path.write_text(json.dumps([self.record,dict(self.record,private_phone="secret")]))
        self.assertEqual(self.runner.run_due()[0]["error_code"],"record_invalid")
        self.assertEqual(self.candidates(),[])
        self.assertEqual(self.sql("SELECT failures FROM lavlah.collection_jobs WHERE permission_id=%s",(self.pid,)),[(1,)])
        self.path.write_text(json.dumps([self.record]))
        self.due()
        self.assertEqual(self.runner.run_due()[0]["outcome"],"success")
        self.assertEqual(self.sql("SELECT failures FROM lavlah.collection_jobs WHERE permission_id=%s",(self.pid,)),[(0,)])
