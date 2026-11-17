"""No-network tests for the authenticated read-only candidate probe."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minibench_readonly_probe import collect, run

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 17, 7, 0, tzinfo=UTC)

class Open:
    name = "OPEN"
class Closed:
    name = "CLOSED"
class BinaryQuestion:
    def __init__(self, **kw):
        self.__dict__.update(kw)
class NumericQuestion(BinaryQuestion):
    pass

def q(**overrides):
    info = dict(id_of_post=1, id_of_question=2, state=Open(),
                already_forecasted=False,
                scheduled_close_time=NOW + dt.timedelta(hours=2),
                question_text="Sample question?",
                resolution_criteria="Sample resolution criteria",
                fine_print="", background_info="",
                page_url="https://www.metaculus.com/questions/1/")
    info.update(overrides)
    return BinaryQuestion(**info)

class Client:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
    def get_all_open_questions_from_tournament(self, tournament):
        self.calls.append(tournament)
        return self.rows

class ProbeTests(unittest.TestCase):
    def test_one_open_unforecasted(self):
        client = Client([q()])
        data = collect(client, NOW)
        self.assertEqual(client.calls, ["minibench"])
        self.assertEqual(data["eligible_after_status_and_deadline_check"], 1)
        self.assertFalse(data["complete_60_question_census"])
        self.assertTrue(data["items"][0]["supported_by_current_validator"])
    def test_duplicate_not_repeated(self):
        data = collect(Client([q(),q()]), NOW)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["counts"]["duplicate_identifiers"], 1)
    def test_previously_forecasted_excluded(self):
        data = collect(Client([q(already_forecasted=True)]), NOW)
        self.assertEqual(len(data["items"]), 0)
        self.assertEqual(data["counts"]["already_forecasted"],1)
    def test_unknown_previously_forecasted_failclosed(self):
        data = collect(Client([q(already_forecasted=None)]), NOW)
        self.assertEqual(len(data["items"]), 0)
    def test_closed_excluded(self):
        data = collect(Client([q(state=Closed())]), NOW)
        self.assertEqual(len(data["items"]), 0)
    def test_elapsed_excluded(self):
        data = collect(Client([q(scheduled_close_time=NOW-dt.timedelta(seconds=1))]), NOW)
        self.assertEqual(len(data["items"]), 0)
    def test_nonbinary_preserved_not_supported(self):
        nonbinary = NumericQuestion(**q().__dict__)
        data = collect(Client([nonbinary]), NOW)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["supported_binary"], 0)
    def test_no_token_does_not_call_client(self):
        def nope():
            raise AssertionError("unauthenticated call attempted")
        receipt, feed = run(client_factory=nope, token="", now=NOW)
        self.assertEqual(receipt["status"], "BLOCKED_MISSING_PLATFORM_TOKEN")
        self.assertIsNone(feed)
    def test_errors_are_redacted(self):
        def nope():
            raise ValueError("SECRET_NEVER_SHOW")
        receipt, feed = run(client_factory=nope, token="testing-token", now=NOW)
        self.assertEqual(receipt["status"], "FETCH_FAILED")
        self.assertEqual(receipt["error_type"], "ValueError")
        self.assertNotIn("SECRET_NEVER_SHOW", repr(receipt))
        self.assertIsNone(feed)
    def test_bad_identifiers_excluded(self):
        data = collect(Client([q(id_of_post=None)]), NOW)
        self.assertEqual(len(data["items"]), 0)
    def test_bad_timestamp_excluded(self):
        data = collect(Client([q(scheduled_close_time="not a timestamp")]), NOW)
        self.assertEqual(len(data["items"]), 0)

if __name__ == "__main__":
    unittest.main()
