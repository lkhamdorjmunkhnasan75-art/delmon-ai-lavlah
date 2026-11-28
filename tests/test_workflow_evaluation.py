import unittest
from lavlah.workflow_evaluation import fixtures, evaluate

class EvaluationTests(unittest.TestCase):
    def test_fixture_count(self):
        cases = fixtures()
        self.assertEqual(len(cases), 100)
        self.assertEqual(len({c.question for c in cases}), 100)
        self.assertEqual(sum(c.expected == "answer" for c in cases), 80)
    def test_reference(self):
        cases = fixtures()
        lookup = {c.question: (c.expected, c.answer) for c in cases}
        self.assertEqual(evaluate(cases, lookup.__getitem__)["accuracy"], 1.0)
    def test_refusal(self):
        result = evaluate(fixtures(), lambda q: ("unavailable", ""))
        self.assertEqual(result["correct"], 20)
        self.assertEqual(result["unsupported"], 0)
    def test_wrong_answer(self):
        result = evaluate(fixtures(), lambda q: ("answer", "wrong"))
        self.assertEqual(result["unsupported"], 100)
        self.assertEqual(result["correct"], 0)
    def test_error(self):
        def fail(q):
            raise RuntimeError()
        self.assertEqual(evaluate(fixtures(), fail)["errors"], 100)
    def test_empty(self):
        self.assertIsNone(evaluate((), lambda q: ("unavailable", ""))["accuracy"])
    def test_invalid(self):
        self.assertEqual(evaluate(fixtures(), lambda q: ("invalid", ""))["errors"], 100)
