import inspect
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import live_free_runner as runner

class Dummy:
    def __init__(self, state, already):
        self.state = state
        self.already_forecasted = already

class RunnerContract(unittest.TestCase):
    def test_retry_limit_is_three(self):
        self.assertEqual(runner.MODEL_ALLOWED_TRIES, 3)

    def test_eligibility_is_only_open_and_unforecasted(self):
        from forecasting_tools.data_models.questions import QuestionState
        self.assertTrue(runner.eligible_question(Dummy(QuestionState.OPEN, False)))
        self.assertFalse(runner.eligible_question(Dummy(QuestionState.OPEN, True)))
        non_open = next(x for x in QuestionState if x != QuestionState.OPEN)
        self.assertFalse(runner.eligible_question(Dummy(non_open, False)))
        src = inspect.getsource(runner.eligible_question)
        self.assertNotIn("BinaryQuestion", src)
        self.assertNotIn("scheduled_close", src)
        self.assertNotIn("page_url", src)

    def test_no_question_type_filter_contract(self):
        src = inspect.getsource(runner.run_batch)
        self.assertIn("if eligible_question(q)", src)
        self.assertNotIn("isinstance(q", src)

    def test_batch_continues_after_question_failure(self):
        src = inspect.getsource(runner.run_batch)
        self.assertIn("for tournament, q in candidates", src)
        self.assertIn("summary[\"processed\"].append(item)", src)

if __name__ == "__main__":
    unittest.main()
