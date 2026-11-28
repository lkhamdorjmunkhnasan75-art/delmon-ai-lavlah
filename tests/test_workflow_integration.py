"""Synthetic end-to-end test; never connects to the public directory."""
import unittest
from datetime import datetime, timedelta, timezone
from lavlah.workflow_learning import SyntheticPilot
from lavlah.workflow_review import Review, eligible_for_evaluation
from lavlah.conversation import PublicRecord, respond
from lavlah.workflow_evaluation import fixtures, evaluate

class WorkflowIntegrationTests(unittest.TestCase):
    def test_pipeline(self):
        now = datetime.now(timezone.utc)
        expiry = now + timedelta(days=1)
        pilot = SyntheticPilot()
        records = {}
        cases = fixtures()
        for case in cases:
            example = pilot.add("demo", "other", case.question,
                                case.answer or "synthetic withheld", synthetic=True)
            review = Review(example, "fixture-reviewer", "fixture-source",
                            expiry, case.expected == "answer")
            if eligible_for_evaluation(review, "demo", now):
                records[case.question] = PublicRecord(
                    "Synthetic fixture", example.answer, "https://example.test",
                    now, expiry, True)
        class Adapter:
            def search(self, query, limit):
                return (records[query],) if query in records else ()
        def predict(question):
            reply = respond(question, Adapter())
            return reply.status, reply.records[0].description if reply.records else ""
        result = evaluate(cases, predict)
        self.assertEqual(len(records), 80)
        self.assertEqual(result["correct"], 100)
        self.assertEqual(result["unsupported"], 0)
        self.assertEqual(result["errors"], 0)

    def test_revoked_and_other_scope(self):
        now = datetime.now(timezone.utc)
        example = SyntheticPilot().add("demo", "hours", "Хэзээ?", "09:00", synthetic=True)
        review = Review(example, "fixture-reviewer", "fixture-source",
                        now + timedelta(days=1), True, True)
        self.assertFalse(eligible_for_evaluation(review, "demo", now))
        self.assertFalse(eligible_for_evaluation(review, "other", now))
