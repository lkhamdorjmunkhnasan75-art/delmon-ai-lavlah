import unittest
from lavlah.workflow_learning import SyntheticPilot

class WorkflowLearningTests(unittest.TestCase):
    def setUp(self):
        self.pilot = SyntheticPilot()
    def add(self, org="demo", category="hours", question="Хэзээ нээх вэ?", answer="09:00", synthetic=True):
        return self.pilot.add(org, category, question, answer, synthetic=synthetic)
    def test_pending(self):
        self.assertEqual(self.add().state, "pending")
    def test_requires_synthetic(self):
        with self.assertRaises(ValueError):
            self.add(synthetic=False)
    def test_duplicate(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add(question="  ХЭЗЭЭ  НЭЭХ ВЭ? ")
    def test_scope(self):
        self.assertEqual(self.add().fingerprint, self.add(org="demo2").fingerprint)
    def test_category(self):
        with self.assertRaises(ValueError):
            self.add(category="unknown")
    def test_empty(self):
        with self.assertRaises(ValueError):
            self.add(answer=" ")
    def test_limit(self):
        with self.assertRaises(ValueError):
            self.add(question="а"*1001)
    def test_normalization(self):
        self.assertEqual(self.add(question="  А   Б ").question, "А Б")
