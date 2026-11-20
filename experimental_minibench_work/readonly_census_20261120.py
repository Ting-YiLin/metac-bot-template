#!/usr/bin/env python3
"""One-shot MiniBench metadata census. GET only; never forecasts or comments."""
import collections
import datetime as dt
import json
import os
import urllib.parse
import urllib.request

START = dt.datetime.fromisoformat("2026-11-19T04:00:00+00:00")
END = dt.datetime.fromisoformat("2026-11-20T04:00:00+00:00")
API = "https://www.metaculus.com/api/posts/"
token = os.environ.get("METACULUS_TOKEN", "")
if not token:
    raise SystemExit("BLOCKED_NO_TOKEN")
def get_json(url):
    if not url.startswith(API) or urllib.parse.urlparse(url).netloc != "www.metaculus.com":
        raise RuntimeError("BAD_NEXT_URL")
    hdr = {"Accept": "application/json", "User-Agent": "MiniBenchMetadataCensus/20261120"}
    if token:
        hdr["Authorization"] = "Token " + token
    req=urllib.request.Request(url, headers=hdr, method="GET")
    with urllib.request.urlopen(req, timeout=35) as resp:
        return json.loads(resp.read())
def iso(v):
    if not isinstance(v,str) or not v:
        return None
    try:
        return dt.datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(dt.timezone.utc)
    except (ValueError,TypeError):
        return None
def inrange(v):
    t=iso(v)
    return t is not None and START<=t<END
def classify(post):
    q=post.get("question") or {}
    return str(q.get("type") or post.get("forecast_type") or ("conditional" if post.get("conditional") else ("group_of_questions" if post.get("group_of_questions") else "unknown")))
def safeval(v):
    return v if isinstance(v,(str,int,float,bool)) or v is None else None

params=urllib.parse.urlencode({"tournaments":"minibench","limit":100,"offset":0})
next_url=API+"?"+params
posts=[]
seen_urls=set()
for page in range(10):
    if not next_url: break
    if next_url in seen_urls:raise RuntimeError("PAGINATION_LOOP")
    seen_urls.add(next_url)
    payload=get_json(next_url)
    if not isinstance(payload,dict) or not isinstance(payload.get("results"),list):
        raise RuntimeError("INVALID_RESPONSE_SHAPE")
    posts.extend(payload["results"])
    next_url=payload.get("next")
    if next_url:
        next_url=urllib.parse.urljoin(API,next_url)
else:
    if next_url:raise RuntimeError("PAGINATION_EXCEEDED")
rows=[]
seen_posts=set()
for p in posts:
    if not isinstance(p,dict):continue
    pid=p.get("id")
    if pid in seen_posts:continue
    seen_posts.add(pid)
    q=p.get("question") or {}
    if not isinstance(q,dict):q={}
    row={"post_id":safeval(pid),"question_id":safeval(q.get("id")),"type":classify(p),"status":safeval(p.get("status")),"created_at":safeval(p.get("created_at")),"published_at":safeval(p.get("published_at")),"open_time":safeval(p.get("open_time")),"scheduled_close_time":safeval(p.get("scheduled_close_time")),"actual_close_time":safeval(p.get("actual_close_time")),"question_created_at":safeval(q.get("created_at")),"question_open_time":safeval(q.get("open_time"))}
    row["created_during_window"]=inrange(row["created_at"]) or inrange(row["question_created_at"])
    row["published_during_window"]=inrange(row["published_at"])
    row["opened_during_window"]=inrange(row["open_time"]) or inrange(row["question_open_time"])
    row["closed_during_window"]=inrange(row["actual_close_time"]) or inrange(row["scheduled_close_time"])
    rows.append(row)
counts=collections.Counter(x["status"] for x in rows)
types=collections.Counter(x["type"] for x in rows)
events={k:sum(bool(x[k]) for x in rows) for k in ("created_during_window","published_during_window","opened_during_window","closed_during_window")}
missing={k:sum(x[k] is None for x in rows) for k in ("created_at","published_at","open_time","scheduled_close_time","actual_close_time")}
out={"audit":"MINIBENCH_ONE_SHOT_METADATA_GET_ONLY","window_start_utc":START.isoformat(),"window_end_utc":END.isoformat(),"query":"tournaments=minibench;all statuses;paginated","raw_results":len(posts),"unique_posts":len(rows),"status_counts":dict(counts),"type_counts":dict(types),"window_events":events,"missing_timestamps":missing,"complete_listing":not bool(next_url),"rows":sorted(rows,key=lambda x:str(x["post_id"]))}
with open("minibench_census_20261120.json","w",encoding="utf-8") as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False))
for x in out["rows"]:
    print("ROW_META "+json.dumps(x,ensure_ascii=False,separators=(",",":")))
