"""Synthetic identity regression tests; no external identity provider."""
import os
import unittest
from unittest.mock import patch, Mock
import psycopg
from lavlah.identity_store import checked_dsn, check_connection, identity_transaction
from lavlah.pilot_fixtures import apply, identifier
from test_identity_isolation import token, KEY

LOGIN = "lavlah_identity_login"
DSN = "postgresql://lavlah_identity_login@127.0.0.1:5432/lavlah_pilot_test"
ENV = {"LAVLAH_ENV":"pilot", "LAVLAH_PILOT_ONLY":"1", "LAVLAH_IDENTITY_DSN":DSN,
       "LAVLAH_SYNTHETIC_KEY":KEY.hex()}

class PreflightTests(unittest.TestCase):
    def test_valid_preflight(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(checked_dsn("LAVLAH_IDENTITY_DSN", LOGIN), DSN)

    def test_modes_denied_before_connection(self):
        for mode in ("", "production", "development", "unknown", "Pilot"):
            with self.subTest(mode=mode), patch.dict(os.environ, ENV | {"LAVLAH_ENV":mode}, clear=True):
                with patch("lavlah.identity_store.psycopg.connect") as connect:
                    with self.assertRaises(ValueError):
                        with identity_transaction(token()): pass
                    connect.assert_not_called()

    def test_missing_configuration_denied(self):
        for missing in ("LAVLAH_ENV", "LAVLAH_PILOT_ONLY", "LAVLAH_IDENTITY_DSN", "LAVLAH_SYNTHETIC_KEY"):
            with self.subTest(missing=missing), patch.dict(os.environ, {k:v for k,v in ENV.items() if k!=missing}, clear=True):
                with patch("lavlah.identity_store.psycopg.connect") as connect:
                    with self.assertRaises(ValueError):
                        with identity_transaction(token()): pass
                    connect.assert_not_called()

    def test_bad_dsn_denied_before_connection(self):
        for dsn in ("invalid dsn", DSN.replace(":5432",":5433"), DSN.replace("127.0.0.1","localhost"),
                    DSN.replace("lavlah_pilot_test","postgres"), DSN.replace(LOGIN,"postgres"),
                    DSN+"?sslmode=invalid", DSN+"?options=-cfoo"):
            with self.subTest(case=dsn.split("?")[0].split("@")[-1]), patch.dict(os.environ, ENV | {"LAVLAH_IDENTITY_DSN":dsn}, clear=True):
                with patch("lavlah.identity_store.psycopg.connect") as connect:
                    with self.assertRaises(ValueError):
                        with identity_transaction(token()): pass
                    connect.assert_not_called()

    def test_inherited_routing_options_denied(self):
        for key in ("PGHOSTADDR","PGSERVICE","PGSERVICEFILE","PGOPTIONS","PGPORT","PGTARGETSESSIONATTRS","PGLOADBALANCEHOSTS"):
            with self.subTest(key=key), patch.dict(os.environ, ENV | {key:""}, clear=True):
                with self.assertRaises(ValueError):
                    checked_dsn("LAVLAH_IDENTITY_DSN", LOGIN)

    def test_non_tcp_connection_denied(self):
        c=Mock()
        c.execute.return_value.fetchone.return_value={"db":"lavlah_pilot_test","login":LOGIN,
            "addr":None,"marker":"yes","privileged":False}
        with self.assertRaises(ValueError): check_connection(c, LOGIN)

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class TenantBoundaryDB(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.addCleanup(apply,self.dsn,reset=True)
        with psycopg.connect(self.dsn) as c:
            c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'owner'),(%s,%s,'viewer')",
                      (identifier(1),identifier(100),identifier(2),identifier(101)))
        flag=patch.dict(os.environ,{"LAVLAH_ENV":"pilot","LAVLAH_SYNTHETIC_KEY":KEY.hex()})
        flag.start()
        self.addCleanup(flag.stop)

    def test_cross_tenant_read_and_update(self):
        with identity_transaction(token()) as c:
            self.assertEqual(c.execute("SELECT id FROM lavlah.organizations WHERE id=%s",(identifier(101),)).fetchall(),[])
            self.assertEqual(c.execute("UPDATE lavlah.organizations SET description='changed' WHERE id=%s",(identifier(101),)).rowcount,0)
            self.assertEqual(c.execute("UPDATE lavlah.organizations SET description='changed' WHERE id=%s",(identifier(100),)).rowcount,1)

    def test_viewer_cannot_edit_own_tenant(self):
        with identity_transaction(token(sub="synthetic-pilot-2")) as c:
            self.assertEqual(c.execute("SELECT id FROM lavlah.organizations WHERE id=%s",(identifier(101),)).fetchone()["id"],identifier(101))
            self.assertEqual(c.execute("UPDATE lavlah.organizations SET description='changed' WHERE id=%s",(identifier(101),)).rowcount,0)

    def test_membership_revocation_same_token(self):
        t=token()
        with identity_transaction(t) as c:
            self.assertEqual(c.execute("SELECT id FROM lavlah.organizations").fetchone()["id"],identifier(100))
        with psycopg.connect(self.dsn) as c:
            c.execute("DELETE FROM lavlah.memberships WHERE user_id=%s AND organization_id=%s",(identifier(1),identifier(100)))
        with identity_transaction(t) as c:
            self.assertEqual(c.execute("SELECT id FROM lavlah.organizations").fetchall(),[])
            self.assertEqual(c.execute("UPDATE lavlah.organizations SET description='changed' WHERE id=%s",(identifier(100),)).rowcount,0)

    def test_direct_membership_write_denied(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with identity_transaction(token()) as c:
                c.execute("INSERT INTO lavlah.memberships VALUES (%s,%s,'owner')",(identifier(1),identifier(101)))
