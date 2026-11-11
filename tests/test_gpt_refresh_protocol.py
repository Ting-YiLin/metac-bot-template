"""Offline validation for the GPT-initiated candidate feed refresh protocol."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from integrations.gpt_chat_queue.refresh_protocol import (
    validate_request,
    request_id_from_push,
)


def valid_request(now):
    request_id = now.strftime("req-%Y%m%dT%H%M%SZ") + "-ab12cdef"
    return request_id, {
        "schema_version": 1,
        "request_id": request_id,
        "source": "chatgpt_scheduled_research",
        "tournament": "bot-testing-area",
        "intent": "READ_ONLY_REFRESH",
        "created_at_utc": now.isoformat().replace("+00:00", "Z"),
    }


class RefreshRequestTests(unittest.TestCase):

    def with_request(self, data, request_id):
        td = tempfile.TemporaryDirectory()
        root = Path(td.name)
        folder = root / "integrations/gpt_chat_queue/refresh_requests"
        folder.mkdir(parents=True)
        path = folder / (request_id + ".json")
        path.write_text(json.dumps(data), encoding="utf-8")
        return td, root, path

    def test_accept_fresh_read_only_test_request(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, data = valid_request(now)
        td, root, path = self.with_request(data, request_id)
        prior = os.getcwd()
        try:
            os.chdir(root)
            self.assertEqual(validate_request(path.relative_to(root), now), request_id)
        finally:
            os.chdir(prior)
            td.cleanup()

    def test_reject_outdated_request(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, data = valid_request(now - timedelta(hours=3))
        td, root, path = self.with_request(data, request_id)
        oldcwd = os.getcwd()
        try:
            os.chdir(root)
            with self.assertRaisesRegex(ValueError, "REQUEST_TIMESTAMP_OUT_OF_RANGE"):
                validate_request(path.relative_to(root), now)
        finally:
            os.chdir(oldcwd)
            td.cleanup()

    def test_reject_formal_competition_and_non_read_only(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, data = valid_request(now)
        td, root, path = self.with_request(data, request_id)
        oldcwd = os.getcwd()
        try:
            os.chdir(root)
            data["tournament"] = "futureeval"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FORBIDDEN_TOURNAMENT"):
                validate_request(path.relative_to(root), now)
            data["tournament"] = "bot-testing-area"
            data["intent"] = "SUBMIT_FORECAST"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FORBIDDEN_REQUEST_INTENT"):
                validate_request(path.relative_to(root), now)
        finally:
            os.chdir(oldcwd)
            td.cleanup()

    def test_reject_id_mismatch(self):
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, data = valid_request(now)
        data["request_id"] = "req-20000101T000000Z-badbad00"
        td, root, path = self.with_request(data, request_id)
        oldcwd = os.getcwd()
        try:
            os.chdir(root)
            with self.assertRaisesRegex(ValueError, "REQUEST_ID_MISMATCH"):
                validate_request(path.relative_to(root), now)
        finally:
            os.chdir(oldcwd)
            td.cleanup()

    def test_push_without_request_is_maintenance(self):
        fake_git = MagicMock(return_value=MagicMock(stdout=".github/workflows/export_gpt_chat_candidates.yaml\n"))
        self.assertIsNone(request_id_from_push("push", run_git=fake_git))

    def test_scheduled_refresh_does_not_read_git(self):
        git = MagicMock(side_effect=AssertionError("No git calls for schedule"))
        self.assertIsNone(request_id_from_push("schedule", run_git=git))
        git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
