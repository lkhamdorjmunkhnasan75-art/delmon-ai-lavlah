import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from lavlah.conversation import PublicRecord, respond

class Adapter:
    def __init__(self, records=(), fail=False):
        self.records, self.fail, self.calls = records, fail, []
    def search(self, query, limit):
        self.calls.append((query, limit))
        if self.fail:
            raise RuntimeError("private error")
        return self.records

class ConversationTests(unittest.TestCase):
    def setUp(self):
        now = datetime.now(timezone.utc)
        self.record = PublicRecord("Төв", "Нээлттэй мэдээлэл", "https://example.test", now-timedelta(days=1), now+timedelta(days=1), True)
    def test_answer(self):
        a = Adapter((self.record,))
        self.assertEqual(respond("  Төв   хаана ", a).records, (self.record,))
        self.assertEqual(a.calls, [("Төв хаана", 5)])
    def test_empty(self):
        a = Adapter()
        self.assertEqual(respond("  ", a).status, "clarification")
        self.assertEqual(a.calls, [])
    def test_oversized(self):
        a = Adapter()
        self.assertEqual(respond("а"*1001, a).status, "clarification")
        self.assertEqual(a.calls, [])
    def test_no_results(self):
        self.assertEqual(respond("Төв", Adapter()).status, "unavailable")
    def test_unpublished(self):
        self.assertEqual(respond("Төв", Adapter((replace(self.record, published=False),))).records, ())
    def test_expired(self):
        self.assertEqual(respond("Төв", Adapter((replace(self.record, expires_at=self.record.verified_at),))).records, ())
    def test_future(self):
        self.assertEqual(respond("Төв", Adapter((replace(self.record, verified_at=self.record.expires_at),))).records, ())
    def test_failure(self):
        reply = respond("Төв", Adapter(fail=True))
        self.assertEqual(reply.status, "unavailable")
        self.assertNotIn("private error", reply.message)
    def test_invalid_url(self):
        self.assertEqual(respond("Төв", Adapter((replace(self.record, source_url="file:///secret"),))).status, "unavailable")
    def test_limit(self):
        self.assertEqual(respond("Төв", Adapter((self.record,)*6)).status, "unavailable")
