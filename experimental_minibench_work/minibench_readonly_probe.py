"""Read-only MiniBench snapshot through the existing forecasting-tools client.

This module intentionally contains no Metaculus write or forecast methods.
It checks OPEN questions only. Its output is not proof of account admission.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter
from all_types_adapter import forecast_format_skeleton, KINDS
from pathlib import Path

TOURNAMENT = "minibench"
OUT = Path("minibench_readonly_probe_receipt.json")
FEED = Path("minibench_readonly_candidate_feed.json")
MAX_ITEMS = 150


def state_is_open(q):
    state = getattr(q, "state", None)
    return str(getattr(state, "name", state)).upper() == "OPEN"


def as_iso(value):
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(dt.timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return t.astimezone(dt.timezone.utc).isoformat() if t.tzinfo else None
        except ValueError:
            return None
    return None


def closing_time(q):
    for attr in ("scheduled_close_time", "close_time", "forecasting_close_time"):
        value = as_iso(getattr(q, attr, None))
        if value:
            return value
    return None


def text_field(q, attr, max_length=8000):
    x = getattr(q, attr, None)
    return x[:max_length] if isinstance(x, str) else ""


def collect(client, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    checked = now.astimezone(dt.timezone.utc).isoformat()
    questions = client.get_all_open_questions_from_tournament(TOURNAMENT)
    if not isinstance(questions, list):
        questions = list(questions)
    counts = Counter()
    items = []
    seen = set()
    for q in questions:
        counts["api_rows"] += 1
        if not state_is_open(q):
            counts["not_open"] += 1
            continue
        pid, qid = getattr(q, "id_of_post", None), getattr(q, "id_of_question", None)
        if type(pid) is not int or type(qid) is not int or pid <= 0 or qid <= 0:
            counts["missing_identifiers"] += 1
            continue
        if (pid, qid) in seen:
            counts["duplicate_identifiers"] += 1
            continue
        seen.add((pid, qid))
        prev = getattr(q, "already_forecasted", None)
        if prev is True:
            counts["already_forecasted"] += 1
            continue
        if prev is not False:
            counts["forecast_status_unknown"] += 1
            continue
        close_iso = closing_time(q)
        if not close_iso:
            counts["missing_close_time"] += 1
            continue
        if dt.datetime.fromisoformat(close_iso) <= now:
            counts["already_closed"] += 1
            continue
        qtype = type(q).__name__
        counts["eligible_" + qtype] += 1
        if qtype not in KINDS:
            counts["unsupported_type"] += 1
        url = getattr(q, "page_url", None)
        try:
            format_context = forecast_format_skeleton(q)
        except Exception:
            # Retain question in coverage statistics; mark metadata incomplete,
            # never invent bounds or options.
            format_context = {"question_type": qtype, "format_error": "SDK_METADATA_MISSING"}
            counts["format_context_missing"] += 1
        item = {
            "post_id": pid, "question_id": qid, "question_type": qtype,
            "format_context": format_context,
            "close_time_utc": close_iso,
            "question_text": text_field(q, "question_text", 12000),
            "background_info": text_field(q, "background_info"),
            "resolution_criteria": text_field(q, "resolution_criteria"),
            "fine_print": text_field(q, "fine_print"),
            "url": url if isinstance(url, str) and url.startswith("https://www.metaculus.com/") else None,
            "supported_by_current_validator": qtype in KINDS and "format_error" not in format_context,
        }
        items.append(item)
    items.sort(key=lambda item: (item["close_time_utc"], item["post_id"], item["question_id"]))
    feed = {
        "schema_version": 1,
        "scope": "AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION",
        "tournament_requested": TOURNAMENT,
        "checked_at_utc": checked,
        "complete_60_question_census": False,
        "bot_account_tournament_admission_verified": False,
        "api_open_rows": counts["api_rows"],
        "eligible_after_status_and_deadline_check": len(items),
        "supported_binary": sum(x["supported_by_current_validator"] for x in items),
        "counts": dict(counts),
        "items": items[:MAX_ITEMS],
        "truncated": len(items) > MAX_ITEMS,
    }
    return feed


def run(client_factory=None, token=None, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    token = os.getenv("METACULUS_TOKEN") if token is None else token
    receipt = {
        "schema_version": 1, "tournament": TOURNAMENT,
        "checked_at_utc": now.astimezone(dt.timezone.utc).isoformat(),
        "scope": "READ_ONLY_NO_FORECAST_POST_NO_COMMENT_POST",
        "api_token_present": bool(token), "status": "STARTED",
    }
    feed = None
    if not token:
        receipt["status"] = "BLOCKED_MISSING_PLATFORM_TOKEN"
    else:
        try:
            if client_factory is None:
                from forecasting_tools import MetaculusClient
                client_factory = MetaculusClient
            feed = collect(client_factory(), now)
            receipt["status"] = "OPEN_SLICE_FETCHED"
            receipt["api_open_rows"] = feed["api_open_rows"]
            receipt["eligible_unforecasted"] = feed["eligible_after_status_and_deadline_check"]
            receipt["eligible_binary"] = feed["supported_binary"]
            receipt["nonbinary_unsupported"] = feed["counts"].get("unsupported_type", 0)
            receipt["account_admission_verified"] = False
        except Exception as exc:
            # Avoid printing request headers, URLs or exceptions that could contain tokens.
            receipt["status"] = "FETCH_FAILED"
            receipt["error_type"] = type(exc).__name__
    return receipt, feed


def main():
    receipt, feed = run()
    if feed is not None:
        FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt["status"] == "OPEN_SLICE_FETCHED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
