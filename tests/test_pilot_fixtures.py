import os
import unittest
from unittest.mock import patch, Mock
from contextlib import closing
import subprocess
import sys
import psycopg
from fastapi.testclient import TestClient
from lavlah.public_api import app
from lavlah.pilot_fixtures import apply, validate_dsn, guard, identifier, RECORDS

class PilotGuardTests(unittest.TestCase):
    def test_remote_and_wrong_database_rejected_before_connection(self):
        for dsn in ("postgresql://example.test/lavlah_pilot_test",
                    "postgresql://127.0.0.1/postgres",
                    "host=127.0.0.1 dbname=lavlah_pilot_test hostaddr=192.0.2.1"):
            with self.subTest(dsn=dsn), patch("lavlah.pilot_fixtures.psycopg.connect") as connect:
                with self.assertRaises(ValueError): apply(dsn)
                connect.assert_not_called()

    def test_opt_in_required(self):
        with patch.dict(os.environ,{"LAVLAH_PILOT_ONLY":"0"}), patch("lavlah.pilot_fixtures.psycopg.connect") as connect:
            with self.assertRaises(ValueError): apply("postgresql://127.0.0.1/lavlah_pilot_test")
            connect.assert_not_called()

    def test_server_guard(self):
        for row in (("postgres","127.0.0.1"),("lavlah_pilot_test","192.0.2.1")):
            c=Mock()
            c.execute.return_value.fetchone.return_value=row
            with self.assertRaises(ValueError): guard(c)
        c=Mock()
        c.execute.return_value.fetchone.return_value=("lavlah_pilot_test","172.18.0.2/32")
        with patch.dict(os.environ,{"LAVLAH_PILOT_INTEGRATION":"1","LAVLAH_PILOT_CONTAINER_IP":"172.18.0.2"}):
            guard(c)
            c.execute.return_value.fetchone.return_value=("lavlah_pilot_test","172.18.0.3/32")
            with self.assertRaises(ValueError): guard(c)

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class PilotIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        self.client=TestClient(app)
        apply(self.dsn)
    def tearDown(self):
        apply(self.dsn,reset=True)
        self.client.close()
    def search(self,**params):
        res=self.client.get("/v1/directory",params=params)
        self.assertEqual(res.status_code,200,res.text)
        return res.json()["items"]
    def test_mongolian_search_and_categories(self):
        self.assertEqual([r["name"] for r in self.search(q="АЛТАН НАР")],[RECORDS[0][0]])
        self.assertEqual([r["name"] for r in self.search(q="хөх тэнгэр",category="trade")],[RECORDS[1][0]])
        self.assertEqual(self.search(q="хөх",category="services"),[])
    def test_freshness_and_approval(self):
        self.assertEqual({r["name"] for r in self.search()},{RECORDS[0][0],RECORDS[1][0]})
        self.assertEqual(self.search(q="Цагаан уул"),[])
        self.assertEqual(self.search(q="Ногоон тал"),[])
        self.assertTrue(all(r["source_url"].startswith("https://pilot.example.test/") for r in self.search()))
    def test_seed_reset_cli_idempotent(self):
        for _ in range(2):
            subprocess.run([sys.executable,"-m","lavlah.pilot_fixtures","seed"],check=True,timeout=15)
        self.assertEqual(len(self.search()),2)
        for _ in range(2):
            subprocess.run([sys.executable,"-m","lavlah.pilot_fixtures","reset"],check=True,timeout=15)
        self.assertEqual(self.search(),[])
    def test_foreign_data_prevents_reset(self):
        with closing(psycopg.connect(self.dsn)) as c:
            with c.transaction():
                c.execute("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,'foreign-fixture','Foreign fixture')",(identifier(999),))
            try:
                with self.assertRaisesRegex(ValueError,"Non-pilot users"): apply(self.dsn,reset=True)
                self.assertEqual(len(self.search()),2)
            finally:
                with c.transaction(): c.execute("DELETE FROM lavlah.users WHERE id=%s",(identifier(999),))
    def test_marker_required(self):
        with closing(psycopg.connect(self.dsn,autocommit=True)) as c:
            c.execute("ALTER DATABASE lavlah_pilot_test RESET lavlah.pilot_only")
            try:
                with self.assertRaisesRegex(ValueError,"marker"): apply(self.dsn,reset=True)
                self.assertEqual(len(self.search()),2)
            finally:
                c.execute("ALTER DATABASE lavlah_pilot_test SET lavlah.pilot_only='yes'")
