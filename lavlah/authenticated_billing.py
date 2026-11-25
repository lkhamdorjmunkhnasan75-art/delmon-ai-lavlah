"""Internal offline pilot only. Callback key is held by trusted synthetic operator."""
import os
import json
import hmac
import hashlib
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from uuid import UUID
from contextlib import closing
import psycopg
from psycopg.rows import dict_row
from lavlah.identity_store import identity_transaction, checked_dsn
from lavlah.mock_billing import MockBilling, BillingConflict

def verify_callback(payload,signature,key,now=None):
    if not isinstance(payload,dict) or not isinstance(key,bytes) or len(key)<32:
        raise BillingConflict("Invalid callback")
    try:
        raw=json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
        if len(raw)>2048 or not isinstance(signature,str) or not hmac.compare_digest(hmac.digest(key,raw,"sha256").hex(),signature):
            raise ValueError()
        op=payload["op"]
        fields={"finish":{"request","resolved"},"refund":{"payment"},"subscribe":{"organization","consent_mnt","on"}}[op]
        if set(payload)!={"op","id","actor","issued_at"}|fields:raise ValueError()
        for k in {"id","actor"}|(fields&{"request","payment","organization"}):
            if str(UUID(payload[k]))!=payload[k]:raise ValueError()
        now=int(time.time()) if now is None else now
        if type(payload["issued_at"]) is not int or not 0<=now-payload["issued_at"]<=300:raise ValueError()
        if op=="finish" and type(payload["resolved"]) is not bool:raise ValueError()
        if op=="subscribe" and (type(payload["consent_mnt"]) is not int or payload["consent_mnt"]!=300000 or payload["on"]!=today().isoformat()):raise ValueError()
        return hashlib.sha256(raw).hexdigest()
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        raise BillingConflict("Invalid callback") from None

def today():
    return datetime.now(ZoneInfo("Asia/Ulaanbaatar")).date()

class AuthenticatedBilling:
    def __init__(self):
        if os.getenv("LAVLAH_BILLING_STRICT")!="1":raise BillingConflict("Strict pilot required")
        self.service=MockBilling(checked_dsn("LAVLAH_BILLING_DSN","lavlah_billing_test"),strict=True)
    @staticmethod
    def actor(c):
        row=c.execute("SELECT id FROM lavlah.users").fetchone()
        if not row:raise BillingConflict("Unknown identity")
        return row["id"]
    def start(self,token,key,request,case,*,prior=None):
        with identity_transaction(token) as c:
            return self.service.start(self.actor(c),key,request,case,prior=prior)
    def authorize(self,token,key,request,consent_mnt):
        with identity_transaction(token) as c:
            return self.service.authorize(self.actor(c),key,request,consent_mnt)
    def entitlements(self,token,organization):
        with identity_transaction(token) as c:
            return self.service.entitlements(self.actor(c),organization,today())
    def callback(self,token,payload,signature):
        try:key=bytes.fromhex(os.environ["LAVLAH_MOCK_CALLBACK_KEY"])
        except (KeyError,ValueError):raise BillingConflict("Callback disabled") from None
        digest=verify_callback(payload,signature,key)
        with identity_transaction(token) as c:
            actor=self.actor(c)
            if str(actor)!=payload["actor"]:raise BillingConflict("Callback identity mismatch")
            op=payload["op"]
            if op=="finish":return self.service.finish(actor,payload["id"],payload["request"],resolved=payload["resolved"],callback=digest)
            if op=="refund":return self.service.refund(actor,payload["id"],payload["payment"],callback=digest)
            return self.service.subscribe(actor,payload["id"],payload["organization"],payload["consent_mnt"],on=today(),callback=digest)
    def reconcile(self):
        """Trusted operator only; aggregate internal ledger consistency, no provider calls."""
        with closing(psycopg.connect(self.service.dsn,connect_timeout=5,row_factory=dict_row)) as c:
            with c.transaction():
                self.service._guard(c)
                c.execute("SET TRANSACTION READ ONLY")
                c.execute("SET LOCAL ROLE lavlah_mock_billing")
                c.execute("SET LOCAL statement_timeout='5s'")
                return c.execute("""WITH events AS (
                  SELECT p.id,p.state,p.amount_mnt,coalesce(array_agg(l.event ORDER BY l.id) FILTER(WHERE l.id IS NOT NULL),ARRAY[]::text[]) AS events
                  FROM lavlah.mock_payments p LEFT JOIN lavlah.mock_ledger l ON l.payment_id=p.id GROUP BY p.id
                ) SELECT count(*) AS payments,
                  count(*) FILTER(WHERE events<>CASE state WHEN 'authorized' THEN ARRAY['authorize'] WHEN 'captured' THEN ARRAY['authorize','capture'] WHEN 'released' THEN ARRAY['authorize','release'] ELSE ARRAY['authorize','capture','refund'] END) AS mismatches,
                  coalesce(sum(amount_mnt) FILTER(WHERE state='captured'),0) AS net_mock_mnt FROM events""").fetchone()
