"""Offline tests: no model calls, no platform submissions."""
import base64
import inspect
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import live_free_runner
from tools.testing_failure_ledger import (
    TestingFailureLedger,
    question_key,
    MAX_FAILED_ATTEMPTS,
)


def question(i=46451, post=46224):
    return SimpleNamespace(id_of_question=i, id_of_post=post)


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP_" + str(self.status_code))

    def json(self):
        return self._body


class TestTestingFailureLedger(unittest.TestCase):
    def test_question_key_uses_subquestion_id(self):
        self.assertEqual(question_key(question()), "46451")

    def test_skip_after_two_full_failures(self):
        ledger = TestingFailureLedger(token="fake")
        ledger.data = {"schema_version": 1, "questions": {
            "46451": {"failed_attempts": 1}
        }}
        self.assertEqual(MAX_FAILED_ATTEMPTS, 2)
        self.assertFalse(ledger.should_skip(question()))
        ledger.data["questions"]["46451"]["failed_attempts"] = 2
        self.assertTrue(ledger.should_skip(question()))
        self.assertFalse(ledger.should_skip(question(99999)))

    def test_record_failure_persists_to_separate_branch(self):
        original = {
            "schema_version": 1,
            "questions": {"46451": {"post_id": 46224, "failed_attempts": 1}},
        }
        response_body = {
            "sha": "old-sha",
            "content": base64.b64encode(json.dumps(original).encode()).decode(),
        }
        put_calls = []

        def fake_put(url, headers, json, timeout):
            put_calls.append(json)
            return FakeResponse(body={"content": {"sha": "new-sha"}})

        ledger = TestingFailureLedger(token="fake")
        ledger.available = True
        with patch("tools.testing_failure_ledger.requests.get", return_value=FakeResponse(body=response_body)), patch(
            "tools.testing_failure_ledger.requests.put", side_effect=fake_put
        ):
            count = ledger.record_failure(question(), run_id="run-test", error_type="ValidationError")
        self.assertEqual(count, 2)
        self.assertEqual(len(put_calls), 1)
        self.assertEqual(put_calls[0]["branch"], "tingyi001-test-state")
        saved = json.loads(base64.b64decode(put_calls[0]["content"]))
        self.assertEqual(saved["questions"]["46451"]["failed_attempts"], 2)
        self.assertTrue(ledger.should_skip(question()))

    def test_runner_has_no_count_limit(self):
        src = inspect.getsource(live_free_runner.run_batch)
        self.assertNotIn("MAX_TEST_QUESTIONS", src)
        self.assertNotIn("TEST_BATCH_QUESTION_LIMIT", src)
        self.assertIn("ledger.should_skip(q)", src)
        self.assertIn("RUN_TIME_BUDGET", src)


if __name__ == "__main__":
    unittest.main()
