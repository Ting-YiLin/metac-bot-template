"""Unscored, no-POST MiniBench dry-run intake for Work -> GitHub handoff.

Never calls any Metaculus write method. Live tournament submission remains disabled.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from minibench_readonly_probe import closing_time, state_is_open
from validate_dryrun import validate

DIR = Path("experimental_minibench_work/pending")
OUT = Path("minibench_work_queue_receipt.json")
MAX_AGE = dt.timedelta(minutes=60)
NAME = re.compile(r"q-\d+-\d+-[a-zA-Z0-9_-]{4,48}\.json\Z")

def utc(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    t=dt.datetime.fromisoformat(value.replace("Z","+00:00"))
    if t.tzinfo is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return t.astimezone(dt.timezone.utc)

def validate_input(data, path, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if data.get("schema_version") != 1 or data.get("scope") != "MINIBENCH_WORK_DRY_RUN":
        raise ValueError("INVALID_SCHEMA")
    if data.get("tournament") != "minibench" or data.get("mode") != "DRY_RUN":
        raise ValueError("LIVE_OR_WRONG_TOURNAMENT")
    if data.get("source") != "work_luna_sol":
        raise ValueError("INVALID_ORIGIN")
    pid, qid = data.get("post_id"), data.get("question_id")
    if type(pid) is not int or type(qid) is not int or pid <= 0 or qid <= 0:
        raise ValueError("INVALID_IDS")
    p=Path(path)
    if p.parent != DIR or not NAME.fullmatch(p.name) or not p.name.startswith(f"q-{pid}-{qid}-"):
        raise ValueError("INVALID_PATH")
    prob = data.get("p_yes")
    if type(prob) not in (int,float) or not math.isfinite(prob) or not (0.001 <= prob <= 0.999):
        raise ValueError("INVALID_P_YES")
    reason=data.get("reasoning")
    if not isinstance(reason,str) or not (20 <= len(reason) <= 7000):
        raise ValueError("INVALID_REASON")
    sources = data.get("sources")
    if not isinstance(sources,list) or any(not isinstance(x,str) or not x.startswith(("https://","http://")) for x in sources):
        raise ValueError("INVALID_SOURCES")
    created=utc(data.get("forecast_created_at_utc"))
    cutoff=utc(data.get("evidence_cutoff_utc"))
    if created<cutoff or created>now+dt.timedelta(minutes=2) or now-created>MAX_AGE:
        raise ValueError("STALE_OR_IMPOSSIBLE_FORECAST")
    return data

def process_one(data, path, client, now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    result={"file":Path(path).name,"question_id":data.get("question_id") if isinstance(data,dict) else None,
            "status":"STARTED","submission_performed":False}
    try:
        validate_input(data,path,now)
        rows=client.get_all_open_questions_from_tournament("minibench")
        matched=[q for q in rows
                 if getattr(q,"id_of_post",None)==data["post_id"]
                 and getattr(q,"id_of_question",None)==data["question_id"]]
        if len(matched)!=1:
            result["status"]="BLOCKED_NOT_FOUND_IN_CURRENT_MINIBENCH"
            return result
        q=matched[0]
        if not state_is_open(q) or getattr(q,"already_forecasted",None) is not False:
            result["status"]="BLOCKED_OPEN_OR_FORECAST_STATUS"
            return result
        if type(q).__name__!="BinaryQuestion":
            result["status"]="BLOCKED_UNSUPPORTED_TYPE"
            return result
        close=closing_time(q)
        if not close or utc(close)<=now:
            result["status"]="BLOCKED_CLOSE_TIME"
            return result
        record={"target":{"tournament_id":"minibench","round_verified":True,
                          "question_id":data["question_id"],"post_id":data["post_id"],
                          "question_type":"BinaryQuestion","status":"OPEN",
                          "already_forecasted":False,"closes_at":close},
                "forecast":{"question_id":data["question_id"],"p_yes":data["p_yes"],
                            "reasoning":data["reasoning"],"sources":data["sources"]},
                "control":{"mode":"dry_run","submit_authorized":False,"post_state":"NONE"}}
        check=validate(record,now)
        result.update(status="PASS_DRY_RUN" if check["status"]=="DRY_RUN_VALID" else "BLOCKED_VALIDATOR",
                      gate_errors=check["errors"],p_yes=data["p_yes"],
                      deadline_utc=close,account_competition_admission_verified=False)
        return result
    except Exception as exc:
        result["status"]="REJECTED"
        result["error_type"]=type(exc).__name__
        return result

def event_files():
    if os.getenv("GITHUB_EVENT_NAME")!="push":
        return []
    finished=subprocess.run(
        ["git","diff-tree","--no-commit-id","--name-only","--diff-filter=A","-r","HEAD"],
        capture_output=True,text=True,timeout=10,check=True)
    return [Path(t) for t in finished.stdout.splitlines()
            if Path(t).parent==DIR and Path(t).suffix==".json"]

def main():
    paths=event_files()
    response={"scope":"MINIBENCH_DRY_RUN_NO_PLATFORM_POST",
              "run_id":os.getenv("GITHUB_RUN_ID"),"submitted":0,
              "files_seen":len(paths),"processed":[]}
    if paths:
        try:
            if not os.getenv("METACULUS_TOKEN"):
                response["status"]="BLOCKED_NO_TOKEN"
            else:
                from forecasting_tools import MetaculusClient
                client=MetaculusClient()
                for p in sorted(paths)[:10]:
                    data=json.loads(p.read_text(encoding="utf-8"))
                    response["processed"].append(process_one(data,p,client))
                response["status"]="PROCESSED_DRY_RUN"
        except Exception as exc:
            response["status"]="BLOCKED_API_OR_INPUT"
            response["error_type"]=type(exc).__name__
    else:
        response["status"]="NO_NEW_FORECAST_FILES"
    OUT.write_text(json.dumps(response,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":response["status"],"files_seen":len(paths),
                      "results":[x["status"] for x in response["processed"]],"submitted":0}))
    return 0 if response["status"] in ("NO_NEW_FORECAST_FILES","PROCESSED_DRY_RUN") else 2

if __name__=="__main__":
    raise SystemExit(main())
