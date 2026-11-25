import os
import time
import json
import unittest
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from contextlib import closing
import psycopg
from lavlah.bounded_transport import bounded_fetch
from lavlah.scheduler import Scheduler
from lavlah.ingestion import IngestionError

def slow_fixture(url):
    time.sleep(10)
    return b"{}"

def fast_fixture(url):
    return b"{}"

def feed(url):
    return json.dumps({"updated_at":(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat(),"records":[{"name":"Fixture","category_slug":"services","description":"Public"}]}).encode()

class DeadlineTests(unittest.TestCase):
    def test_process_deadline(self):
        start=time.monotonic()
        with self.assertRaisesRegex(IngestionError,"timeout"):
            bounded_fetch("https://example.test",slow_fixture,timeout=0.2)
        self.assertLess(time.monotonic()-start,4)
    def test_process_success(self):
        self.assertEqual(bounded_fetch("https://example.test",fast_fixture,timeout=5),b"{}")

@unittest.skipUnless(os.getenv("LAVLAH_SCHEDULER_INTEGRATION")=="1","Disposable database required")
class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.admin=os.environ["LAVLAH_TEST_ADMIN_DSN"]
        self.sql("DELETE FROM lavlah.https_domain_slots")
        self.dsn=os.environ["LAVLAH_INGESTION_DSN"]
        self.actor,self.org=uuid4(),uuid4()
        self.host=str(uuid4())+".example.test"
        self.sql("UPDATE lavlah.collection_jobs SET enabled=false")
        self.sql("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,'Fixture')",(self.actor,str(self.actor)))
        self.sql("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,'Fixture','services')",(self.org,))
    def sql(self,q,args=()):
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                cur=c.execute(q,args)
                return cur.fetchall() if cur.description else None
    def job(self):
        pid=uuid4()
        url="https://"+self.host+"/"+str(pid)
        self.sql("INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days) VALUES (%s,%s,%s,'fixture',%s,now()+interval '2 days',1)",(pid,self.org,url,self.actor))
        self.sql("INSERT INTO lavlah.https_sources(permission_id,endpoint,enabled,min_interval_seconds) VALUES (%s,%s,true,60)",(pid,url))
        self.sql("INSERT INTO lavlah.collection_jobs(permission_id,actor_id,interval_minutes,enabled) VALUES (%s,%s,1440,true)",(pid,self.actor))
        return pid
    def test_domain_and_monitoring(self):
        self.job()
        self.job()
        calls=[]
        def fake(url):
            calls.append(url)
            return feed(url)
        self.assertEqual(Scheduler(self.dsn).run_due(),[])
        s=Scheduler(self.dsn,transport=fake)
        self.assertEqual([r["outcome"] for r in s.run_due()],["success","deferred"])
        self.assertEqual(len(calls),1)
        self.assertTrue(any(r["outcome"]=="success" for r in s.stats()))
    def test_recover_and_fence(self):
        pid=self.job()
        s=Scheduler(self.dsn,transport=feed)
        job,run=s._claim()
        self.assertIsNone(s._claim())
        self.sql("UPDATE lavlah.https_scheduler_runs SET lease_until=now()-interval '1 second' WHERE id=%s",(run,))
        self.assertEqual(s.recover(),1)
        self.assertFalse(s._finish(job,run,"success",1,None))
        self.assertEqual(self.sql("SELECT outcome FROM lavlah.https_scheduler_runs WHERE id=%s",(run,)),[("interrupted",)])
        self.sql("UPDATE lavlah.collection_jobs SET next_run=now() WHERE permission_id=%s",(pid,))
        self.assertEqual(s.run_due()[0]["outcome"],"success")
    def test_revoked_and_timeout(self):
        pid=self.job()
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(pid,))
        def never(url): self.fail("unexpected network")
        self.assertEqual(Scheduler(self.dsn,transport=never).run_due()[0]["outcome"],"blocked")
        self.job()
        def timeout(url): raise IngestionError("timeout")
        result=Scheduler(self.dsn,transport=timeout).run_due()[0]
        self.assertEqual((result["outcome"],result["error_code"]),("failed","timeout"))

    def test_parallel_workers_and_shared_bucket(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        for i in range(8):
            self.host=str(uuid4())+".example.test"
            self.job()
        barrier=Barrier(8)
        def worker(i):
            barrier.wait(timeout=10)
            return Scheduler(self.dsn,transport=feed).run_due(limit=1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=[row for batch in pool.map(worker,range(8)) for row in batch]
        self.assertEqual(sum(row["outcome"]=="success" for row in results),1)
        self.assertEqual(self.sql("SELECT count(*) FROM lavlah.https_observations WHERE permission_id IN (SELECT id FROM lavlah.ingestion_permissions WHERE organization_id=%s)",(self.org,)),[(1,)])
    def test_committed_run_reconciliation(self):
        from lavlah.https_adapter import collect_registered
        pid=self.job()
        s=Scheduler(self.dsn,transport=feed)
        job,run=s._claim()
        collect_registered(self.dsn,pid,self.actor,feed,run_id=run)
        self.sql("UPDATE lavlah.https_scheduler_runs SET lease_until=now()-interval '1 second' WHERE id=%s",(run,))
        self.assertTrue(any(a["code"]=="expired_lease" for a in s.alerts()))
        self.assertEqual(s.recover(),1)
        self.assertEqual(s.recover(),0)
        self.assertEqual(self.sql("SELECT outcome,record_count FROM lavlah.https_scheduler_runs WHERE id=%s",(run,)),[("success",1)])
        self.sql("UPDATE lavlah.collection_jobs SET failures=3 WHERE permission_id=%s",(pid,))
        self.assertTrue(any(a["code"]=="repeated_failure" for a in s.alerts()))
