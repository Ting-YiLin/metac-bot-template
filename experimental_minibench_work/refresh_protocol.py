"""Validate Work-triggered read-only MiniBench refresh requests.

No model execution, credentials access, or forecast submission.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

DIR=Path("experimental_minibench_work/refresh_requests")
NAME=re.compile(r"req-\d{8}T\d{6}Z-[a-z0-9]{6,16}\Z")

def validate_request(path,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    p=Path(path)
    if p.parent!=DIR or not NAME.fullmatch(p.stem) or p.suffix!=".json":
        raise ValueError("BAD_REQUEST_FILE_NAME")
    if not p.is_file() or p.stat().st_size>2048:
        raise ValueError("BAD_REQUEST_FILE")
    data=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data,dict) or set(data)!={"schema_version","request_id","source","tournament","intent","created_at_utc"}:
        raise ValueError("BAD_REQUEST_FIELDS")
    if data["schema_version"]!=1 or data["request_id"]!=p.stem:
        raise ValueError("BAD_REQUEST_ID")
    if data["source"]!="chatgpt_work_scheduled_forecast" or data["tournament"]!="minibench" or data["intent"]!="READ_ONLY_REFRESH":
        raise ValueError("FORBIDDEN_SCOPE")
    created=dt.datetime.fromisoformat(data["created_at_utc"].replace("Z","+00:00"))
    if created.tzinfo is None or created.utcoffset()!=dt.timedelta(0):
        raise ValueError("TIME_NOT_UTC")
    age=now-created
    if age < -dt.timedelta(minutes=2) or age>dt.timedelta(minutes=30):
        raise ValueError("STALE_REQUEST")
    id_time=dt.datetime.strptime(p.stem[4:20],"%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    if abs((created-id_time).total_seconds())>120:
        raise ValueError("ID_TIME_MISMATCH")
    return p.stem

def request_id_from_push(now=None):
    if os.getenv("GITHUB_EVENT_NAME")!="push":
        return None
    run=subprocess.run(["git","diff-tree","--no-commit-id","--name-only","--diff-filter=A","-r","HEAD"],
        capture_output=True,text=True,timeout=10,check=True)
    files=sorted(set(Path(x) for x in run.stdout.splitlines() if Path(x).parent==DIR and x.endswith(".json")))
    if len(files)>1:
        raise ValueError("MULTIPLE_REFRESH_REQUESTS")
    return validate_request(files[0],now) if files else None
