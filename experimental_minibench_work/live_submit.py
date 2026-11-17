"""MiniBench encrypted Work queue -> scored forecast + PRIVATE rationale.

Allowed only in isolated live workflow, from new sealed-queue file.
POST each prediction at most once, even on timeout; always read back.
Never publishes raw p_yes or rationale in Actions logs/artifacts.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
import requests

from sealed_queue import unseal
from minibench_readonly_probe import closing_time,state_is_open

QUEUE_DIR=Path("experimental_minibench_work/live_pending")
RECEIPT=Path("minibench_live_submit_receipt.json")
API="https://www.metaculus.com/api"
ALLOWED_TOURNAMENT="minibench"
# Pilot question was shown to the human while still open; do not hand-select it for scoring.
EXCLUDED_PREVIEWED_QUESTION_IDS={46868}
MAX_FORECAST_AGE=dt.timedelta(minutes=60)

def utc(s):
    if not isinstance(s,str):raise ValueError("INVALID_TIME")
    val=dt.datetime.fromisoformat(s.replace("Z","+00:00"))
    if val.tzinfo is None:raise ValueError("TIMEZONE_REQUIRED")
    return val.astimezone(dt.timezone.utc)

def validate_data(data,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    expected={"schema_version":1,"scope":"MINIBENCH_WORK_LIVE_V1","tournament":"minibench",
              "mode":"LIVE","source":"work_luna_sol","question_type":"BinaryQuestion"}
    if not isinstance(data,dict) or any(data.get(k)!=v for k,v in expected.items()):
        raise ValueError("INVALID_LIVE_CONTRACT")
    pid,qid=data.get("post_id"),data.get("question_id")
    if type(pid) is not int or type(qid) is not int or min(pid,qid)<=0:
        raise ValueError("INVALID_IDS")
    if qid in EXCLUDED_PREVIEWED_QUESTION_IDS:
        raise ValueError("PREVIEWED_QUESTION_EXCLUDED")
    p=data.get("p_yes")
    if type(p) not in (float,int) or not math.isfinite(p) or not (0.001<=p<=0.999):
        raise ValueError("INVALID_BINARY_PROBABILITY")
    rationale=data.get("reasoning")
    if not isinstance(rationale,str) or not (50<=len(rationale)<=7000):
        raise ValueError("INVALID_PRIVATE_RATIONALE")
    sources=data.get("sources")
    if not isinstance(sources,list) or not sources or any(not isinstance(s,str) or not s.startswith("https://") for s in sources):
        raise ValueError("NO_VERIFIABLE_EVIDENCE_URLS")
    for field in ("sol_model","sol_effort","research_model"):
        if not isinstance(data.get(field),str) or not data[field].strip():
            raise ValueError("MODEL_PROVENANCE_MISSING")
    cutoff=utc(data.get("evidence_cutoff_utc"))
    created=utc(data.get("forecast_created_at_utc"))
    if cutoff>created or created>now+dt.timedelta(minutes=2) or now-created>MAX_FORECAST_AGE:
        raise ValueError("STALE_OR_IMPOSSIBLE_FORECAST")
    return data

def select_from_current(client,data,now=None):
    now=now or dt.datetime.now(dt.timezone.utc)
    questions=client.get_all_open_questions_from_tournament(ALLOWED_TOURNAMENT)
    matches=[q for q in questions
             if getattr(q,"id_of_post",None)==data["post_id"]
             and getattr(q,"id_of_question",None)==data["question_id"]]
    if len(matches)!=1:return None,"NOT_IN_CURRENT_OPEN_MINIBENCH"
    q=matches[0]
    if type(q).__name__!="BinaryQuestion":return None,"NOT_BINARY"
    if not state_is_open(q):return None,"NOT_OPEN"
    if getattr(q,"already_forecasted",None) is not False:return None,"ALREADY_FORECASTED_OR_UNKNOWN"
    close=closing_time(q)
    if not close:return None,"UNKNOWN_CLOSING_TIME"
    if utc(close)<now+dt.timedelta(minutes=2):return None,"TOO_CLOSE_TO_DEADLINE"
    return q,"ELIGIBLE"

def get_forecast_readback(post_id,question_id,p_yes,token,session=requests):
    r=session.get(f"{API}/posts/{post_id}/",
        headers={"Authorization":"Token "+token},timeout=20)
    if r.status_code!=200:return {"state":"READBACK_HTTP_ERROR","http_status":r.status_code}
    body=r.json()
    obj=body.get("question",{})
    if not isinstance(obj,dict) or obj.get("id")!=question_id:
        return {"state":"READBACK_QUESTION_MISMATCH"}
    latest=(obj.get("my_forecasts") or {}).get("latest") or {}
    values=latest.get("forecast_values")
    if not isinstance(values,list) or len(values)!=2:
        return {"state":"READBACK_MISSING_OR_UNKNOWN"}
    try:
        observed=float(values[1])
    except (TypeError,ValueError):
        return {"state":"READBACK_INVALID_VALUE"}
    if not math.isfinite(observed):return {"state":"READBACK_INVALID_VALUE"}
    return {"state":"FORECAST_CONFIRMED" if abs(observed-p_yes)<=0.00001 else "READBACK_DIFFERENT_P",
            "value_match":abs(observed-p_yes)<=0.00001}

def post_private_comment(post_id,text,token,session=requests):
    headers={"Authorization":"Token "+token}
    request={"text":text,"parent":None,"included_forecast":True,
             "is_private":True,"on_post":post_id}
    result={"post_attempted":True,"confirmed":False}
    try:
        r=session.post(f"{API}/comments/create/",headers=headers,json=request,timeout=30)
        result["post_http_status"]=r.status_code
        if not (200<=r.status_code<300):
            result["state"]="COMMENT_POST_ERROR_NO_RETRY"
            return result
        try:
            content=r.json()
            comment_id=content.get("id")
        except Exception:
            comment_id=None
        if not isinstance(comment_id,int):
            result["state"]="COMMENT_POST_RETURNED_NO_READBACK_ID"
            return result
        result["comment_id"]=comment_id
    except Exception as exc:
        result.update(state="COMMENT_POST_UNKNOWN_NO_RETRY",error_type=type(exc).__name__)
        return result
    try:
        rb=session.get(f"{API}/comments/{comment_id}/",headers=headers,timeout=20)
        if rb.status_code==200:
            detail=rb.json()
            if detail.get("id")==comment_id and detail.get("text")==text and detail.get("is_private") is True:
                result["state"]="PRIVATE_COMMENT_CONFIRMED"
                result["confirmed"]=True
            else:
                result["state"]="COMMENT_READBACK_UNMATCHED"
        else:
            result.update(state="COMMENT_READBACK_HTTP_ERROR",readback_http_status=rb.status_code)
    except Exception as exc:
        result.update(state="COMMENT_READBACK_UNKNOWN",error_type=type(exc).__name__)
    return result

def process_one(envelope,client,token,now=None,session=requests):
    now=now or dt.datetime.now(dt.timezone.utc)
    result={"state":"STARTED","forecast_post_attempted":False,
            "forecast_confirmed":False,"comment_confirmed":False,
            "submission_type":"SCORING_COMPETITION","tournament":"minibench",
            "processed_at_utc":now.isoformat()}
    try:
        data=validate_data(unseal(envelope,token),now)
        result.update(post_id=data["post_id"],question_id=data["question_id"],
                      research_model=data["research_model"],sol_model=data["sol_model"],
                      sol_effort=data["sol_effort"],
                      evidence_cutoff_utc=data["evidence_cutoff_utc"],
                      forecast_created_at_utc=data["forecast_created_at_utc"],
                      reasoning_digest=hashlib.sha256(data["reasoning"].encode()).hexdigest())
    except Exception as exc:
        result.update(state="REJECTED_INPUT",error_type=type(exc).__name__)
        return result
    try:
        q,eligible=select_from_current(client,data,now)
    except Exception as exc:
        result.update(state="READONLY_PREFLIGHT_FAILED",error_type=type(exc).__name__)
        return result
    if q is None:
        result["state"]="BLOCKED_"+eligible
        return result
    result["deadline_utc"]=closing_time(q)
    # A separate exact account readback prevents a second post on ambiguous SDK state.
    try:
        before=get_forecast_readback(data["post_id"],data["question_id"],data["p_yes"],token,session)
        result["preflight_exact_readback_state"]=before["state"]
        if before["state"]!="READBACK_MISSING_OR_UNKNOWN":
            result["state"]="BLOCKED_PREFLIGHT_"+before["state"]
            return result
    except Exception as exc:
        result.update(state="BLOCKED_PREFLIGHT_READBACK_ERROR",error_type=type(exc).__name__)
        return result
    # Exactly one forecast POST. Any failure transitions to GET-only verification.
    result["forecast_post_attempted"]=True
    try:
        client.post_binary_question_prediction(
            question_id=data["question_id"],
            prediction_in_decimal=float(data["p_yes"]))
        result["forecast_post_returned"]=True
    except Exception as exc:
        result.update(forecast_post_returned=False,
                      forecast_post_error_type=type(exc).__name__)
    for k in range(3):
        try:
            after=get_forecast_readback(data["post_id"],data["question_id"],data["p_yes"],token,session)
            result["forecast_readback_state"]=after["state"]
            if after["state"]=="FORECAST_CONFIRMED":
                result["forecast_confirmed"]=True
                break
            if after["state"]=="READBACK_DIFFERENT_P":
                break
        except Exception as exc:
            result["readback_error_type"]=type(exc).__name__
        if k<2:time.sleep(1)
    if not result["forecast_confirmed"]:
        result["state"]="FORECAST_UNCONFIRMED_NEVER_AUTO_RETRY"
        return result
    # Mandatory private rationale. One POST only, readback by comment id.
    private_text=(f"Autonomous forecast reasoning (Sol final judgment).\n\n"
                  f"{data['reasoning']}\n\n"
                  f"Evidence sources:\n"+ "\n".join(data["sources"][:12]))
    comment=post_private_comment(data["post_id"],private_text,token,session)
    result["comment_post_state"]=comment["state"]
    result["comment_confirmed"]=comment["confirmed"]
    if "comment_id" in comment:result["comment_id"]=comment["comment_id"]
    if "post_http_status" in comment:result["comment_http_status"]=comment["post_http_status"]
    result["state"]="FORECAST_AND_PRIVATE_COMMENT_CONFIRMED" if comment["confirmed"] else "FORECAST_CONFIRMED_COMMENT_UNCONFIRMED_NO_AUTO_RETRY"
    return result

def changed_files():
    if os.getenv("GITHUB_EVENT_NAME")!="push":return []
    r=subprocess.run(["git","diff-tree","--no-commit-id","--name-only",
                      "--diff-filter=A","-r","HEAD"],capture_output=True,text=True,
                     timeout=15,check=True)
    return sorted(set(Path(s) for s in r.stdout.splitlines()
                      if Path(s).parent==QUEUE_DIR
                      and re.fullmatch(r"sealed-[a-f0-9]{12,40}\.json",Path(s).name)))

def main():
    files=changed_files()
    receipt={"workflow":"MINIBENCH_LIVE_SCORING","run_id":os.getenv("GITHUB_RUN_ID"),
             "processed_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
             "files_seen":len(files),"entries":[],"raw_forecasts_redacted":True}
    if os.getenv("BTF3_MINIBENCH_LIVE_APPROVED")!="1":
        receipt["state"]="BLOCKED_NOT_APPROVED"
    elif not files:
        receipt["state"]="NO_NEW_ENCRYPTED_FORECAST"
    elif len(files)>3:
        receipt["state"]="BLOCKED_TOO_MANY_FILES"
    else:
        token=os.getenv("METACULUS_TOKEN","")
        if len(token)<20:
            receipt["state"]="BLOCKED_NO_SECRET_TOKEN"
        else:
            try:
                from forecasting_tools import MetaculusClient
                client=MetaculusClient()
                for path in files:
                    if path.stat().st_size>65000:
                        receipt["entries"].append({"file":path.name,"state":"BLOCKED_FILE_SIZE"})
                        continue
                    try:
                        envelope=json.loads(path.read_text(encoding="utf-8"))
                        item=process_one(envelope,client,token)
                        item["sealed_file"]=path.name
                        receipt["entries"].append(item)
                    except Exception as exc:
                        receipt["entries"].append({"file":path.name,"state":"PROCESS_ERROR_NO_AUTO_RETRY",
                            "error_type":type(exc).__name__})
                receipt["state"]="BATCH_PROCESSED"
            except Exception as exc:
                receipt.update(state="BLOCKED_RUNTIME",error_type=type(exc).__name__)
    RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"state":receipt["state"],"files_seen":receipt["files_seen"],
                      "entry_states":[x["state"] for x in receipt["entries"]],
                      "forecast_confirmations":sum(x.get("forecast_confirmed") is True for x in receipt["entries"]),
                      "private_comment_confirmations":sum(x.get("comment_confirmed") is True for x in receipt["entries"])}))
    return 0 if receipt["state"] in ("NO_NEW_ENCRYPTED_FORECAST","BATCH_PROCESSED") else 2
if __name__=="__main__":sys.exit(main())
