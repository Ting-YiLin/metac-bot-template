"""Read-only format smoke against actual OPEN MiniBench question metadata.

Creates synthetic forecast distributions in memory ONLY to validate the
platform SDK's option/bound/scaling conversion. NEVER POSTs or queues them.
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
from pathlib import Path

from all_types_adapter import KINDS,make_api_payload
from minibench_readonly_probe import state_is_open

OUT=Path("minibench_format_probe_receipt.json")
LEVELS=(.1,.2,.4,.6,.8,.9)

def synthetic_shape(q):
    name=type(q).__name__
    if name=="BinaryQuestion":
        return {"question_type":name,"p_yes":0.5}
    if name=="MultipleChoiceQuestion":
        labels=list(q.options)
        if not 2<=len(labels)<=500:
            raise ValueError("OPTION_COUNT")
        p=1/len(labels)
        if p<0.001:
            raise ValueError("OPTION_MIN_PROBABILITY")
        return {"question_type":name,
                "option_probabilities":{label:p for label in labels}}
    if name in ("NumericQuestion","DateQuestion","DiscreteQuestion"):
        is_date=name=="DateQuestion"
        low=q.lower_bound.timestamp() if is_date else float(q.lower_bound)
        high=q.upper_bound.timestamp() if is_date else float(q.upper_bound)
        if not math.isfinite(low) or not math.isfinite(high) or not high>low:
            raise ValueError("BAD_BOUNDS")
        zero=getattr(q,"zero_point",None)
        values=[]
        for p in LEVELS:
            if zero is not None:
                ratio=(high-zero)/(low-zero)
                x=low+(high-low)*(ratio**p-1)/(ratio-1)
            else:
                x=low+(high-low)*p
            if is_date:
                value=dt.datetime.fromtimestamp(x,tz=dt.timezone.utc).isoformat()
            else:
                value=x
            values.append({"p":p,"value":value})
        return {"question_type":name,"percentiles":values}
    raise ValueError("UNSUPPORTED_TYPE")

def collect(client):
    rows=client.get_all_open_questions_from_tournament("minibench")
    receipt={"scope":"READ_ONLY_FORMAT_SMOKE_SYNTHETIC_NO_POST",
             "checked_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
             "tournament":"minibench","api_rows":0,"passed":0,"blocked":0,
             "results":[],"forecast_submissions":0}
    for q in rows:
        receipt["api_rows"]+=1
        typ=type(q).__name__
        label={"question_type":typ,"status":"NOT_CHECKED"}
        if not state_is_open(q) or getattr(q,"already_forecasted",None) is not False:
            label["status"]="SKIPPED_NOT_ELIGIBLE"
        elif typ not in KINDS:
            label["status"]="UNSUPPORTED_COMPLEX_TYPE"
            receipt["blocked"]+=1
        else:
            try:
                shape=synthetic_shape(q)
                payload,readback=make_api_payload(shape,q)
                label["status"]="FORMAT_OK"
                label["vector_length"]=len(readback)
                receipt["passed"]+=1
            except Exception as exc:
                label["status"]="FORMAT_BLOCKED"
                label["error_type"]=type(exc).__name__
                receipt["blocked"]+=1
        receipt["results"].append(label)
    return receipt

def main():
    try:
        if not os.getenv("METACULUS_TOKEN"):
            raise ValueError("TOKEN_MISSING")
        from forecasting_tools import MetaculusClient
        receipt=collect(MetaculusClient())
        OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"status":"FORMAT_SMOKE_COMPLETED","passed":receipt["passed"],
                          "blocked":receipt["blocked"],"types":receipt["results"],
                          "submitted":0},ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"FORMAT_SMOKE_BLOCKED","error_type":type(exc).__name__,
                          "submitted":0},ensure_ascii=False))
        return 2

if __name__=="__main__":raise SystemExit(main())
