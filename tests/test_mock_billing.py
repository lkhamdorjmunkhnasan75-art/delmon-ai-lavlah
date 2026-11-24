import os
import unittest
from datetime import date
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import psycopg
from lavlah.mock_billing import MockBilling, BillingConflict, annual_expiry

class CalendarTests(unittest.TestCase):
    def test_leap_year(self):
        self.assertEqual(annual_expiry(date(2028,2,29)),date(2029,2,28))

@unittest.skipUnless(os.getenv("LAVLAH_BILLING_INTEGRATION")=="1","Requires disposable billing database")
class BillingTests(unittest.TestCase):
    def setUp(self):
        self.actor,self.other,self.org,self.req,self.case=[uuid4() for _ in range(5)]
        self.admin=os.environ["LAVLAH_TEST_ADMIN_DSN"]
        self.dsn=os.environ["LAVLAH_BILLING_DSN"]
        self.service=MockBilling(self.dsn)
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                for actor in (self.actor,self.other):
                    c.execute("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,'Fixture')",(actor,str(actor)))
                c.execute("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,'Fixture','services')",(self.org,))
                c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'owner')",(self.actor,self.org))
                c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'viewer')",(self.other,self.org))

    def start(self,**kwargs):
        return self.service.start(self.actor,uuid4(),self.req,self.case,**kwargs)

    def authorize(self):
        return self.service.authorize(self.actor,uuid4(),self.req,1000)

    def finish(self,resolved):
        return self.service.finish(self.actor,uuid4(),self.req,resolved=resolved)

    def ledger(self,payment):
        with closing(psycopg.connect(self.admin)) as c:
            return c.execute("SELECT event,amount_mnt FROM lavlah.mock_ledger WHERE payment_id=%s ORDER BY id",(payment,)).fetchall()

    def test_capture_consent_and_concurrent_retries(self):
        self.start()
        with self.assertRaises(BillingConflict): self.finish(True)
        with self.assertRaises(ValueError): self.service.authorize(self.actor,uuid4(),self.req,1001)
        with self.assertRaises(BillingConflict): self.service.authorize(self.other,uuid4(),self.req,1000)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.authorize(),range(4)))
        self.assertEqual(len({x["payment"] for x in results}),1)
        p=results[0]["payment"]
        key=uuid4()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:self.service.finish(self.actor,key,self.req,resolved=True),range(4)))
        self.assertEqual([r["charged_mnt"] for r in results],[1000]*4)
        self.assertEqual(self.ledger(p),[("authorize",1000),("capture",1000)])
        with self.assertRaises(BillingConflict): self.service.finish(self.actor,key,self.req,resolved=False)
        with self.assertRaises(BillingConflict): self.finish(False)
        self.service.refund(self.actor,uuid4(),p)
        self.service.refund(self.actor,uuid4(),p)
        self.assertEqual(self.ledger(p),[("authorize",1000),("capture",1000),("refund",1000)])

    def test_failed_release_and_free_paths(self):
        self.start()
        p=self.authorize()["payment"]
        self.assertEqual(self.finish(False)["released_mnt"],1000)
        self.finish(False)
        self.assertEqual(self.ledger(p),[("authorize",1000),("release",1000)])
        self.req=uuid4()
        self.start(emergency=True)
        with self.assertRaises(BillingConflict): self.authorize()
        self.assertEqual(self.finish(True)["charged_mnt"],0)
        self.req=uuid4()
        self.start()
        self.authorize()
        self.finish(True)
        prior=self.req
        self.req=uuid4()
        self.assertEqual(self.start(prior=prior)["quote_mnt"],0)
        self.assertEqual(self.finish(True)["charged_mnt"],0)
        with self.assertRaises(BillingConflict):
            self.service.start(self.other,uuid4(),uuid4(),self.case,prior=prior)

    def test_subscription_entitlement_expiry_refund(self):
        on=date(2026,11,24)
        s=self.service
        self.assertEqual(s.entitlements(self.actor,self.org,on),{"basic_listing"})
        with self.assertRaises(BillingConflict): s.subscribe(self.other,uuid4(),self.org,300000,on=on)
        key=uuid4()
        first=s.subscribe(self.actor,key,self.org,300000,on=on)
        self.assertEqual(first,s.subscribe(self.actor,key,self.org,300000,on=on))
        with self.assertRaises(BillingConflict): s.subscribe(self.actor,uuid4(),self.org,300000,on=on)
        self.assertIn("analytics",s.entitlements(self.other,self.org,on))
        self.assertEqual(s.entitlements(self.actor,self.org,date(2027,11,24)),{"basic_listing"})
        p=first["payment"]
        with self.assertRaises(BillingConflict): s.refund(self.other,uuid4(),p)
        s.refund(self.actor,uuid4(),p)
        self.assertEqual(s.entitlements(self.actor,self.org,on),{"basic_listing"})
        self.assertEqual(self.ledger(p),[("authorize",300000),("capture",300000),("refund",300000)])

    def test_ledger_private_and_append_only(self):
        self.start()
        p=self.authorize()["payment"]
        with closing(psycopg.connect(self.dsn,autocommit=True)) as c:
            c.execute("SET ROLE lavlah_mock_billing")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("DELETE FROM lavlah.mock_ledger WHERE payment_id=%s",(p,))
        with closing(psycopg.connect(os.environ["LAVLAH_PUBLIC_DSN"],autocommit=True)) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM lavlah.mock_ledger")
