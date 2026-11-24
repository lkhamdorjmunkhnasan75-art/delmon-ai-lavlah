"""Internal mock billing only. Actor and inquiry outcome must come from trusted server.
No provider calls, bank accounts, real funds or public endpoints.
"""
from datetime import date
from uuid import UUID, uuid4
from contextlib import closing
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from lavlah.subscription import SubscriptionTerm, organization_entitlements

class BillingConflict(ValueError):
    pass

def annual_expiry(start):
    try:
        return start.replace(year=start.year+1)
    except ValueError:
        return start.replace(year=start.year+1, day=28)

class MockBilling:
    def __init__(self, dsn):
        self.dsn=dsn

    def _command(self, actor, key, payload, operation):
        actor, key=UUID(str(actor)), UUID(str(key))
        with closing(psycopg.connect(self.dsn,row_factory=dict_row)) as c:
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_mock_billing")
                c.execute("SET LOCAL statement_timeout='5s'")
                # Serialize by command key; no duplicate execution even on concurrent retry.
                c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(str(key),))
                old=c.execute("SELECT * FROM lavlah.mock_commands WHERE key=%s",(key,)).fetchone()
                if old:
                    if old["actor_id"]!=actor or old["payload"]!=payload:
                        raise BillingConflict("Idempotency key conflict")
                    return old["result"]
                result=operation(c,actor)
                c.execute("INSERT INTO lavlah.mock_commands VALUES (%s,%s,%s,%s)",(key,actor,Jsonb(payload),Jsonb(result)))
                return result

    @staticmethod
    def _event(c,payment,event):
        c.execute("INSERT INTO lavlah.mock_ledger(payment_id,event,amount_mnt) VALUES (%s,%s,%s)",(payment["id"],event,payment["amount_mnt"]))

    @staticmethod
    def _payment(c,actor,subject,kind,amount):
        p=c.execute("""INSERT INTO lavlah.mock_payments(id,actor_id,subject_id,kind,amount_mnt,state)
            VALUES (%s,%s,%s,%s,%s,'authorized') RETURNING *""",(uuid4(),actor,subject,kind,amount)).fetchone()
        MockBilling._event(c,p,"authorize")
        return p

    @staticmethod
    def _transition(c,p,state,event):
        c.execute("UPDATE lavlah.mock_payments SET state=%s WHERE id=%s",(state,p["id"]))
        MockBilling._event(c,p,event)

    def start(self,actor,key,request,case,*,emergency=False,prior=None):
        request,case=UUID(str(request)),UUID(str(case))
        prior=UUID(str(prior)) if prior else None
        if type(emergency) is not bool or (emergency and prior):
            raise ValueError("Invalid inquiry kind")
        def run(c,a):
            kind="emergency" if emergency else "personal"
            if prior:
                p=c.execute("SELECT * FROM lavlah.mock_inquiries WHERE id=%s AND actor_id=%s",(prior,a)).fetchone()
                if not p or p["case_id"]!=case or p["state"]!="resolved" or prior==request:
                    raise BillingConflict("Invalid clarification")
                kind="clarification"
            c.execute("INSERT INTO lavlah.mock_inquiries VALUES (%s,%s,%s,%s,'open',%s)",(request,case,a,kind,prior))
            return {"request":str(request),"kind":kind,"quote_mnt":1000 if kind=="personal" else 0}
        return self._command(actor,key,{"op":"start","request":str(request),"case":str(case),"emergency":emergency,"prior":str(prior) if prior else None},run)

    @staticmethod
    def _inquiry(c,a,request):
        row=c.execute("SELECT * FROM lavlah.mock_inquiries WHERE id=%s AND actor_id=%s FOR UPDATE",(request,a)).fetchone()
        if not row: raise BillingConflict("Inquiry unavailable")
        return row

    @staticmethod
    def _find(c,request):
        return c.execute("SELECT * FROM lavlah.mock_payments WHERE kind='inquiry' AND subject_id=%s FOR UPDATE",(request,)).fetchone()

    def authorize(self,actor,key,request,consent_mnt):
        request=UUID(str(request))
        if type(consent_mnt) is not int or consent_mnt!=1000:
            raise ValueError("Explicit 1000 MNT consent required")
        def run(c,a):
            i=self._inquiry(c,a,request)
            if i["kind"]!="personal" or i["state"]!="open": raise BillingConflict("Cannot authorize")
            p=self._find(c,request)
            if not p: p=self._payment(c,a,request,"inquiry",1000)
            return {"payment":str(p["id"]),"authorized_mnt":1000}
        return self._command(actor,key,{"op":"authorize","request":str(request),"consent_mnt":consent_mnt},run)

    def finish(self,actor,key,request,*,resolved):
        request=UUID(str(request))
        if type(resolved) is not bool: raise ValueError("Boolean outcome required")
        def run(c,a):
            i=self._inquiry(c,a,request)
            p=self._find(c,request)
            target="resolved" if resolved else "failed"
            if i["state"] not in ("open",target): raise BillingConflict("Outcome immutable")
            if i["state"]=="open":
                if resolved and i["kind"]=="personal" and not p: raise BillingConflict("Consent required")
                if p: self._transition(c,p,"captured" if resolved else "released","capture" if resolved else "release")
                c.execute("UPDATE lavlah.mock_inquiries SET state=%s WHERE id=%s",(target,request))
            return {"state":target,"charged_mnt":1000 if resolved and p and p["state"]!="refunded" else 0,"released_mnt":1000 if not resolved and p else 0}
        return self._command(actor,key,{"op":"finish","request":str(request),"resolved":resolved},run)

    def subscribe(self,actor,key,organization,consent_mnt,*,on):
        org=UUID(str(organization))
        if type(consent_mnt) is not int or consent_mnt!=300000 or type(on) is not date:
            raise ValueError("Explicit annual quote and trusted date required")
        def run(c,a):
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,1))",(str(org),))
            member=c.execute("SELECT 1 FROM lavlah.memberships WHERE user_id=%s AND organization_id=%s AND role='owner'",(a,org)).fetchone()
            if not member: raise BillingConflict("Owner required")
            existing=c.execute("""SELECT 1 FROM lavlah.mock_terms t JOIN lavlah.mock_payments p ON p.id=t.payment_id
                WHERE t.organization_id=%s AND p.state='captured' AND t.expires_on>%s""",(org,on)).fetchone()
            if existing: raise BillingConflict("Existing active or future term")
            p=self._payment(c,a,uuid4(),"subscription",300000)
            self._transition(c,p,"captured","capture")
            expires=annual_expiry(on)
            c.execute("INSERT INTO lavlah.mock_terms VALUES (%s,%s,%s,%s)",(p["id"],org,on,expires))
            return {"payment":str(p["id"]),"charged_mnt":300000,"starts_on":on.isoformat(),"expires_on":expires.isoformat()}
        return self._command(actor,key,{"op":"subscribe","org":str(org),"consent_mnt":consent_mnt,"on":on.isoformat()},run)

    def refund(self,actor,key,payment):
        """Internal approved full refund; not exposed to the public."""
        payment=UUID(str(payment))
        def run(c,a):
            p=c.execute("SELECT * FROM lavlah.mock_payments WHERE id=%s AND actor_id=%s FOR UPDATE",(payment,a)).fetchone()
            if not p or p["state"] not in ("captured","refunded"): raise BillingConflict("Refund unavailable")
            if p["state"]=="captured": self._transition(c,p,"refunded","refund")
            return {"payment":str(payment),"refunded_mnt":p["amount_mnt"]}
        return self._command(actor,key,{"op":"refund","payment":str(payment)},run)

    def entitlements(self,actor,organization,on):
        with closing(psycopg.connect(self.dsn,row_factory=dict_row)) as c:
            with c.transaction():
                c.execute("SET LOCAL ROLE lavlah_mock_billing")
                member=c.execute("SELECT 1 FROM lavlah.memberships WHERE user_id=%s AND organization_id=%s",(actor,organization)).fetchone()
                if not member: raise BillingConflict("Membership required")
                row=c.execute("""SELECT t.starts_on,t.expires_on FROM lavlah.mock_terms t JOIN lavlah.mock_payments p ON p.id=t.payment_id
                    WHERE t.organization_id=%s AND p.state='captured' AND t.starts_on<=%s AND t.expires_on>%s""",(organization,on,on)).fetchone()
                return organization_entitlements(on,SubscriptionTerm(**row) if row else None)
