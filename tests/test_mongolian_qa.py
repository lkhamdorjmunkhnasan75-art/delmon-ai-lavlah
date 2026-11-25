import os
import unittest
from unittest.mock import Mock, patch
import psycopg
from fastapi.testclient import TestClient
from lavlah.mongolian_qa import interpret, answer
from lavlah.public_api import app
from tests_pilot_auth import pilot_auth
from lavlah.pilot_fixtures import apply, RECORDS

class MongolianQATests(unittest.TestCase):
    def test_cyrillic(self):
        self.assertEqual(interpret("АЛТАН НАР засвар хаана байна?"),"алтан нар засвар")

    def test_latin_aliases(self):
        for q in ("Altan nar zasvar baina uu?", "Алтан нар zasvar хаана вэ?"):
            self.assertEqual(interpret(q),"алтан нар засвар")
        self.assertEqual(interpret("Huh tenger hudaldaa haana ve?"),"хөх тэнгэр худалдаа")

    def test_clarification_without_lookup(self):
        search=Mock()
        for q in ("Хаана байна?", "Алтан нар утасны дугаар хэд вэ?", "Altan nar une?", "unknown", "123", "你好", " "):
            self.assertEqual(answer(q,search)["status"],"clarify")
        search.assert_not_called()

    def test_no_result(self):
        search=Mock(return_value=[])
        result=answer("Үл мэдэгдэх байгууллага",search)
        self.assertEqual(result["status"],"no_result")
        self.assertEqual(result["items"],[])
        search.assert_called_once_with("үл мэдэгдэх байгууллага","",5,0)

    def test_projection_no_extra_private_fields(self):
        row=dict(organization_id="fixture",name="Алтан нар",category_slug="services",
                 description="Зохиомол",source_url="https://pilot.example.test/0",
                 verified_at="fixture",expires_at="fixture",private="hidden")
        result=answer("Алтан нар",Mock(return_value=[row]))
        self.assertEqual(result["status"],"matched")
        self.assertEqual(result["items"],[{k:v for k,v in row.items() if k!="private"}])

    def test_invalid_input(self):
        for q in ("", "а"*241, "а\x00", None):
            with self.assertRaises(ValueError): interpret(q)

    def test_api_disabled_default(self):
        with patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"0"}), patch("lavlah.public_api.search_directory") as search:
            with TestClient(app) as client, pilot_auth(client):
                self.assertEqual(client.post("/v1/pilot/ask",json={"question":"Алтан нар"}).status_code,404)
            search.assert_not_called()

    def test_api_validation_and_error(self):
        with patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1"}), TestClient(app) as client, pilot_auth(client):
            for body in ({"question":""},{"question":"а"*241},{"question":"а\x00"},{"question":"Алтан нар","sql":"ignored"}):
                self.assertEqual(client.post("/v1/pilot/ask",json=body).status_code,422)
            with patch("lavlah.public_api.search_directory",side_effect=psycopg.OperationalError("private details")):
                res=client.post("/v1/pilot/ask",json={"question":"Алтан нар"})
                self.assertEqual(res.status_code,503)
                self.assertNotIn("private details",res.text)

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class MongolianQAIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(self.dsn)
        self.flag=patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1"})
        self.flag.start()
        self.addCleanup(self.flag.stop)
        self.client=TestClient(app)
        auth=pilot_auth(self.client)
        auth.__enter__()
        self.addCleanup(auth.__exit__,None,None,None)
        self.addCleanup(self.client.close)
        self.addCleanup(apply,self.dsn,reset=True)

    def ask(self,q):
        res=self.client.post("/v1/pilot/ask",json={"question":q})
        self.assertEqual(res.status_code,200,res.text)
        self.assertEqual(res.headers["cache-control"],"no-store")
        return res.json()

    def test_verified_cyrillic_and_latin_answers(self):
        for q in ("Алтан нар засвар хаана байна?","Altan nar zasvar baina uu?"):
            res=self.ask(q)
            self.assertEqual(res["status"],"matched")
            self.assertEqual([row["name"] for row in res["items"]],[RECORDS[0][0]])
            self.assertEqual(res["items"][0]["source_url"],"https://pilot.example.test/0")
            self.assertTrue(res["items"][0]["expires_at"])

    def test_expired_unapproved_and_unknown_abstain(self):
        for q in ("Цагаан уул хүргэлт","Nogoon tal surgalt","Байхгүй байгууллага"):
            res=self.ask(q)
            self.assertEqual(res["status"],"no_result")
            self.assertEqual(res["items"],[])
        self.assertEqual(self.ask("Алтан нар үнэ хэд вэ?")["status"],"clarify")
