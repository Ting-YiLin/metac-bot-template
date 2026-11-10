"""Persistent test-area per-question failure counts.

State lives on an isolated Git branch; no model calls and no forecast validation.
The isolated branch prevents state updates from retriggering the production workflow.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone

import requests

LEDGER_BRANCH = "tingyi001-test-state"
LEDGER_PATH = "state/testing_area_failures.json"
MAX_FAILED_ATTEMPTS = 2


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def question_key(q):
    """Use Metaculus subquestion ID, falling back to post ID when absent."""
    question_id = getattr(q, "id_of_question", None)
    if isinstance(question_id, int):
        return str(question_id)
    post_id = getattr(q, "id_of_post", None)
    return "post:" + str(post_id)


class TestingFailureLedger:
    def __init__(self, token=None, repo=None):
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN", "")
        self.repo = repo or os.getenv("GITHUB_REPOSITORY", "Ting-YiLin/metac-bot-template")
        self.url = (
            f"https://api.github.com/repos/{self.repo}/contents/{LEDGER_PATH}"
        )
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            self.headers["Authorization"] = "Bearer " + self.token
        self.data = {"schema_version": 1, "questions": {}}
        self.sha = None
        self.available = False
        self.error = None

    def load(self):
        try:
            response = requests.get(
                self.url,
                headers=self.headers,
                params={"ref": LEDGER_BRANCH},
                timeout=20,
            )
            response.raise_for_status()
            body = response.json()
            raw = base64.b64decode(body["content"]).decode("utf-8")
            loaded = json.loads(raw)
            if not isinstance(loaded.get("questions"), dict):
                raise ValueError("INVALID_FAILURE_LEDGER")
            self.data = loaded
            self.sha = body["sha"]
            self.available = True
            self.error = None
            return True
        except Exception as exc:
            self.available = False
            self.error = type(exc).__name__
            return False

    def failures_for(self, q):
        record = self.data.get("questions", {}).get(question_key(q), {})
        return max(0, int(record.get("failed_attempts", 0)))

    def should_skip(self, q):
        return self.failures_for(q) >= MAX_FAILED_ATTEMPTS

    def record_failure(self, q, *, run_id="", error_type=""):
        """Record one failed full-question attempt. 409 conflicts are retried."""
        if not self.available or not self.token:
            self.error = "LEDGER_UNAVAILABLE_OR_TOKEN_MISSING"
            return None
        key = question_key(q)
        for _ in range(3):
            # Reload remote state to merge with other runs and avoid overwriting.
            if not self.load():
                return None
            current = self.failures_for(q)
            if current >= MAX_FAILED_ATTEMPTS:
                return current
            updated = dict(self.data)
            questions = dict(self.data["questions"])
            record = dict(questions.get(key, {}))
            record.update({
                "post_id": getattr(q, "id_of_post", None),
                "failed_attempts": current + 1,
                "last_failed_at_utc": utc_timestamp(),
                "last_run_id": str(run_id),
                "last_error_type": str(error_type)[:120],
            })
            questions[key] = record
            updated["questions"] = questions
            payload = {
                "branch": LEDGER_BRANCH,
                "sha": self.sha,
                "message": f"Record failed testing-area forecast for question {key}",
                "content": base64.b64encode(
                    (json.dumps(updated, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                ).decode("ascii"),
            }
            try:
                response = requests.put(
                    self.url,
                    headers=self.headers,
                    json=payload,
                    timeout=20,
                )
                if response.status_code in (409, 422):
                    continue
                response.raise_for_status()
                self.data = updated
                self.sha = response.json().get("content", {}).get("sha", self.sha)
                self.available = True
                self.error = None
                return current + 1
            except Exception as exc:
                self.error = type(exc).__name__
                self.available = False
                return None
        self.error = "LEDGER_WRITE_CONFLICT"
        return None
