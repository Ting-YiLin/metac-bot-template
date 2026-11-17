"""Publish an authenticated READ-ONLY MiniBench snapshot to isolated state branch.

Never sends a forecast; never writes main or the existing testing-area feed.
Only a time-limited, sanitized public candidate snapshot is published.
"""
from __future__ import annotations
import base64
import datetime as dt
import json
import os
from pathlib import Path


REPO = "Ting-YiLin/metac-bot-template"
BRANCH = "tingyi001-test-state"
PATH = "state/minibench_work_candidate_feed.json"
SRC = Path("minibench_readonly_candidate_feed.json")
OUT = Path("minibench_feed_publish_receipt.json")
from refresh_protocol import request_id_from_push


def validate_snapshot(doc, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if doc.get("schema_version") != 1:
        raise ValueError("BAD_SCHEMA")
    if doc.get("tournament_requested") != "minibench":
        raise ValueError("FORBIDDEN_TOURNAMENT")
    if doc.get("scope") != "AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION":
        raise ValueError("BAD_SCOPE")
    checked = dt.datetime.fromisoformat(doc["checked_at_utc"].replace("Z", "+00:00"))
    if checked.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    age = now - checked.astimezone(dt.timezone.utc)
    if not dt.timedelta(seconds=-30) <= age <= dt.timedelta(minutes=15):
        raise ValueError("STALE_FEED")
    items = doc.get("items")
    if not isinstance(items, list) or len(items) > 150:
        raise ValueError("ITEMS_INVALID")
    if doc.get("truncated") is True:
        raise ValueError("TRUNCATED_FEED")
    if doc.get("eligible_after_status_and_deadline_check") != len(items):
        raise ValueError("COUNT_MISMATCH")
    for row in items:
        if type(row.get("question_id")) is not int or type(row.get("post_id")) is not int:
            raise ValueError("BAD_IDS")
        qtype=row.get("question_type")
        if not isinstance(qtype,str) or not qtype.strip():
            raise ValueError("INVALID_TYPE_LABEL")
        known={"BinaryQuestion","NumericQuestion","DateQuestion","DiscreteQuestion","MultipleChoiceQuestion"}
        if qtype not in known and row.get("supported_by_current_validator") is True:
            raise ValueError("UNKNOWN_TYPE_MISLABELED_SUPPORTED")
    return checked


def publish(doc, token, run_id, session=None, now=None, request_id=None):
    if session is None:
        import requests
        session = requests
    now = now or dt.datetime.now(dt.timezone.utc)
    if not token:
        raise RuntimeError("NO_GITHUB_TOKEN")
    validate_snapshot(doc, now)
    snapshot = dict(doc)
    snapshot["refresh_run_id"] = str(run_id or "")
    snapshot["refresh_request_id"] = request_id
    snapshot["refresh_trigger"] = "WORK_REQUEST" if request_id else "CODE_OR_MANUAL"
    snapshot["published_at_utc"] = now.isoformat()
    snapshot["freshness_expires_utc"] = (now + dt.timedelta(minutes=20)).isoformat()
    snapshot["is_live_tournament_submission_authorized"] = False
    url = "https://api.github.com/repos/" + REPO + "/contents/" + PATH
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "User-Agent": "BTF3MiniBenchReadOnly"}
    prior = session.get(url, params={"ref": BRANCH}, headers=headers, timeout=20)
    if prior.status_code not in (200,404):
        raise RuntimeError("STATE_READ_FAILED_" + str(prior.status_code))
    payload = {
        "branch": BRANCH,
        "message": "Publish latest MiniBench Work read-only candidate snapshot",
        "content": base64.b64encode((json.dumps(snapshot,ensure_ascii=False,indent=2)+"\n").encode("utf-8")).decode("ascii")
    }
    if prior.status_code == 200:
        payload["sha"] = prior.json()["sha"]
    result = session.put(url, json=payload, headers=headers, timeout=25)
    if result.status_code not in (200,201):
        raise RuntimeError("STATE_WRITE_FAILED_" + str(result.status_code))
    return snapshot


def main():
    status = {"status":"STARTED","tournament":"minibench",
              "scope":"READ_ONLY_FEED_PUBLICATION_NO_PLATFORM_POST",
              "run_id":os.getenv("GITHUB_RUN_ID")}
    try:
        doc = json.loads(SRC.read_text(encoding="utf-8"))
        request_id = request_id_from_push()
        out = publish(doc,os.getenv("GITHUB_TOKEN",""),os.getenv("GITHUB_RUN_ID"),request_id=request_id)
        status.update(status="PUBLISHED_STATE_FEED",eligible=len(out["items"]),
                      feed_path=PATH,feed_branch=BRANCH,refresh_request_id=out["refresh_request_id"],
                      checked_at_utc=out["checked_at_utc"])
    except Exception as exc:
        # No exception text; HTTP failures may carry authentication details.
        status.update(status="PUBLISH_FAILED",error_type=type(exc).__name__)
    OUT.write_text(json.dumps(status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(status,ensure_ascii=False))
    return 0 if status["status"]=="PUBLISHED_STATE_FEED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
