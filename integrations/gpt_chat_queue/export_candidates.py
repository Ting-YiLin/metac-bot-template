"""Publish a minimal live Metaculus testing-area candidate feed to isolated state branch.

No forecast generation, no platform submissions. ChatGPT can read via GitHub
connector, without holding any Metaculus API credential.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from refresh_protocol import request_id_from_push

REPO = "Ting-YiLin/metac-bot-template"
BRANCH = "tingyi001-test-state"
PATH = "state/gpt_chat_candidate_feed.json"
OUT = Path("gpt_chat_candidate_feed_receipt.json")


def serialize_text(value, limit=9000):
    return str(value or "")[:limit]


def collect_feed(client, now=None):
    from forecasting_tools.data_models.questions import QuestionState

    now = now or datetime.now(timezone.utc)
    rows = client.get_all_open_questions_from_tournament("bot-testing-area")
    items = []
    skipped_existing = 0
    for q in rows:
        if q.state != QuestionState.OPEN or q.already_forecasted is not False:
            skipped_existing += 1
            continue
        item = {
            "post_id": getattr(q, "id_of_post", None),
            "question_id": getattr(q, "id_of_question", None),
            "question_type": type(q).__name__,
            "question_text": serialize_text(getattr(q, "question_text", None), 12000),
            "background_info": serialize_text(getattr(q, "background_info", None)),
            "resolution_criteria": serialize_text(getattr(q, "resolution_criteria", None)),
            "fine_print": serialize_text(getattr(q, "fine_print", None)),
            "close_time": serialize_text(
                getattr(q, "scheduled_close_time", None)
                or getattr(q, "close_time", None)
                or getattr(q, "forecasting_close_time", None)
            ),
            "url": serialize_text(getattr(q, "page_url", None)),
        }
        if item["post_id"] and item["question_id"]:
            items.append(item)
    items.sort(key=lambda x: (x["close_time"], x["post_id"], x["question_id"]))
    return {
        "schema_version": 1,
        "checked_at_utc": now.isoformat(),
        "tournament": "bot-testing-area",
        "open_questions_seen": len(rows),
        "eligible_unforecasted": len(items),
        "excluded_or_forecasted": skipped_existing,
        "items": items,
        "scope": "READ_ONLY_QUESTION_FEED_NO_FORECAST_NO_SUBMISSION",
    }


def publish_to_github(feed, token, *, requests_module=requests):
    if not token:
        raise RuntimeError("GITHUB_TOKEN_MISSING")
    url = f"https://api.github.com/repos/{REPO}/contents/{PATH}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
        "User-Agent": "TingYi001GPTQuestionFeed",
    }
    old = requests_module.get(url, params={"ref": BRANCH}, headers=headers, timeout=20)
    if old.status_code not in (200, 404):
        raise RuntimeError("GITHUB_FEED_READ_" + str(old.status_code))
    payload = {
        "branch": BRANCH,
        "message": "Refresh public testing-area question feed (read only)",
        "content": base64.b64encode(
            (json.dumps(feed, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        ).decode("ascii"),
    }
    if old.status_code == 200:
        payload["sha"] = old.json()["sha"]
    put = requests_module.put(url, headers=headers, json=payload, timeout=25)
    if put.status_code not in (200, 201):
        raise RuntimeError("GITHUB_FEED_WRITE_" + str(put.status_code))
    return True


def main():
    from forecasting_tools import MetaculusClient
    result = {"status": "STARTED", "checked_at_utc": datetime.now(timezone.utc).isoformat()}
    try:
        request_id = request_id_from_push(os.getenv("GITHUB_EVENT_NAME", ""))
        result["refresh_request_id"] = request_id
        feed = collect_feed(MetaculusClient())
        feed["refresh_request_id"] = request_id
        feed["refresh_trigger"] = "GPT_REQUEST" if request_id else os.getenv("GITHUB_EVENT_NAME", "unknown")
        feed["refresh_run_id"] = os.getenv("GITHUB_RUN_ID")
        feed["refresh_trigger_commit"] = os.getenv("GITHUB_SHA")
        feed["refresh_completed_at_utc"] = datetime.now(timezone.utc).isoformat()
        result.update({
            "status": "FETCHED",
            "eligible_unforecasted": feed["eligible_unforecasted"],
            "open_questions_seen": feed["open_questions_seen"],
        })
        publish_to_github(feed, os.getenv("GITHUB_TOKEN", ""))
        result["status"] = "PUBLISHED_TO_STATE_BRANCH"
    except Exception as exc:
        result["status"] = "FAILED_NO_FEED_UPDATE"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)[:180]
    finally:
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PUBLISHED_TO_STATE_BRANCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
