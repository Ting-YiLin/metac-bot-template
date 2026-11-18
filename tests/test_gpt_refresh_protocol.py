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


    def test_immutable_result_create_without_old_sha(self):
        import base64
        from integrations.gpt_chat_queue.export_candidates import (
            publish_to_github, RESULT_DIR
        )
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, _ = valid_request(now)
        path = f"{RESULT_DIR}/{request_id}.json"
        api = MagicMock()
        api.get.return_value.status_code = 404
        api.put.return_value.status_code = 201
        record = {"refresh_request_id": request_id, "refresh_status": "COMPLETE",
                  "eligible_unforecasted": 0, "items": []}
        self.assertTrue(publish_to_github(
            record, "fake-test-token", path=path, create_only=True, requests_module=api
        ))
        written = api.put.call_args.kwargs["json"]
        self.assertNotIn("sha", written)
        self.assertEqual(written["branch"], "tingyi001-test-state")
        self.assertEqual(json.loads(base64.b64decode(written["content"]))["refresh_request_id"], request_id)

    def test_immutable_result_cannot_overwrite(self):
        from integrations.gpt_chat_queue.export_candidates import publish_to_github, RESULT_DIR
        now = datetime.now(timezone.utc).replace(microsecond=0)
        request_id, _ = valid_request(now)
        api = MagicMock()
        api.get.return_value.status_code = 200
        with self.assertRaisesRegex(RuntimeError, "REQUEST_RESULT_ALREADY_EXISTS"):
            publish_to_github(
                {}, "fake-test-token", path=f"{RESULT_DIR}/{request_id}.json",
                create_only=True, requests_module=api,
            )
        api.put.assert_not_called()

    def test_immutable_result_rejects_other_paths(self):
        from integrations.gpt_chat_queue.export_candidates import publish_to_github
        api = MagicMock()
        with self.assertRaisesRegex(ValueError, "FORBIDDEN_FEED_OUTPUT_PATH"):
            publish_to_github({}, "fake-test-token", path="state/other.json",
                              create_only=True, requests_module=api)
        api.get.assert_not_called()

    def test_mutable_legacy_feed_remains_supported(self):
        from integrations.gpt_chat_queue.export_candidates import publish_to_github
        api = MagicMock()
        api.get.return_value.status_code = 200
        api.get.return_value.json.return_value = {"sha": "old-sha"}
        api.put.return_value.status_code = 200
        self.assertTrue(publish_to_github({"eligible_unforecasted": 0},
                                          "fake-test-token", requests_module=api))
        self.assertEqual(api.put.call_args.kwargs["json"]["sha"], "old-sha")


if __name__ == "__main__":
    unittest.main()
