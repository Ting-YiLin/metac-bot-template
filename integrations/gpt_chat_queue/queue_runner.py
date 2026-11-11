"""GPT -> GitHub -> Metaculus testing-area queue consumer.

Hard gates: test tournament only, binary only, exact question IDs, valid
forecast age, platform OPEN and unforecasted, durable two-failure policy.
No model calls. No competition submissions.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT = Path("gpt_queue_receipt.json")
QUEUE_DIR = Path("integrations/gpt_chat_queue/pending")
ALLOWED_MARKETS = (
    "polymarket", "kalshi", "manifold",
    "metaculus", "hypermind", "betfair",
)
ALLOWED_STATUSES = {
    "VERIFIED_EXACT", "RULE_MISMATCH", "RELATED_ONLY",
    "NOT_FOUND", "ACCESS_BLOCKED",
}
MAX_AGE_MINUTES = 60
REQUIRED_ROUNDS = ("broad", "deep", "local_language")


def parse_utc(s):
    if not isinstance(s, str) or not s:
        raise ValueError("INVALID_UTC_TIME")
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def validate_payload(data, path, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(data, dict):
        raise ValueError("NOT_JSON_OBJECT")
    if data.get("schema_version") != 1:
        raise ValueError("INVALID_SCHEMA_VERSION")
    if data.get("source") != "chatgpt_scheduled_research":
        raise ValueError("INVALID_SOURCE")
    if data.get("tournament") != "bot-testing-area":
        raise ValueError("FORBIDDEN_TOURNAMENT")
    if data.get("question_type") != "BinaryQuestion":
        raise ValueError("BINARY_ONLY")
    post_id, question_id = data.get("post_id"), data.get("question_id")
    if type(post_id) is not int or type(question_id) is not int or min(post_id, question_id) <= 0:
        raise ValueError("INVALID_QUESTION_IDS")
    if not re.fullmatch(r"q-\d+-\d+-[a-zA-Z0-9_-]{4,48}\.json", Path(path).name):
        raise ValueError("INVALID_QUEUE_FILENAME")
    if not Path(path).name.startswith(f"q-{post_id}-{question_id}-"):
        raise ValueError("FILENAME_QUESTION_ID_MISMATCH")
    p = data.get("p_yes")
    if type(p) not in (int, float) or not math.isfinite(p) or not (0.001 <= p <= 0.999):
        raise ValueError("INVALID_P_YES")
    if not isinstance(data.get("reasoning"), str) or not (20 <= len(data["reasoning"]) <= 7000):
        raise ValueError("INVALID_REASONING")
    forecast_time = parse_utc(data.get("forecast_created_at_utc"))
    cutoff = parse_utc(data.get("evidence_cutoff_utc"))
    if cutoff > forecast_time or forecast_time > now + timedelta(minutes=2):
        raise ValueError("INVALID_TIME_ORDER")
    if not (timedelta(0) <= now - forecast_time <= timedelta(minutes=MAX_AGE_MINUTES)):
        raise ValueError("STALE_FORECAST")
    rounds = data.get("research_rounds")
    if not isinstance(rounds, dict) or set(rounds) != set(REQUIRED_ROUNDS):
        raise ValueError("MISSING_RESEARCH_ROUNDS")
    total_sources = 0
    for stage in REQUIRED_ROUNDS:
        rd = rounds[stage]
        if not isinstance(rd, dict) or rd.get("status") not in ("DONE", "BLOCKED"):
            raise ValueError("INVALID_RESEARCH_ROUND_" + stage)
        if not isinstance(rd.get("queries"), list) or not rd["queries"]:
            raise ValueError("NO_QUERIES_" + stage)
        if any(not isinstance(q, str) or not q.strip() for q in rd["queries"]):
            raise ValueError("INVALID_QUERY_" + stage)
        sources = rd.get("sources")
        if not isinstance(sources, list):
            raise ValueError("INVALID_SOURCES_" + stage)
        for source in sources:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                raise ValueError("INVALID_SOURCE_ENTRY_" + stage)
            if not source["url"].startswith(("https://", "http://")):
                raise ValueError("INVALID_SOURCE_URL_" + stage)
        total_sources += len(sources)
        if stage == "local_language" and not isinstance(rd.get("language"), str):
            raise ValueError("MISSING_LOCAL_LANGUAGE")
    if total_sources < 1:
        raise ValueError("NO_DOCUMENTED_SOURCES")
    markets = data.get("market_checks")
    if not isinstance(markets, dict) or set(markets) != set(ALLOWED_MARKETS):
        raise ValueError("MISSING_MARKET_CHECKS")
    for market, record in markets.items():
        if not isinstance(record, dict) or record.get("status") not in ALLOWED_STATUSES:
            raise ValueError("INVALID_MARKET_STATUS_" + market)
        if record["status"] == "VERIFIED_EXACT":
            prob = record.get("p_yes")
            if type(prob) not in (int, float) or not math.isfinite(prob) or not (0 <= prob <= 1):
                raise ValueError("INVALID_EXACT_MARKET_P_" + market)
            if not isinstance(record.get("url"), str) or not record["url"].startswith(("https://", "http://")):
                raise ValueError("MISSING_MARKET_URL_" + market)
    if data.get("mode") not in ("DRY_RUN", "TEST_SUBMIT"):
        raise ValueError("INVALID_MODE")
    return data


def paths_from_event(event_file):
    if not event_file:
        return []
    info = json.loads(Path(event_file).read_text(encoding="utf-8"))
    paths = set()
    for commit in info.get("commits", []):
        for path in commit.get("added", []) + commit.get("modified", []):
            if isinstance(path, str):
                p = Path(path)
                if p.parent == QUEUE_DIR and p.suffix == ".json":
                    paths.add(path)
    return sorted(paths)


def select_testing_question(client, data):
    from forecasting_tools.data_models.questions import QuestionState

    questions = client.get_all_open_questions_from_tournament("bot-testing-area")
    selected = [
        q for q in questions
        if getattr(q, "id_of_post", None) == data["post_id"]
        and getattr(q, "id_of_question", None) == data["question_id"]
    ]
    if len(selected) != 1:
        return None, "NOT_FOUND_IN_TESTING_AREA"
    q = selected[0]
    if type(q).__name__ != "BinaryQuestion":
        return None, "PLATFORM_QUESTION_TYPE_MISMATCH"
    if q.state != QuestionState.OPEN:
        return None, "QUESTION_NOT_OPEN"
    if q.already_forecasted is not False:
        return None, "ALREADY_FORECASTED_OR_UNKNOWN"
    return q, "ELIGIBLE"


def process_one(path, client, ledger, live_enabled, now=None):
    entry = {"path": str(path), "status": "STARTED", "submitted": False}
    try:
        data = validate_payload(json.loads(Path(path).read_text(encoding="utf-8")), path, now)
        entry.update({"post_id": data["post_id"], "question_id": data["question_id"],
                      "mode": data["mode"], "p_yes": data["p_yes"]})
        if ledger is None or not ledger.available:
            entry["status"] = "STOP_LEDGER_UNAVAILABLE"
            return entry
        if ledger.failures_for(type("Q", (), {"id_of_question": data["question_id"]})()) >= 2:
            entry["status"] = "SKIP_TWO_PREVIOUS_FAILURES"
            return entry
        q, reason = select_testing_question(client, data)
        if q is None:
            entry["status"] = "SKIP_" + reason
            return entry
        entry["status"] = "VALIDATED_ELIGIBLE"
        if data["mode"] == "DRY_RUN" or not live_enabled:
            entry["status"] = "PASS_DRY_RUN"
            return entry
        # Final independent readback before submission; duplicate-risk is fail-closed.
        from live_free_runner import readback_selected_question
        if readback_selected_question(client, q) is not False:
            entry["status"] = "SKIP_READBACK_ALREADY_OR_UNKNOWN"
            return entry
        try:
            client.post_binary_question_prediction(
                question_id=data["question_id"],
                prediction_in_decimal=float(data["p_yes"]),
            )
            entry["submission_function_returned"] = True
        except Exception as exc:
            entry["submit_error_type"] = type(exc).__name__
            entry["submission_function_returned"] = False
        # Never retry a POST in the same run; check remote state instead.
        try:
            rb = readback_selected_question(client, q)
        except Exception as exc:
            rb = None
            entry["readback_error_type"] = type(exc).__name__
        entry["platform_readback_already_forecasted"] = rb
        if rb is True:
            entry["status"] = "PASS_SUBMITTED_READBACK"
            entry["submitted"] = True
        elif entry.get("submission_function_returned") is True:
            entry["status"] = "UNCONFIRMED_SUBMISSION_DO_NOT_RETRY"
        else:
            entry["status"] = "FAILED_SUBMISSION_NO_CONFIRMATION"
            if ledger is not None and ledger.available:
                entry["persistent_failures"] = ledger.record_failure(
                    q, run_id=os.getenv("GITHUB_RUN_ID", ""),
                    error_type=entry.get("submit_error_type", "Unknown"),
                )
        return entry
    except Exception as exc:
        entry["status"] = "REJECTED"
        entry["error_type"] = type(exc).__name__
        entry["error"] = str(exc)[:200]
        return entry


def main():
    from forecasting_tools import MetaculusClient
    from tools.testing_failure_ledger import TestingFailureLedger

    event_path = os.getenv("GITHUB_EVENT_PATH")
    paths = paths_from_event(event_path)
    if not paths and os.getenv("GPT_QUEUE_ALLOW_ALL") == "1":
        paths = [str(p) for p in sorted(QUEUE_DIR.glob("q-*.json"))]
    live_enabled = os.getenv("GPT_QUEUE_LIVE_SUBMIT") == "1"
    ledger = TestingFailureLedger()
    ledger.load()
    client = MetaculusClient()
    result = {
        "mode": "TESTING_AREA_ONLY",
        "live_submit_enabled": live_enabled,
        "ledger_available": ledger.available,
        "processed": [],
        "queue_candidates": len(paths),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    for path in paths[:10]:
        result["processed"].append(process_one(path, client, ledger, live_enabled))
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "queue_candidates": result["queue_candidates"],
        "statuses": [p["status"] for p in result["processed"]],
        "confirmed_submissions": sum(x.get("submitted") is True for x in result["processed"]),
        "ledger_available": ledger.available,
    }))
    # Invalid queue submissions are visible in receipt, without causing an unsafe retry.
    return 0


if __name__ == "__main__":
    sys.exit(main())
