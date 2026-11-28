import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from lavlah.workflow_learning import SyntheticPilot
from lavlah.workflow_review import Review, eligible_for_evaluation

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        example = SyntheticPilot().add("demo", "hours", "Хэзээ?", "09:00", synthetic=True)
        self.review = Review(example, "reviewer-demo", "fixture-source", self.now+timedelta(days=1), True)
    def check(self, **changes):
        return eligible_for_evaluation(replace(self.review, **changes), "demo", self.now)
    def test_approved(self):
        self.assertTrue(self.check())
    def test_pending(self):
        self.assertFalse(self.check(approved=False))
    def test_revoked(self):
        self.assertFalse(self.check(revoked=True))
    def test_expired(self):
        self.assertFalse(self.check(expires_at=self.now))
    def test_missing_source(self):
        self.assertFalse(self.check(source_reference=" "))
    def test_missing_reviewer(self):
        self.assertFalse(self.check(reviewer=""))
    def test_naive_time(self):
        self.assertFalse(self.check(expires_at=self.now.replace(tzinfo=None)))
    def test_other_org(self):
        self.assertFalse(eligible_for_evaluation(self.review, "other", self.now))
