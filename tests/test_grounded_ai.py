import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from uuid import UUID
from fastapi.testclient import TestClient
from lavlah.grounded_ai import respond, Selection
from lavlah.public_api import app
from tests_pilot_auth import pilot_auth
from lavlah.pilot_fixtures import apply, RECORDS

NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def row(n,name="Алтан нар",**kwargs):
    return dict(organization_id=UUID(int=n),name=name,category_slug="services",
                description="Зохиомол",source_url="https://pilot.example.test/"+str(n),
                verified_at=NOW-timedelta(days=1),expires_at=NOW+timedelta(days=1)) | kwargs

class GroundedTests(unittest.TestCase):
    def test_rank_and_deduplicate(self):
        result=respond("Алтан нар",Mock(return_value=[row(2,"ТУРШИЛТ Алтан нар"),row(1),row(1)]),now=NOW)
        self.assertEqual([x["organization_id"] for x in result["items"]],[str(UUID(int=1)),str(UUID(int=2))])
        self.assertEqual(result["usage"]["outcome"],"selected")
    def test_filter_invalid_evidence(self):
        rows=[row(1,expires_at=NOW),row(2,verified_at=NOW+timedelta(days=1)),
              row(3,source_url="javascript:alert(1)"),row(4,"Хамааралгүй"),
              row(5,source_url="https://user:secret@pilot.example.test/")]
        adapter=Mock()
        self.assertEqual(respond("Алтан нар",Mock(return_value=rows),adapter,now=NOW)["status"],"no_result")
        adapter.select.assert_not_called()
    def test_mock_cost(self):
        result=respond("Алтан нар",Mock(return_value=[row(1)]),now=NOW)
        u=result["usage"]
        self.assertEqual(u["estimated_micro_mnt"],2*u["input_units"]+5*u["output_units"])
        self.assertEqual(u["actual_charge_mnt"],0)
    def test_invalid_selection_fallback(self):
        for ids in ((str(UUID(int=99)),),(str(UUID(int=1)),)*2,()):
            adapter=Mock()
            adapter.select.return_value=Selection(ids,10,10)
            result=respond("Алтан нар",Mock(return_value=[row(1)]),adapter,now=NOW)
            self.assertEqual(result["usage"]["outcome"],"fallback")
            self.assertIsNone(result["usage"]["estimated_micro_mnt"])
            self.assertEqual(result["items"][0]["organization_id"],str(UUID(int=1)))
    def test_exception_and_invalid_usage(self):
        for adapter in (Mock(select=Mock(side_effect=RuntimeError("SECRET"))),
                        Mock(select=Mock(return_value=Selection((str(UUID(int=1)),),-1,10)))):
            result=respond("Алтан нар",Mock(return_value=[row(1)]),adapter,now=NOW)
            self.assertEqual(result["usage"]["outcome"],"fallback")
            self.assertNotIn("SECRET",str(result))
    def test_clarify_and_no_result_zero_attempts(self):
        search=Mock(return_value=[])
        adapter=Mock()
        self.assertEqual(respond("Үнэ хэд вэ?",search,adapter)["status"],"clarify")
        search.assert_not_called()
        result=respond("Altan nar",search,adapter)
        self.assertEqual(result["status"],"no_result")
        self.assertEqual(result["usage"]["attempts"],0)
        adapter.select.assert_not_called()
    def test_adapter_cannot_inject_fields(self):
        result=respond("Алтан нар",Mock(return_value=[row(1,secret="hidden")]),now=NOW)
        self.assertNotIn("secret",result["items"][0])
    def test_api_disabled_and_validation(self):
        with TestClient(app) as client, pilot_auth(client):
            with patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1","LAVLAH_ENABLE_MOCK_AI":"0"}):
                self.assertEqual(client.post("/v1/pilot/grounded-ask",json={"question":"Алтан нар"}).status_code,404)
            with patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1","LAVLAH_ENABLE_MOCK_AI":"1"}):
                self.assertEqual(client.post("/v1/pilot/grounded-ask",json={"question":""}).status_code,422)

@unittest.skipUnless(os.getenv("LAVLAH_PILOT_INTEGRATION")=="1","Disposable pilot DB required")
class GroundedIntegration(unittest.TestCase):
    def setUp(self):
        dsn=os.environ["LAVLAH_PILOT_DSN"]
        apply(dsn)
        self.addCleanup(apply,dsn,reset=True)
        flag=patch.dict(os.environ,{"LAVLAH_ENABLE_PILOT_QA":"1","LAVLAH_ENABLE_MOCK_AI":"1"})
        flag.start()
        self.addCleanup(flag.stop)
        self.client=TestClient(app)
        auth=pilot_auth(self.client)
        auth.__enter__()
        self.addCleanup(auth.__exit__,None,None,None)
        self.addCleanup(self.client.close)
    def test_grounded_api_and_usage_event(self):
        with self.assertLogs("lavlah.mock_usage",level="INFO") as logs:
            res=self.client.post("/v1/pilot/grounded-ask",json={"question":"Altan nar zasvar baina uu?"})
        self.assertEqual(res.status_code,200,res.text)
        self.assertEqual(res.headers["cache-control"],"no-store")
        data=res.json()
        self.assertEqual(data["items"][0]["name"],RECORDS[0][0])
        self.assertEqual(data["items"][0]["source_url"],"https://pilot.example.test/0")
        self.assertEqual(data["usage"]["actual_charge_mnt"],0)
        self.assertNotIn("Altan nar"," ".join(logs.output))
    def test_hidden_and_expired_not_selected(self):
        for q in ("Цагаан уул хүргэлт","Ногоон тал сургалт"):
            data=self.client.post("/v1/pilot/grounded-ask",json={"question":q}).json()
            self.assertEqual(data["status"],"no_result")
            self.assertEqual(data["items"],[])
            self.assertEqual(data["usage"]["attempts"],0)
