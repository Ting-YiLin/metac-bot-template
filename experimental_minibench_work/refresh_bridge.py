"""Wait for the exact GitHub read-only MiniBench refresh result in the SAME Work turn.

Use AFTER creating exactly one refresh request and obtaining its Git commit SHA.
This tool NEVER creates a forecast, enqueues a forecast, or posts to Metaculus.
No secret is required to read this public repository. Optional GITHUB_TOKEN
reduces rate-limiting, and is never emitted to logs.

Work:
  python experimental_minibench_work/refresh_bridge.py \
     --request-id req-YYYYMMDDTHHMMSSZ-abcdef12 --commit-sha <40hex> \
     --wait-seconds 180 --interval-seconds 12

EXIT 0 for READY or NO_ACTION only when matching run and fresh feed verified.
EXIT 1 for timed-out pending states; EXIT 2 for permanent refresh failure.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com/repos/Ting-YiLin/metac-bot-template"
WORKFLOW = "experimental_minibench_readonly.yml"
BRANCH = "experiment/work-luna-sol-minibench-20261117"
FEED_PATH = "state/minibench_work_candidate_feed.json"
FEED_BRANCH = "tingyi001-test-state"
REQUEST_PATTERN = re.compile(r"req-\d{8}T\d{6}Z-[a-z0-9]{6,16}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
PENDING = frozenset(("WAIT_RUN", "WAIT_REFRESH", "WAIT_FEED"))
TERMINAL = frozenset(("READY", "NO_ACTION"))
UTC = dt.timezone.utc


class BridgeError(Exception):
    pass


def timestamp(value):
    if not isinstance(value, str):
        raise BridgeError("INVALID_TIMESTAMP")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise BridgeError("INVALID_TIMESTAMP") from None
    if result.tzinfo is None:
        raise BridgeError("NAIVE_TIMESTAMP")
    return result.astimezone(UTC)


def find_exact_run(runs, sha):
    """A request commit triggers one push run on the isolated workflow."""
    if not isinstance(runs, list):
        raise BridgeError("RUN_LIST_INVALID")
    exact = [
        r for r in runs if isinstance(r, dict)
        and r.get("head_sha") == sha
        and r.get("event") == "push"
        and r.get("head_branch") == BRANCH
    ]
    if not exact:
        return None
    return max(exact, key=lambda r: int(r.get("id") or 0))


def evaluate_run(run):
    if run is None:
        return {"state": "WAIT_RUN"}
    run_id = str(run.get("id", ""))
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status != "completed":
        return {"state": "WAIT_REFRESH", "refresh_run_id": run_id}
    if conclusion != "success":
        return {"state": "BLOCKED_REFRESH_FAILED",
                "refresh_run_id": run_id,
                "conclusion": conclusion or "unknown"}
    return {"state": "WAIT_FEED", "refresh_run_id": run_id}


def evaluate_feed(feed, expected_request_id, run_id, now=None):
    now = now or dt.datetime.now(UTC)
    if not isinstance(feed, dict):
        raise BridgeError("FEED_NOT_OBJECT")
    if feed.get("refresh_request_id") != expected_request_id or str(feed.get("refresh_run_id")) != str(run_id):
        return {"state": "WAIT_FEED", "refresh_run_id": str(run_id)}
    if feed.get("refresh_trigger") != "WORK_REQUEST":
        raise BridgeError("FEED_REFRESH_TRIGGER_MISMATCH")
    if feed.get("tournament_requested") != "minibench":
        raise BridgeError("FEED_TOURNAMENT_MISMATCH")
    if feed.get("scope") != "AUTHENTICATED_OPEN_SLICE_ONLY_READ_ONLY_NO_SUBMISSION":
        raise BridgeError("FEED_SCOPE_MISMATCH")
    if feed.get("truncated") is True:
        raise BridgeError("FEED_TRUNCATED")
    items = feed.get("items")
    if not isinstance(items, list) or feed.get("eligible_after_status_and_deadline_check") != len(items):
        raise BridgeError("FEED_COUNT_MISMATCH")
    checked = timestamp(feed.get("checked_at_utc"))
    published = timestamp(feed.get("published_at_utc"))
    expires = timestamp(feed.get("freshness_expires_utc"))
    if checked > published + dt.timedelta(seconds=90) or published > now + dt.timedelta(minutes=2):
        raise BridgeError("FEED_TIME_INCONSISTENT")
    if expires <= now or now - checked > dt.timedelta(minutes=22):
        return {"state": "BLOCKED_MATCHED_FEED_EXPIRED", "refresh_run_id": str(run_id)}
    ids = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or type(item.get("question_id")) is not int or type(item.get("post_id")) is not int:
            raise BridgeError("FEED_ITEM_INVALID")
        key = (item["post_id"], item["question_id"])
        if key in seen:
            raise BridgeError("FEED_DUPLICATE_QUESTION")
        seen.add(key)
        ids.append({"question_id": key[1],
                    "post_id": key[0],
                    "question_type": item.get("question_type"),
                    "close_time_utc": item.get("close_time_utc")})
    return {
        "state": "READY" if items else "NO_ACTION",
        "refresh_run_id": str(run_id),
        "refresh_request_id": expected_request_id,
        "feed_checked_at_utc": feed["checked_at_utc"],
        "feed_expires_at_utc": feed["freshness_expires_utc"],
        "eligible": len(items),
        "candidates": ids,
    }


def http_json(url, params=None, token=None):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "MiniBenchRefreshBridgeV2"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise BridgeError("GITHUB_HTTP_" + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise BridgeError("GITHUB_READ_FAILED") from None


def probe_once(request_id, commit_sha, get_json=http_json, now=None):
    if not REQUEST_PATTERN.fullmatch(request_id) or not SHA_PATTERN.fullmatch(commit_sha):
        raise BridgeError("INVALID_REQUEST_IDENTIFIERS")
    params={"branch": BRANCH, "event": "push", "per_page": 50}
    runs_doc = get_json(f"{API}/actions/workflows/{WORKFLOW}/runs", params=params)
    run = find_exact_run(runs_doc.get("workflow_runs"), commit_sha)
    progress = evaluate_run(run)
    if progress["state"] != "WAIT_FEED":
        return progress
    # Only fetch the candidate feed after the exact read-only workflow completed.
    feed = get_json(f"{API}/contents/{FEED_PATH}",params={"ref":FEED_BRANCH})
    # GitHub Contents API returns base64 when using the REST contents endpoint.
    if "content" in feed and feed.get("encoding") == "base64":
        import base64
        try:
            feed=json.loads(base64.b64decode(feed["content"]).decode("utf-8"))
        except (ValueError, KeyError, TypeError):
            raise BridgeError("FEED_DECODE_FAILED") from None
    return evaluate_feed(feed,request_id,progress["refresh_run_id"],now)


def wait(request_id,commit_sha,timeout_seconds=180,interval_seconds=12,
         get_json=http_json,monotonic=time.monotonic,sleep=time.sleep):
    if not 0 <= timeout_seconds <= 240 or not 3 <= interval_seconds <= 60:
        raise BridgeError("INVALID_WAIT_BUDGET")
    deadline=monotonic()+timeout_seconds
    checks=0
    last={"state":"WAIT_RUN"}
    while True:
        checks+=1
        try:
            last=probe_once(request_id,commit_sha,get_json)
        except BridgeError as exc:
            if str(exc).startswith(("GITHUB_HTTP_429","GITHUB_HTTP_403","GITHUB_READ_FAILED")):
                last={"state":"WAIT_REFRESH","transient_error":str(exc)}
            else:
                raise
        last["checks"]=checks
        if last["state"] in TERMINAL or last["state"] not in PENDING:
            return last
        remaining=deadline-monotonic()
        if remaining<=0:
            return {**last,"state":"BLOCKED_REFRESH_TIMEOUT","last_state":last["state"],
                    "checks":checks}
        sleep(min(interval_seconds,remaining))


def main():
    parser=argparse.ArgumentParser(description="Validate same-turn refreshed MiniBench feed without posting")
    parser.add_argument("--request-id",required=True)
    parser.add_argument("--commit-sha",required=True)
    parser.add_argument("--wait-seconds",type=int,default=180)
    parser.add_argument("--interval-seconds",type=int,default=12)
    args=parser.parse_args()
    try:
        token=os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
        def fetch(url, params=None):
            return http_json(url,params,token)
        result=wait(args.request_id,args.commit_sha,args.wait_seconds,
                    args.interval_seconds,get_json=fetch)
    except BridgeError as exc:
        result={"state":"BLOCKED_REFRESH_BRIDGE","error_code":str(exc)}
    print(json.dumps(result,ensure_ascii=False,separators=(",",":")))
    return 0 if result["state"] in TERMINAL else 1 if result["state"]=="BLOCKED_REFRESH_TIMEOUT" else 2


if __name__ == "__main__":
    sys.exit(main())
