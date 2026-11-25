import os
import unittest
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
from lavlah.public_api import app, security
from lavlah.pilot_security import Security, enabled
from tests_pilot_auth import pilot_auth, PASSWORD

class SecurityTests(unittest.TestCase):
    def test_environment_denied(self):
        with patch.dict(os.environ,{"LAVLAH_ENV":"production","LAVLAH_PILOT_ONLY":"1"}):
            self.assertFalse(enabled())
            with TestClient(app) as c:
                self.assertEqual(c.post("/v1/pilot/login",json={"password":PASSWORD}).status_code,404)
    def test_wrong_database_denied(self):
        with patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_PILOT_ONLY":"1","LAVLAH_PUBLIC_DSN":"postgresql://lavlah_integration_login@127.0.0.1/postgres"}):
            self.assertFalse(enabled())
    def test_session_expiry_and_revocation(self):
        clock=Mock(return_value=100)
        s=Security(clock)
        with patch.dict(os.environ,{"LAVLAH_PILOT_PASSWORD":PASSWORD}):
            self.assertIsNone(s.login("wrong"))
            token=s.login(PASSWORD)
            self.assertIsNotNone(s.authorize(token))
            self.assertNotIn(token,s.sessions)
            s.logout(token)
            self.assertIsNone(s.authorize(token))
            token=s.login(PASSWORD)
            clock.return_value=1000
            self.assertIsNone(s.authorize(token))
    def test_rate_window(self):
        clock=Mock(return_value=1)
        s=Security(clock)
        self.assertTrue(s.allow("a",2))
        self.assertTrue(s.allow("a",2))
        self.assertFalse(s.allow("a",2))
        self.assertTrue(s.allow("b",2))
        clock.return_value=61
        self.assertTrue(s.allow("a",2))
    def test_no_auth_and_logout(self):
        with TestClient(app) as c,pilot_auth(c):
            auth=c.headers.pop("Authorization")
            self.assertEqual(c.post("/v1/pilot/grounded-ask",json={"question":"Алтан нар"}).status_code,401)
            c.headers["Authorization"]=auth
            self.assertEqual(c.post("/v1/pilot/logout",json={}).status_code,200)
            self.assertEqual(c.post("/v1/pilot/grounded-ask",json={"question":"Алтан нар"}).status_code,401)
    def test_privacy_and_body_limit(self):
        with TestClient(app) as c,pilot_auth(c):
            res=c.post("/v1/pilot/login",json={"password":"secret-private","extra":"private"})
            self.assertEqual(res.status_code,422)
            self.assertNotIn("secret-private",res.text)
            res=c.post("/v1/pilot/grounded-ask",json={"question":"а"*5000})
            self.assertEqual(res.status_code,413)
            self.assertEqual(res.headers["cache-control"],"no-store")
    def test_login_and_request_rate_limits(self):
        with TestClient(app) as c,pilot_auth(c):
            for _ in range(9):
                self.assertEqual(c.post("/v1/pilot/login",json={"password":"wrong"}).status_code,401)
            self.assertEqual(c.post("/v1/pilot/login",json={"password":PASSWORD}).status_code,429)
            with patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1","LAVLAH_ENABLE_MOCK_AI":"1"}):
                for _ in range(20):
                    self.assertEqual(c.post("/v1/pilot/grounded-ask",json={"question":"Үнэ хэд вэ?"}).status_code,200)
                self.assertEqual(c.post("/v1/pilot/grounded-ask",json={"question":"Үнэ хэд вэ?"}).status_code,429)
    def test_security_logs_no_password(self):
        s=Security()
        with patch.dict(os.environ,{"LAVLAH_PILOT_PASSWORD":PASSWORD}),self.assertLogs("lavlah.pilot_security",level="INFO") as logs:
            s.login("private-wrong")
            token=s.login(PASSWORD)
            s.logout(token)
        for secret in ("private-wrong",PASSWORD,token):
            self.assertNotIn(secret," ".join(logs.output))
