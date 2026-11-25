import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from lavlah.public_api import app
from lavlah.api_limits import reserve, Limited, principal_bucket
import psycopg

class LimitTests(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ,{"LAVLAH_ENABLE_SHARED_LIMITS":"1","LAVLAH_ENV":"pilot"})
        p.start()
        self.addCleanup(p.stop)
        p=patch("lavlah.public_api.pilot_enabled",return_value=True)
        p.start()
        self.addCleanup(p.stop)
        self.c=TestClient(app)
        self.addCleanup(self.c.close)
    def test_retry_after(self):
        with patch("lavlah.public_api.reserve",side_effect=Limited(17)):
            r=self.c.get("/v1/directory")
        self.assertEqual(r.status_code,429)
        self.assertEqual(r.headers["Retry-After"],"17")
        self.assertEqual(r.headers["Cache-Control"],"no-store")
    def test_forwarded_identity_denied(self):
        with patch("lavlah.public_api.reserve") as f:
            r=self.c.get("/v1/directory",headers={"X-Forwarded-For":"8.8.8.8"})
            self.assertEqual(r.status_code,403)
            f.assert_not_called()
    def test_database_failure(self):
        with patch("lavlah.public_api.reserve",side_effect=psycopg.OperationalError("private")):
            r=self.c.get("/v1/directory")
        self.assertEqual(r.status_code,503)
        self.assertNotIn("private",r.text)
    def test_global_and_directory(self):
        with patch("lavlah.public_api.reserve") as f,patch("lavlah.public_api.search_directory",return_value=[]):
            self.assertEqual(self.c.get("/v1/directory").status_code,200)
            f.assert_called_once_with({"global":300,"directory":120})
    def test_production_denied(self):
        with patch.dict(os.environ,{"LAVLAH_ENV":"production"}):
            self.assertEqual(self.c.get("/v1/directory").status_code,503)
    def test_principal_hash(self):
        self.assertEqual(principal_bucket("synthetic-pilot-1"),principal_bucket("synthetic-pilot-1"))
        self.assertNotEqual(principal_bucket("synthetic-pilot-1"),principal_bucket("synthetic-pilot-2"))
        self.assertNotIn("synthetic",principal_bucket("synthetic-pilot-1"))

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class SharedIntegration(unittest.TestCase):
    def setUp(self):
        p=patch.dict(os.environ,{"LAVLAH_ENV":"pilot"})
        p.start()
        self.addCleanup(p.stop)
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        self.clear()
        self.addCleanup(self.clear)
    def clear(self):
        with psycopg.connect(self.dsn) as c:
            c.execute("DELETE FROM lavlah.api_budgets")
    def test_parallel_budget(self):
        def one(_):
            try:
                reserve({"global":8,"principal:a":8})
                return True
            except Limited:return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(one,range(16))),8)
        with psycopg.connect(self.dsn) as c:
            self.assertEqual(c.execute("SELECT hits FROM lavlah.api_budgets WHERE bucket='global'").fetchone()[0],8)
    def test_atomic_rejection(self):
        reserve({"global":10,"principal:a":1})
        with self.assertRaises(Limited):reserve({"global":10,"principal:a":1})
        with psycopg.connect(self.dsn) as c:
            self.assertEqual(c.execute("SELECT hits FROM lavlah.api_budgets WHERE bucket='global'").fetchone()[0],1)
        reserve({"global":10,"principal:b":1})
    def test_expired_window(self):
        reserve({"global":1})
        with psycopg.connect(self.dsn) as c:
            c.execute("UPDATE lavlah.api_budgets SET window_start=window_start-60")
        reserve({"global":1})
