"""Integration tests: real PostgreSQL and ASGI HTTP requests, no mocked DB."""
import os
import unittest
from contextlib import closing
import psycopg
from fastapi.testclient import TestClient
from lavlah.public_api import app

@unittest.skipUnless(os.getenv("LAVLAH_INTEGRATION") == "1", "Requires disposable integration DB")
class DirectoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        with closing(psycopg.connect(os.environ["LAVLAH_TEST_ADMIN_DSN"])) as c:
            with c.transaction():
                c.execute("INSERT INTO lavlah.users(id,auth_subject,display_name) VALUES ('00000000-0000-0000-0000-000000000001','fixture','Private reviewer')")
                c.execute("INSERT INTO lavlah.categories VALUES ('services','Services'),('trade','Trade')")
                for n, name, category, status in [
                    (1,"Монгол Алфа","services","valid"),
                    (2,"Монгол Бета","trade","valid"),
                    (3,"Монгол Хугацаа","services","expired"),
                    (4,"Монгол Нууц","services","unapproved"),
                    (5,"Монгол Шалгаагүй","services","unverified"),
                    (6,"Монгол Ирээдүй","services","future"),
                ]:
                    org=f"10000000-0000-0000-0000-{n:012d}"
                    source=f"20000000-0000-0000-0000-{n:012d}"
                    url=f"https://example.test/{n}"
                    c.execute("INSERT INTO lavlah.organizations(id,name,category_slug) VALUES (%s,%s,%s)",(org,"Private "+name,category))
                    c.execute("""INSERT INTO lavlah.sources(id,organization_id,submitted_by,source_url,authorization_reference,observed_at)
                        VALUES (%s,%s,'00000000-0000-0000-0000-000000000001',%s,'private reference',CURRENT_TIMESTAMP-interval '3 days')""",(source,org,url))
                    if status != "unverified":
                        verified="1 day" if status=="future" else "-2 days"
                        expires="-1 day" if status=="expired" else "2 days"
                        c.execute("""UPDATE lavlah.sources SET verified_by=submitted_by,
                            verified_at=CURRENT_TIMESTAMP+%s::interval, expires_at=CURRENT_TIMESTAMP+%s::interval WHERE id=%s""",(verified,expires,source))
                    if status != "unapproved":
                        c.execute("""INSERT INTO lavlah.public_listings(organization_id,source_id,name,category_slug,public_source_url)
                            VALUES (%s,%s,%s,%s,%s)""",(org,source,name,category,url))
    def get(self, **params):
        response=self.client.get("/v1/directory",params=params)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()["items"]

    def test_public_projection_and_freshness(self):
        rows=self.get(q="монгол")
        self.assertEqual({r["name"] for r in rows},{"Монгол Алфа","Монгол Бета"})
        for row in rows:
            self.assertEqual(set(row),{"organization_id","name","category_slug","description","source_url","verified_at","expires_at"})
            self.assertTrue(row["source_url"].startswith("https://example.test/"))

    def test_category_and_pagination(self):
        self.assertEqual([r["name"] for r in self.get(category="services")],["Монгол Алфа"])
        all_rows=self.get()
        self.assertEqual(self.get(limit=1,offset=0),all_rows[:1])
        self.assertEqual(self.get(limit=1,offset=1),all_rows[1:2])
        self.assertEqual(self.get(limit=1,offset=2),[])

    def test_literal_query(self):
        for query in ("%", "_", "' OR 1=1 --", "Private"):
            self.assertEqual(self.get(q=query),[])

    def test_dedicated_login_cannot_read_private_tables(self):
        with closing(psycopg.connect(os.environ["LAVLAH_PUBLIC_DSN"],autocommit=True)) as c:
            self.assertEqual(c.execute("SELECT current_user").fetchone()[0],"lavlah_integration_login")
            for table in ("users","organizations","sources","memberships","public_listings"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    c.execute("SELECT * FROM lavlah."+table)
            for privilege in ("INSERT", "UPDATE", "DELETE"):
                self.assertFalse(c.execute("SELECT has_table_privilege(current_user, %s, %s)", ("lavlah.public_directory", privilege)).fetchone()[0])
            with self.assertRaises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ObjectNotInPrerequisiteState)):
                c.execute("DELETE FROM lavlah.public_directory")

    def test_revocation_immediately_hides_listing(self):
        with closing(psycopg.connect(os.environ["LAVLAH_TEST_ADMIN_DSN"])) as c:
            try:
                c.execute("UPDATE lavlah.sources SET verified_by=NULL,verified_at=NULL,expires_at=NULL WHERE source_url='https://example.test/1'")
                c.commit()
                self.assertEqual(self.get(q="Алфа"),[])
            finally:
                c.execute("""UPDATE lavlah.sources SET verified_by=submitted_by,
                    verified_at=observed_at+interval '1 day',expires_at=CURRENT_TIMESTAMP+interval '1 day'
                    WHERE source_url='https://example.test/1'""")
                c.commit()
