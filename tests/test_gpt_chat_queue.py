"""Offline tests for GPT chat forecast queue. No API calls or submissions."""
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from integrations.gpt_chat_queue.queue_runner import validate_payload, process_one, paths_from_event


MARKETS = ("polymarket", "kalshi", "manifold", "metaculus", "hypermind", "betfair")


def fixture(now=None, *, mode="TEST_SUBMIT"):
    now = now or datetime.now(timezone.utc)
    rounds = {
        "broad": {
            "status": "DONE",
            "queries": ["official announcement"],
            "sources": [{"url": "https://example.org/official"}],
        },
        "deep": {"status": "DONE", "queries": ["counterexample"], "sources": []},
        "local_language": {
            "status": "DONE", "language": "fr",
            "queries": ["recherche locale"], "sources": [],
        },
    }
    return {
        "schema_version": 1,
        "source": "chatgpt_scheduled_research",
        "tournament": "bot-testing-area",
        "question_type": "BinaryQuestion",
        "post_id": 1234, "question_id": 5678,
        "p_yes": 0.62,
        "reasoning": "Public information supports YES, with a nontrivial counterexample.",
        "forecast_created_at_utc": (now - timedelta(minutes=2)).isoformat(),
        "evidence_cutoff_utc": (now - timedelta(minutes=3)).isoformat(),
        "research_rounds": rounds,
        "market_checks": {
            x: {"status": "NOT_FOUND", "url": None, "p_yes": None} for x in MARKETS
        },
        "mode": mode,
    }


class QueueOfflineTests(unittest.TestCase):
    PATH = "integrations/gpt_chat_queue/pending/q-1234-5678-smoke001.json"

    def test_validate_complete_payload(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(validate_payload(fixture(now), self.PATH, now)["p_yes"], 0.62)

    def test_no_formal_tournament(self):
        p = fixture()
        p["tournament"] = "futureeval"
        with self.assertRaisesRegex(ValueError, "FORBIDDEN_TOURNAMENT"):
            validate_payload(p, self.PATH)

    def test_bad_probability_and_wrong_id(self):
        p = fixture()
        p["p_yes"] = 12
        with self.assertRaisesRegex(ValueError, "INVALID_P_YES"):
            validate_payload(p, self.PATH)
        p = fixture()
        p["question_id"] = 999
        with self.assertRaisesRegex(ValueError, "FILENAME_QUESTION_ID_MISMATCH"):
            validate_payload(p, self.PATH)

    def test_stale_question_blocked(self):
        now = datetime.now(timezone.utc)
        p = fixture(now)
        p["forecast_created_at_utc"] = (now - timedelta(hours=3)).isoformat()
        p["evidence_cutoff_utc"] = (now - timedelta(hours=4)).isoformat()
        with self.assertRaisesRegex(ValueError, "STALE_FORECAST"):
            validate_payload(p, self.PATH, now)

    def test_market_requires_exact_probability_and_url(self):
        p = fixture()
        p["market_checks"]["kalshi"]["status"] = "VERIFIED_EXACT"
        with self.assertRaisesRegex(ValueError, "INVALID_EXACT_MARKET_P"):
            validate_payload(p, self.PATH)
        p["market_checks"]["kalshi"]["p_yes"] = 0.54
        with self.assertRaisesRegex(ValueError, "MISSING_MARKET_URL"):
            validate_payload(p, self.PATH)

    def test_event_selects_only_changed_queue(self):
        event = {"commits": [{"added": [self.PATH, "main.py"], "modified": ["README.md"]}]}
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "event.json"
            fp.write_text(json.dumps(event), encoding="utf-8")
            self.assertEqual(paths_from_event(str(fp)), [self.PATH])

    def test_live_disabled_never_submits(self):
        p = fixture()
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "q-1234-5678-smoke001.json"
            fp.write_text(json.dumps(p), encoding="utf-8")
            client = MagicMock()
            q = type("BinaryQuestion", (), {})()
            q.id_of_post, q.id_of_question, q.already_forecasted = 1234, 5678, False
            from forecasting_tools.data_models.questions import QuestionState
            q.state = QuestionState.OPEN
            client.get_all_open_questions_from_tournament.return_value = [q]
            ledger = MagicMock()
            ledger.available = True
            ledger.failures_for.return_value = 0
            result = process_one(fp, client, ledger, live_enabled=False)
            self.assertEqual(result["status"], "PASS_DRY_RUN")
            client.post_binary_question_prediction.assert_not_called()

    def test_double_failed_skip(self):
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "q-1234-5678-smoke001.json"
            fp.write_text(json.dumps(fixture()), encoding="utf-8")
            ledger = MagicMock()
            ledger.available = True
            ledger.failures_for.return_value = 2
            client = MagicMock()
            result = process_one(fp, client, ledger, live_enabled=True)
            self.assertEqual(result["status"], "SKIP_TWO_PREVIOUS_FAILURES")
            client.post_binary_question_prediction.assert_not_called()


if __name__ == "__main__":
    unittest.main()
