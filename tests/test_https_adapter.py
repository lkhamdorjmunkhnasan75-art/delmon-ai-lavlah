import os
import json
import socket
import unittest
from datetime import datetime,timezone,timedelta
from uuid import uuid4
from contextlib import closing
from unittest.mock import patch
import psycopg
from lavlah.https_adapter import endpoint_parts,public_addresses,decode_envelope,collect_registered,fetch_json
from lavlah.ingestion import IngestionError

def envelope(at):
    return json.dumps({"updated_at":at.isoformat(),"records":[{"name":"Fixture","category_slug":"services","description":"Public"}]}).encode()

class HTTPSUnitTests(unittest.TestCase):
    def test_endpoint_validation(self):
        self.assertEqual(endpoint_parts("https://example.test/feed"),("example.test","/feed"))
        for url in ("http://example.test","https://127.0.0.1","https://[::1]","https://example.test:444","https://user@example.test","https://example.test/?secret=x","https://localhost","https://example.test/#x"):
            with self.subTest(url=url),self.assertRaises(IngestionError): endpoint_parts(url)
    def test_dns_rejects_mixed_private_and_public(self):
        def answer(ip):
            return (socket.AF_INET,socket.SOCK_STREAM,6,"",(ip,443))
        for bad in ("127.0.0.1","10.0.0.1","169.254.169.254","100.64.0.1","::1","fc00::1","::ffff:8.8.8.8","224.0.0.1"):
            with self.subTest(ip=bad),self.assertRaises(IngestionError):
                public_addresses("example.test",lambda *a,**k:[answer("8.8.8.8"),answer(bad)])
        self.assertEqual(public_addresses("example.test",lambda *a,**k:[answer("8.8.8.8")]),["8.8.8.8"])
    def test_redirect_not_followed(self):
        with patch("lavlah.https_adapter.public_addresses",return_value=["8.8.8.8"]),patch("lavlah.https_adapter.PinnedHTTPS") as conn:
            conn.return_value.getresponse.return_value.status=302
            with self.assertRaises(IngestionError): fetch_json("https://example.test/feed")
            conn.return_value.request.assert_called_once()
            conn.return_value.close.assert_called_once()
    def test_tls_pins_ip_and_authenticates_hostname(self):
        from lavlah.https_adapter import PinnedHTTPS
        import ssl
        with patch("lavlah.https_adapter.socket.socket") as sock:
            conn=PinnedHTTPS("example.test","8.8.8.8")
            self.assertTrue(conn._context.check_hostname)
            self.assertEqual(conn._context.verify_mode,ssl.CERT_REQUIRED)
            with patch.object(conn._context,"wrap_socket") as wrap:
                conn.connect()
                sock.return_value.connect.assert_called_once_with(("8.8.8.8",443))
                wrap.assert_called_once_with(sock.return_value,server_hostname="example.test")
            with patch.object(conn._context,"wrap_socket",side_effect=ssl.SSLCertVerificationError("fixture")):
                with self.assertRaises(ssl.SSLCertVerificationError): conn.connect()
                sock.return_value.close.assert_called_once()
    def test_freshness_and_schema(self):
        now=datetime.now(timezone.utc)
        records,at,digest=decode_envelope(envelope(now),now,1)
        self.assertEqual(len(records),1)
        self.assertEqual(at,now)
        self.assertEqual(len(digest),64)
        for raw in (envelope(now-timedelta(days=2)),envelope(now+timedelta(seconds=1)),b"{}",b"x"*512001):
            with self.assertRaises(IngestionError): decode_envelope(raw,now,1)

@unittest.skipUnless(os.getenv("LAVLAH_HTTPS_INTEGRATION")=="1","Disposable database required")
class HTTPSDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.admin=os.environ["LAVLAH_TEST_ADMIN_DSN"]
        self.sql("DELETE FROM lavlah.https_domain_slots")
        self.dsn=os.environ["LAVLAH_INGESTION_DSN"]
        self.actor,self.org,self.pid=[uuid4() for _ in range(3)]
        self.sql("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,'Fixture')",(self.actor,str(self.actor)))
        self.sql("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,'Fixture','services')",(self.org,))
        self.sql("INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days) VALUES (%s,%s,'https://example.test/feed','fixture',%s,now()+interval '2 days',1)",(self.pid,self.org,self.actor))
        self.sql("INSERT INTO lavlah.https_sources(permission_id,endpoint,enabled,min_interval_seconds) VALUES (%s,'https://example.test/feed',true,60)",(self.pid,))
    def sql(self,q,args=()):
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                cur=c.execute(q,args)
                return cur.fetchall() if cur.description else None
    def due(self):
        self.sql("UPDATE lavlah.https_sources SET next_fetch_at=now() WHERE permission_id=%s",(self.pid,))
    def test_rate_limit_replay_and_provenance(self):
        at=datetime.now(timezone.utc)-timedelta(seconds=1)
        calls=[]
        def fake(url):
            calls.append(url)
            return envelope(at)
        result=collect_registered(self.dsn,self.pid,self.actor,fake)
        self.assertEqual(result["record_count"],1)
        with self.assertRaisesRegex(IngestionError,"rate_limited"):
            collect_registered(self.dsn,self.pid,self.actor,fake)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.sql("SELECT source_updated_at FROM lavlah.https_observations WHERE permission_id=%s",(self.pid,)),[(at,)])
        self.due()
        with self.assertRaisesRegex(IngestionError,"collection_failed"):
            collect_registered(self.dsn,self.pid,self.actor,fake)
        self.assertEqual(self.sql("SELECT outcome FROM lavlah.https_attempts WHERE permission_id=%s ORDER BY id",(self.pid,)),[("success",),("failed",)])
    def test_revocation_blocks_fetch(self):
        self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
        def never(url):
            self.fail("Network access attempted")
        with self.assertRaises(IngestionError): collect_registered(self.dsn,self.pid,self.actor,never)

    def test_revocation_during_fetch_discards_data(self):
        def fake(url):
            self.sql("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.pid,))
            return envelope(datetime.now(timezone.utc)-timedelta(seconds=1))
        with self.assertRaisesRegex(IngestionError,"collection_failed"):
            collect_registered(self.dsn,self.pid,self.actor,fake)
        self.assertEqual(self.sql("SELECT id FROM lavlah.https_observations WHERE permission_id=%s",(self.pid,)),[])
        self.assertEqual(self.sql("SELECT id FROM lavlah.ingestion_candidates WHERE permission_id=%s",(self.pid,)),[])
        self.assertEqual(self.sql("SELECT outcome FROM lavlah.https_attempts WHERE permission_id=%s",(self.pid,)),[("failed",)])
