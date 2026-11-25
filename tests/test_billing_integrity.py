import os
import unittest
import time
import json
import hmac
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import psycopg
from lavlah.authenticated_billing import AuthenticatedBilling,verify_callback,today
from lavlah.mock_billing import BillingConflict
from lavlah.pilot_fixtures import apply,identifier
from test_identity_isolation import token,KEY

CALLBACK_KEY=b"c"*32
def signed(**fields):
    p={"id":str(uuid4()),"actor":str(identifier(1)),"issued_at":int(time.time()),**fields}
    sig=hmac.digest(CALLBACK_KEY,json.dumps(p,sort_keys=True,separators=(",",":")).encode(),"sha256").hex()
    return p,sig

class CallbackTests(unittest.TestCase):
    def test_signature(self):
        p,s=signed(op="finish",request=str(uuid4()),resolved=True)
        self.assertEqual(len(verify_callback(p,s,CALLBACK_KEY)),64)
        with self.assertRaises(BillingConflict):verify_callback(p,"0"*64,CALLBACK_KEY)
    def test_expiry(self):
        p,s=signed(op="finish",request=str(uuid4()),resolved=True,issued_at=int(time.time())-301)
        with self.assertRaises(BillingConflict):verify_callback(p,s,CALLBACK_KEY)
    def test_invalid_outcome(self):
        p,s=signed(op="finish",request=str(uuid4()),resolved=1)
        with self.assertRaises(BillingConflict):verify_callback(p,s,CALLBACK_KEY)
    def test_price_tampering(self):
        p,s=signed(op="subscribe",organization=str(uuid4()),consent_mnt=1,on=today().isoformat())
        with self.assertRaises(BillingConflict):verify_callback(p,s,CALLBACK_KEY)

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class BillingIntegrityDB(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.addCleanup(self.cleanup)
        self.actor=identifier(1)
        self.org=identifier(100)
        self.req=uuid4()
        self.case=uuid4()
        with psycopg.connect(self.dsn) as c:
            c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'owner'),(%s,%s,'viewer')",(self.actor,self.org,identifier(2),self.org))
        p=patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_BILLING_STRICT":"1","LAVLAH_SYNTHETIC_KEY":KEY.hex(),"LAVLAH_MOCK_CALLBACK_KEY":CALLBACK_KEY.hex()})
        p.start()
        self.addCleanup(p.stop)
        self.s=AuthenticatedBilling()
    def cleanup(self):
        with psycopg.connect(self.dsn) as c:
            for table in ("mock_callbacks","mock_commands","mock_ledger","mock_terms","mock_payments","mock_inquiries"):
                c.execute("DELETE FROM lavlah."+table)
        apply(self.dsn,reset=True)
    def start(self,**kw):
        return self.s.start(token(),uuid4(),self.req,self.case,**kw)
    def authorize(self):
        return self.s.authorize(token(),uuid4(),self.req,1000)
    def finish(self,resolved):
        return self.s.callback(token(),*signed(op="finish",request=str(self.req),resolved=resolved))
    def test_consent_and_identity(self):
        self.assertEqual(self.start()["quote_mnt"],1000)
        with self.assertRaises(BillingConflict):self.finish(True)
        with self.assertRaises(BillingConflict):self.s.authorize(token(sub="synthetic-pilot-2"),uuid4(),self.req,1000)
        with self.assertRaises(ValueError):self.s.authorize(token(),uuid4(),self.req,999)
        self.authorize()
        self.assertEqual(self.finish(True)["charged_mnt"],1000)
        self.assertEqual(self.s.reconcile()["mismatches"],0)
    def test_concurrent_callback_and_refund(self):
        self.start()
        payment=self.authorize()["payment"]
        p,s=signed(op="finish",request=str(self.req),resolved=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            out=list(pool.map(lambda _:self.s.callback(token(),p,s),range(4)))
        self.assertEqual(out,[out[0]]*4)
        altered,signature=signed(**dict(p,resolved=False))
        with self.assertRaises(BillingConflict):self.s.callback(token(),altered,signature)
        self.s.callback(token(),*signed(op="refund",payment=payment))
        self.assertEqual(self.s.reconcile()["net_mock_mnt"],0)
        with psycopg.connect(self.dsn) as c:
            self.assertEqual(c.execute("SELECT event FROM lavlah.mock_ledger WHERE payment_id=%s ORDER BY id",(payment,)).fetchall(),[("authorize",),("capture",),("refund",)])
            self.assertEqual(c.execute("SELECT count(*) FROM lavlah.mock_callbacks").fetchone()[0],2)
    def test_free_paths(self):
        self.start()
        self.authorize()
        self.assertEqual(self.finish(False)["released_mnt"],1000)
        self.req=uuid4()
        self.start(emergency=True)
        self.assertEqual(self.finish(True)["charged_mnt"],0)
        self.req=uuid4()
        self.start()
        self.authorize()
        self.finish(True)
        prior=self.req
        self.req=uuid4()
        self.assertEqual(self.start(prior=prior)["quote_mnt"],0)
        self.assertEqual(self.finish(True)["charged_mnt"],0)
        self.assertEqual(self.s.reconcile()["net_mock_mnt"],1000)
    def test_subscription_owner_and_refund(self):
        p,s=signed(op="subscribe",organization=str(self.org),consent_mnt=300000,on=today().isoformat())
        with self.assertRaises(BillingConflict):self.s.callback(token(sub="synthetic-pilot-2"),p,s)
        result=self.s.callback(token(),p,s)
        self.assertEqual(result["charged_mnt"],300000)
        self.assertIn("analytics",self.s.entitlements(token(),self.org))
        self.s.callback(token(),*signed(op="refund",payment=result["payment"]))
        self.assertEqual(self.s.entitlements(token(),self.org),{"basic_listing"})
    def test_db_invariants(self):
        self.start()
        payment=self.authorize()["payment"]
        with psycopg.connect(self.dsn,autocommit=True) as c:
            with self.assertRaises(psycopg.errors.ForeignKeyViolation):
                c.execute("INSERT INTO lavlah.mock_ledger(payment_id,event,amount_mnt) VALUES (%s,'capture',300000)",(payment,))
            with self.assertRaises(psycopg.errors.CheckViolation):
                c.execute("UPDATE lavlah.mock_payments SET state='refunded' WHERE id=%s",(payment,))
        self.assertEqual(self.s.reconcile()["mismatches"],0)
