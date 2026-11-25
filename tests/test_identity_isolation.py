import base64
import hmac
import json
import os
import time
import unittest
from uuid import uuid4
from unittest.mock import patch, Mock
import psycopg
from fastapi.testclient import TestClient
from lavlah.synthetic_identity import validate, ISSUER, AUDIENCE
from lavlah.identity_store import check_connection, checked_dsn
from lavlah.public_api import app, security
from lavlah.pilot_fixtures import apply, identifier

KEY=b"x"*32
def token(**changes):
    now=int(time.time())
    claims={"iss":ISSUER,"aud":AUDIENCE,"sub":"synthetic-pilot-1","iat":now,"exp":now+120,"jti":str(uuid4())}
    claims.update(changes)
    def enc(v):return base64.urlsafe_b64encode(v).decode().rstrip("=")
    payload=enc(json.dumps({"alg":"HS256","typ":"JWT"}).encode())+"."+enc(json.dumps(claims).encode())
    return payload+"."+enc(hmac.digest(KEY,payload.encode(),"sha256"))

class IdentityTests(unittest.TestCase):
    def test_valid_claims(self):
        self.assertEqual(validate(token(),KEY)["sub"],"synthetic-pilot-1")
    def test_bad_signature(self):
        with self.assertRaises(ValueError):validate(token(),b"y"*32)
    def test_wrong_claims(self):
        for change in ({"iss":"wrong"},{"aud":"wrong"},{"sub":"other"},{"exp":0},{"iat":True},{"jti":"bad"},{"role":"owner"},{"exp":int(time.time())+999}):
            with self.assertRaises(ValueError):validate(token(**change),KEY)
    def test_mode_and_dsn(self):
        with patch.dict(os.environ,{"LAVLAH_ENV":"production","LAVLAH_PILOT_ONLY":"1"}):
            with self.assertRaises(ValueError):checked_dsn("LAVLAH_IDENTITY_DSN","lavlah_identity_login")
        with patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_PILOT_ONLY":"1","LAVLAH_IDENTITY_DSN":"postgresql://lavlah_identity_login@127.0.0.1/postgres"}):
            with self.assertRaises(ValueError):checked_dsn("LAVLAH_IDENTITY_DSN","lavlah_identity_login")
    def test_actual_marker_and_role(self):
        c=Mock()
        row={"db":"lavlah_pilot_test","login":"lavlah_identity_login","addr":"127.0.0.1","marker":"yes","privileged":False}
        c.execute.return_value.fetchone.return_value=row
        check_connection(c,"lavlah_identity_login")
        for change in ({"marker":None},{"privileged":True},{"db":"postgres"},{"addr":"8.8.8.8"},{"login":"postgres"}):
            c.execute.return_value.fetchone.return_value=row|change
            with self.assertRaises(ValueError):check_connection(c,"lavlah_identity_login")

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class IdentityIntegration(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.addCleanup(apply,self.dsn,reset=True)
        with psycopg.connect(self.dsn) as c:
            c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'owner'),(%s,%s,'viewer')",(identifier(1),identifier(100),identifier(2),identifier(101)))
        self.flag=patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_SYNTHETIC_KEY":KEY.hex()})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        security.attempts.clear()
        self.client=TestClient(app)
        self.addCleanup(self.client.close)
    def get(self,t):
        return self.client.get("/v1/pilot/identity/me",headers={"Authorization":"Bearer "+t})
    def test_rls_subject_binding(self):
        for subject,n,role in (("synthetic-pilot-1",100,"owner"),("synthetic-pilot-2",101,"viewer")):
            res=self.get(token(sub=subject))
            self.assertEqual(res.status_code,200,res.text)
            self.assertEqual([x["id"] for x in res.json()["organizations"]],[str(identifier(n))])
            self.assertEqual(res.json()["organizations"][0]["role"],role)
        self.assertEqual(self.get(token(sub="synthetic-pilot-3")).status_code,401)
    def test_revocation(self):
        t=token()
        self.assertEqual(self.get(t).status_code,200)
        res=self.client.post("/v1/pilot/identity/revoke",json={},headers={"Authorization":"Bearer "+t})
        self.assertEqual(res.status_code,200,res.text)
        self.assertEqual(self.get(t).status_code,401)
        self.assertEqual(self.get(token()).status_code,200)
    def test_missing_marker(self):
        with psycopg.connect(self.dsn,autocommit=True) as c:
            c.execute("ALTER DATABASE lavlah_pilot_test RESET lavlah.pilot_only")
        try:
            self.assertEqual(self.get(token()).status_code,401)
            self.assertEqual(self.client.get("/v1/directory").status_code,503)
        finally:
            with psycopg.connect(self.dsn,autocommit=True) as c:
                c.execute("ALTER DATABASE lavlah_pilot_test SET lavlah.pilot_only='yes'")
