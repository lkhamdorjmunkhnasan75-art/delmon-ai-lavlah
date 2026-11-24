import os
import unittest
from uuid import uuid4
from contextlib import closing
import psycopg
from lavlah.ingestion import Ingestion, IngestionError, prepare

class NormalizeTests(unittest.TestCase):
    def test_normalized_duplicate(self):
        a={"name":"Монгол  ХХК","category_slug":"services","description":"Үйлчилгээ"}
        b=dict(a,name=" Монгол ХХК ")
        self.assertEqual(prepare(a),prepare(b))
        with self.assertRaises(IngestionError): prepare(dict(a,private_phone="123"))

@unittest.skipUnless(os.getenv("LAVLAH_INGESTION_INTEGRATION")=="1","Requires disposable database")
class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.admin=os.environ["LAVLAH_TEST_ADMIN_DSN"]
        self.s=Ingestion(os.environ["LAVLAH_INGESTION_DSN"],os.environ["LAVLAH_REVIEW_DSN"])
        self.actor,self.reviewer,self.org,self.grant=[uuid4() for _ in range(4)]
        self.record={"name":"Туршилтын байгууллага","category_slug":"services","description":"Нийтийн мэдээлэл"}
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                for user in (self.actor,self.reviewer):
                    c.execute("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES (%s,%s,'Fixture')",(user,str(user)))
                c.execute("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,'Fixture','services')",(self.org,))
                c.execute("""INSERT INTO lavlah.ingestion_permissions(id,organization_id,source_url,evidence,granted_by,valid_until,freshness_days)
                    VALUES (%s,%s,'https://example.test/authorized','fixture permission',%s,now()+interval '2 days',1)""",(self.grant,self.org,self.reviewer))

    def submit(self):
        return self.s.submit(self.grant,self.actor,[self.record])[0]["id"]

    def public(self):
        with closing(psycopg.connect(os.environ["LAVLAH_PUBLIC_DSN"])) as c:
            return c.execute("SELECT name FROM lavlah.public_directory WHERE organization_id=%s",(self.org,)).fetchall()

    def test_review_and_revocation(self):
        candidate=self.submit()
        self.assertIsNotNone(candidate)
        self.assertTrue(self.s.submit(self.grant,self.actor,[dict(self.record,name=" Туршилтын  байгууллага ")])[0]["duplicate"])
        self.assertEqual(self.public(),[])
        with self.assertRaises(IngestionError):
            self.s.review(candidate,self.actor,approve=True,evidence="self")
        self.s.review(candidate,self.reviewer,approve=True,evidence="checked")
        self.assertEqual(self.public(),[(self.record["name"],)])
        with self.assertRaises(IngestionError):
            self.s.review(candidate,self.reviewer,approve=True,evidence="again")
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                c.execute("UPDATE lavlah.ingestion_permissions SET revoked=true WHERE id=%s",(self.grant,))
        self.assertEqual(self.public(),[])
        with self.assertRaises(IngestionError): self.submit()

    def test_rejection_and_expired_candidate(self):
        candidate=self.submit()
        self.s.review(candidate,self.reviewer,approve=False,evidence="not verified")
        self.assertEqual(self.public(),[])
        self.record["description"]="Changed"
        candidate=self.submit()
        with closing(psycopg.connect(self.admin)) as c:
            with c.transaction():
                c.execute("UPDATE lavlah.ingestion_candidates SET observed_at=now()-interval '2 days' WHERE id=%s",(candidate,))
        with self.assertRaises(IngestionError):
            self.s.review(candidate,self.reviewer,approve=True,evidence="stale")
        self.assertEqual(self.public(),[])

    def test_private_queue_and_separate_roles(self):
        candidate=self.submit()
        with closing(psycopg.connect(os.environ["LAVLAH_PUBLIC_DSN"],autocommit=True)) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("SELECT * FROM lavlah.ingestion_candidates")
        with closing(psycopg.connect(os.environ["LAVLAH_INGESTION_DSN"],autocommit=True)) as c:
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("SET ROLE lavlah_ingestion_reviewer")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                c.execute("DELETE FROM lavlah.ingestion_candidates WHERE id=%s",(candidate,))
