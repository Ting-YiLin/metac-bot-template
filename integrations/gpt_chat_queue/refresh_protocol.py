"""Validate GPT-triggered, read-only Metaculus candidate refresh requests.

A new request file on main starts a GitHub Actions push workflow.
Only requests with a matching file name, schema, scope and fresh UTC
timestamp are accepted. This module has no prediction or submission code.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

REQUEST_DIR = Path("integrations/gpt_chat_queue/refresh_requests")
ID_RE = re.compile(r"req-\d{8}T\d{6}Z-[a-z0-9]{6,16}\Z")
MAX_REQUEST_AGE = timedelta(minutes=30)


def utc_time(value):
    if not isinstance(value, str) or not value:
        raise ValueError("MISSING_UTC_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("INVALID_UTC_TIMESTAMP") from e
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
        raise ValueError("REQUIRES_UTC_TIMESTAMP")
    return dt.astimezone(timezone.utc)


def validate_request(path, now=None):
    now = now or datetime.now(timezone.utc)
    path = Path(path)
    if path.parent != REQUEST_DIR or not path.name.startswith("req-") or path.suffix != ".json":
        raise ValueError("FORBIDDEN_REQUEST_PATH")
    request_id = path.stem
    if not ID_RE.fullmatch(request_id):
        raise ValueError("INVALID_REQUEST_ID")
    if not path.is_file() or path.stat().st_size > 2048:
        raise ValueError("INVALID_REQUEST_FILE")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "request_id", "source", "tournament",
        "intent", "created_at_utc",
    }:
        raise ValueError("INVALID_REQUEST_FIELDS")
    if payload["schema_version"] != 1:
        raise ValueError("INVALID_SCHEMA")
    if payload["request_id"] != request_id:
        raise ValueError("REQUEST_ID_MISMATCH")
    if payload["source"] != "chatgpt_scheduled_research":
        raise ValueError("INVALID_SOURCE")
    if payload["tournament"] != "bot-testing-area":
        raise ValueError("FORBIDDEN_TOURNAMENT")
    if payload["intent"] != "READ_ONLY_REFRESH":
        raise ValueError("FORBIDDEN_REQUEST_INTENT")
    created = utc_time(payload["created_at_utc"])
    age = now - created
    if age < timedelta(minutes=-2) or age > MAX_REQUEST_AGE:
        raise ValueError("REQUEST_TIMESTAMP_OUT_OF_RANGE")
    id_time = datetime.strptime(request_id[4:20], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    if abs((created - id_time).total_seconds()) > 120:
        raise ValueError("ID_TIMESTAMP_MISMATCH")
    return request_id


def newly_added_request_paths(*, run_git=subprocess.run):
    completed = run_git(
        ["git", "diff-tree", "--no-commit-id", "--name-only",
         "--diff-filter=A", "-r", "HEAD"],
        capture_output=True, text=True, check=True, timeout=15,
    )
    return sorted(
        set(line.strip() for line in completed.stdout.splitlines()
            if Path(line.strip()).parent == REQUEST_DIR
            and line.strip().endswith(".json"))
    )


def request_id_from_push(event_name, *, now=None, run_git=subprocess.run):
    if event_name != "push":
        return None
    paths = newly_added_request_paths(run_git=run_git)
    if len(paths) > 1:
        raise ValueError("MULTIPLE_REQUESTS_IN_SINGLE_PUSH")
    if not paths:
        # A push changing the workflow definition can also trigger this job.
        return None
    return validate_request(paths[0], now=now)
