"""Persist MINIMAL public audit of each scoring run on the isolated state branch.

Never transmits probabilities, CDFs, quantiles, private reasons, tokens,
encrypted forecast payloads, or raw request/response bodies.
"""
from __future__ import annotations
import base64
import json
import os
import re
from pathlib import Path
import requests

REPO="Ting-YiLin/metac-bot-template"
BRANCH="tingyi001-test-state"
OUT=Path("minibench_live_submit_receipt.json")
ALLOWED_ENTRY=("state","question_id","post_id","forecast_type",
               "forecast_post_attempted","forecast_confirmed","comment_confirmed",
               "comment_post_state","forecast_post_returned","forecast_http_status",
               "forecast_post_error_type","error_type","preflight_exact_readback_state",
               "forecast_readback_state","readback_expected_length",
               "deadline_utc","sealed_file","account_competition_admission_verified",
               "forecast_author","subagent_call_status","model_attestation")

def redacted_snapshot(doc,run_id):
    if doc.get("raw_forecasts_redacted") is not True or str(doc.get("run_id"))!=str(run_id):
        raise ValueError("RUN_ID_OR_REDACTION_INVALID")
    entries=doc.get("entries")
    if not isinstance(entries,list):
        raise ValueError("ENTRIES_NOT_LIST")
    status={
        "schema_version":1,
        "scope":"PUBLIC_MINIBENCH_SCORING_STATUS_NO_FORECASTS",
        "run_id":str(run_id),
        "workflow":doc.get("workflow"),
        "processed_at_utc":doc.get("processed_at_utc"),
        "state":doc.get("state"),
        "files_seen":doc.get("files_seen"),
        "entries":[{k:item[k] for k in ALLOWED_ENTRY if k in item} for item in entries],
    }
    # Status enumerations and identifiers only, no free-text model output.
    for item in status["entries"]:
        if not isinstance(item.get("state"),str) or len(item["state"])>120:
            raise ValueError("INVALID_ENTRY_STATUS")
    return status

def publish(doc,token,run_id,session=requests):
    if not token:
        raise RuntimeError("GITHUB_TOKEN_MISSING")
    if not re.fullmatch(r"\d{6,20}",str(run_id)):
        raise ValueError("INVALID_RUN_ID")
    doc=redacted_snapshot(doc,run_id)
    path=f"state/minibench_live_receipts/run-{run_id}.json"
    url=f"https://api.github.com/repos/{REPO}/contents/{path}"
    headers={"Authorization":"Bearer "+token,
             "Accept":"application/vnd.github+json",
             "User-Agent":"MiniBenchPublicStatusOnly"}
    body={"branch":BRANCH,"message":"Archive redacted MiniBench all-format scoring status for run "+str(run_id),
          "content":base64.b64encode((json.dumps(doc,ensure_ascii=False,indent=2)+"\n").encode()).decode()}
    r=session.put(url,headers=headers,json=body,timeout=30)
    if r.status_code!=201:
        raise RuntimeError("RECEIPT_ARCHIVE_HTTP_"+str(r.status_code))
    return path

def main():
    try:
        run_id=os.getenv("GITHUB_RUN_ID","")
        doc=json.loads(OUT.read_text(encoding="utf-8"))
        path=publish(doc,os.getenv("GITHUB_TOKEN",""),run_id)
        print(json.dumps({"status":"REDACTED_RECEIPT_ARCHIVED","run_id":run_id,"path":path}))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"REDACTED_RECEIPT_ARCHIVE_FAILED","error_type":type(exc).__name__}))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
